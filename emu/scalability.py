#!/usr/bin/env python3
"""
Scalability test for NDNd DV routing on NxN grid topologies.

Measures DV convergence time, file-transfer success, and memory usage
across increasing grid sizes. Results are written to a CSV file that
can be plotted with plot.py.

Usage (inside container):
    python3 emu/scalability.py
    python3 emu/scalability.py --grids 2 3 4 5 --trials 3 --out results/emu
"""

import argparse
import os
import struct
import sys
import time

from mininet.log import setLogLevel, info

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd_fw import NDNd_FW
from minindn.helpers import dv_util

# Allow imports from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import add_config_arg, load_config, dv_config_from
from lib.topology import build_grid_topo, grid_stats
from lib.result_adapter import ResultWriter, emu_trial_result

NETWORK = "/minindn"

# Byte pattern for user traffic name /ndn/test (GenericNameComponent x2)
_USER_NAME_BYTES = b"\x08\x03ndn\x08\x04test"


def _unwrap_lp(payload):
    """Return the inner NDN TLV fragment from an LP packet, or payload unchanged."""
    if not payload or payload[0] != 100:
        return payload
    i = 1
    # Skip LP outer length
    if i < len(payload) and payload[i] >= 0xFD:
        i += 3
    else:
        i += 1
    # Walk LP fields to find Fragment (type=80)
    while i + 1 < len(payload):
        t = payload[i]; i += 1
        if t >= 0xFD:
            if i + 2 < len(payload):
                t = struct.unpack_from("!H", payload, i + 1)[0]; i += 3
            else:
                break
        if i < len(payload) and payload[i] >= 0xFD:
            if i + 2 < len(payload):
                l = struct.unpack_from("!H", payload, i + 1)[0]; i += 3
            else:
                break
        elif i < len(payload):
            l = payload[i]; i += 1
        else:
            break
        if t == 80:  # LpPayload / Fragment
            return payload[i:i + l]
        i += l
    return payload


def _extract_udp_payload(frame, linktype):
    """Return UDP payload for an IPv4 packet, or None.

    This strips L2/L3/L4 headers so accounting only measures NDN payload bytes.
    """
    l2_len = {1: 14, 113: 16, 276: 20}.get(linktype)
    if l2_len is None or len(frame) < l2_len + 20:
        return None

    ip = frame[l2_len:]
    if (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ihl < 20 or len(ip) < ihl + 8:
        return None
    if ip[9] != 17:  # UDP
        return None

    udp = ip[ihl:]
    src_port, dst_port, udp_len = struct.unpack_from("!HHH", udp, 0)
    if src_port != 6363 and dst_port != 6363:
        return None
    if udp_len < 8 or len(udp) < udp_len:
        return None
    return udp[8:udp_len]


def _parse_pcap_ndn(pcap_path, start_ts=None, end_ts=None):
    """Count user and DV packets/bytes from NDN payload carried by UDP/6363.

    Counts full LP packet bytes (the UDP payload) to match sim's link
    tracer, which counts the LP-encoded bytes sent through the CGo bridge.
    Classifies packets by unwrapping LP and inspecting the inner name, and
    splits user traffic into Interest and Data to mirror sim's link-trace
    UserInterest/UserData categories.

    If *start_ts* and *end_ts* (epoch floats) are given, only packets whose
    pcap timestamp falls within [start_ts, end_ts) are counted.  This trims
    the capture to the same observation window as the sim.

    Returns (user_interest_pkts, user_interest_bytes,
             user_data_pkts, user_data_bytes,
             dv_pkts, dv_bytes).
    """
    if not os.path.isfile(pcap_path):
        return 0, 0, 0, 0, 0, 0

    with open(pcap_path, "rb") as f:
        gh = f.read(24)
        if len(gh) < 24:
            return 0, 0, 0, 0, 0, 0

        magic = gh[:4]
        if magic == b"\xd4\xc3\xb2\xa1":
            endian = "<"
        elif magic == b"\xa1\xb2\xc3\xd4":
            endian = ">"
        else:
            return 0, 0, 0, 0, 0, 0

        linktype = struct.unpack(endian + "I", gh[20:24])[0]

        ui_pkts = ui_bts = 0
        ud_pkts = ud_bts = 0
        dv_pkts = dv_bts = 0
        while True:
            ph = f.read(16)
            if len(ph) < 16:
                break
            ts_sec, ts_usec, incl_len, _ = struct.unpack(endian + "IIII", ph)
            frame = f.read(incl_len)
            if len(frame) < incl_len:
                break
            if start_ts is not None:
                pkt_ts = ts_sec + ts_usec / 1e6
                if pkt_ts < start_ts or pkt_ts >= end_ts:
                    continue
            payload = _extract_udp_payload(frame, linktype)
            if payload is None:
                continue
            # Unwrap LP for classification; count full LP packet bytes
            # (= UDP payload) to match sim's link tracer which counts
            # LP-encoded bytes via the NdnPayloadTag.
            tlv = _unwrap_lp(payload)
            if not tlv or tlv[0] not in (5, 6):  # Interest or Data only
                continue
            is_interest = tlv[0] == 5
            lp_len = len(payload)
            if _USER_NAME_BYTES in tlv:
                if is_interest:
                    ui_pkts += 1
                    ui_bts += lp_len
                else:
                    ud_pkts += 1
                    ud_bts += lp_len
            else:
                dv_pkts += 1
                dv_bts += lp_len

    return ui_pkts, ui_bts, ud_pkts, ud_bts, dv_pkts, dv_bts


def _collect_ndn_traffic(hosts, cap_paths, start_ts=None, end_ts=None):
    ui_pkts = ui_bts = ud_pkts = ud_bts = dv_pkts = dv_bts = 0
    for host in hosts:
        cap = cap_paths.get(host.name)
        if not cap:
            continue
        uip, uib, udp, udb, dp, db = _parse_pcap_ndn(cap, start_ts, end_ts)
        ui_pkts += uip; ui_bts += uib
        ud_pkts += udp; ud_bts += udb
        dv_pkts += dp;  dv_bts += db
    user_pkts = ui_pkts + ud_pkts
    user_bts  = ui_bts  + ud_bts
    total_pkts = user_pkts + dv_pkts
    total_bts  = user_bts  + dv_bts
    return (total_pkts, total_bts,
            ui_pkts, ui_bts, ud_pkts, ud_bts,
            user_pkts, user_bts, dv_pkts, dv_bts)


def run_trial(grid_size, delay="10ms", bw=10, cores=0, dv_config=None,
              observation_window_s=0):
    """Run one trial on a grid_size x grid_size grid.

    Args:
        observation_window_s: Seconds to keep the experiment running after
            convergence + file transfer. Matches sim_time in sim so both
            pipelines observe the same traffic window.

    Returns a dict with metrics.
    """
    Minindn.cleanUp()

    topo, nodes = build_grid_topo(grid_size, delay=delay, bw=bw)
    num_nodes, num_links = grid_stats(grid_size)

    ndn = Minindn(topo=topo, controller=None)
    ndn.start()

    if cores > 0:
        for host in ndn.net.hosts:
            host.setCPUs(cores=cores)

    AppManager(ndn, ndn.net.hosts, NDNd_FW)

    cap_tag = f"{os.getpid()}_{int(time.time() * 1000)}"
    cap_paths = {}
    for host in ndn.net.hosts:
        cap = f"/tmp/ndnd_cap_{cap_tag}_{host.name}.pcap"
        cap_paths[host.name] = cap
        host.cmd(f"rm -f {cap}")
        host.cmd(f"tcpdump -i any -Q out -w {cap} udp port 6363 2>/dev/null &")
    time.sleep(0.3)

    dv_start = dv_util.setup(ndn, network=NETWORK, dv_config=dv_config)

    # Match sim behavior: producer and consumer both start at t=0.5s.
    src_name = "n0_0"
    dst_name = f"n{grid_size - 1}_{grid_size - 1}"
    app_prefix = "/ndn/test"
    consumer_log = "/tmp/emu-traffic-client.log"

    # Path to the locally built ndnd binary (same source as ndndSIM sim).
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    ndnd_bin = os.path.join(_script_dir, "ndnd-traffic")

    transfer_ok = False
    producer_started = False
    consumer_started = False

    if observation_window_s > 0:
        start_at = dv_start + 0.5
        now = time.time()
        if now < start_at:
            time.sleep(start_at - now)

        # Producer: prefix=/ndn/test, payload=1024B, freshness=2000ms.
        # --expose uses client origin so DV advertises the prefix globally.
        ndn.net[dst_name].cmd(
            f'{ndnd_bin} traffic producer {app_prefix}'
            f' --payload 1024 --freshness 2000 --expose'
            f' > /tmp/emu-traffic-server.log 2>/dev/null &'
        )
        producer_started = True

        # Consumer: /ndn/test/<seqno> at 10 Hz (100ms interval), lifetime=4000ms.
        # seqno encoded as GenericNameComponent text, matching sim NdndSimRegisterConsumer.
        ndn.net[src_name].cmd(
            f'{ndnd_bin} traffic consumer {app_prefix}'
            f' --interval 100 --lifetime 4000'
            f' > {consumer_log} 2>/dev/null &'
        )
        consumer_started = True

    try:
        conv_time = dv_util.converge(ndn.net.hosts, deadline=120, network=NETWORK, start=dv_start)
    except Exception:
        conv_time = -1

    # Match sim stop times: consumer at simTime-2, producer at simTime.
    if observation_window_s > 0:
        window_end = dv_start + observation_window_s
        consumer_stop = window_end - 2.0

        now = time.time()
        if consumer_started and now < consumer_stop:
            time.sleep(consumer_stop - now)
        if consumer_started:
            ndn.net[src_name].cmd("pkill -f 'ndnd-traffic traffic consumer' 2>/dev/null; true")

        now = time.time()
        if producer_started and now < window_end:
            time.sleep(window_end - now)
        if producer_started:
            ndn.net[dst_name].cmd("pkill -f 'ndnd-traffic traffic producer' 2>/dev/null; true")

        # Consider transfer successful if client received at least one Data.
        if consumer_started:
            out = ndn.net[src_name].cmd(f"cat {consumer_log} 2>/dev/null")
            transfer_ok = "received" in out

    # Collect per-node memory usage (RSS of ndnd fw processes)
    mem_samples = []
    for host in ndn.net.hosts:
        rss = host.cmd("ps -C ndnd -o rss= 2>/dev/null").strip()
        for val in rss.split("\n"):
            val = val.strip()
            if val.isdigit():
                mem_samples.append(int(val))
    avg_mem_kb = sum(mem_samples) // max(len(mem_samples), 1)

    for host in ndn.net.hosts:
        host.cmd(f"pkill -f 'tcpdump.*ndnd_cap_{cap_tag}_' 2>/dev/null; true")
    time.sleep(0.5)

    # Trim pcap analysis to the same window as sim: [dv_start, dv_start + window]
    cap_start = dv_start if observation_window_s > 0 else None
    cap_end = (dv_start + observation_window_s) if observation_window_s > 0 else None

    (total_packets, total_bytes,
     ui_pkts, ui_bts, ud_pkts, ud_bts,
     user_pkts, user_bts, dv_pkts, dv_bts) = _collect_ndn_traffic(
        ndn.net.hosts, cap_paths, start_ts=cap_start, end_ts=cap_end)

    ndn.stop()

    return {
        "grid_size": grid_size,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "convergence_s": conv_time,
        "transfer_ok": transfer_ok,
        "avg_mem_kb": avg_mem_kb,
        "total_packets": total_packets,
        "total_bytes": total_bytes,
        "user_interest_packets": ui_pkts,
        "user_interest_bytes": ui_bts,
        "user_data_packets": ud_pkts,
        "user_data_bytes": ud_bts,
        "user_packets": user_pkts,
        "user_bytes": user_bts,
        "dv_packets": dv_pkts,
        "dv_bytes": dv_bts,
    }


def main():
    parser = argparse.ArgumentParser(description="NDNd DV scalability test")
    parser.add_argument("--grids", nargs="+", type=int, default=[2, 3, 4, 5],
                        help="Grid sizes to test (default: 2 3 4 5)")
    parser.add_argument("--trials", type=int, default=1,
                        help="Repetitions per grid size (default: 1)")
    parser.add_argument("--delay", default="10ms",
                        help="Per-link delay (default: 10ms)")
    parser.add_argument("--bw", type=int, default=10,
                        help="Per-link bandwidth in Mbps (default: 10)")
    parser.add_argument("--out", default="results/emu",
                        help="Output directory (default: results/emu)")
    parser.add_argument("--cores", type=int, default=0,
                        help="Limit CPU cores per node (0 = no limit)")
    parser.add_argument("--adv-interval", type=int, default=0,
                        help="DV advertisement interval in ms (0 = use NDNd default)")
    parser.add_argument("--dead-interval", type=int, default=0,
                        help="DV router dead interval in ms (0 = use NDNd default)")
    parser.add_argument("--window", type=float, default=60,
                        help="Observation window in seconds (default: 60)")
    add_config_arg(parser)
    args = parser.parse_args()

    # Clear sys.argv so Minindn's internal argparse doesn't choke on our flags
    sys.argv = [sys.argv[0]]

    # Config file overrides CLI defaults
    if args.config:
        cfg = load_config(args.config)
        args.grids = cfg["grids"]
        args.delay = f"{cfg['delay_ms']}ms"
        args.bw = cfg["bandwidth_mbps"]
        args.trials = cfg["trials"]
        args.cores = cfg["cores"]
        args.window = cfg["window_s"]
        dv_config = dv_config_from(cfg)
    else:
        dv_config = {}
        if args.adv_interval:
            dv_config["advertise_interval"] = args.adv_interval
        if args.dead_interval:
            dv_config["router_dead_interval"] = args.dead_interval

    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "scalability.csv")

    with ResultWriter(csv_path) as writer:
        for grid_size in args.grids:
            for trial in range(1, args.trials + 1):
                info(f"\n=== Grid {grid_size}x{grid_size}, trial {trial} ===\n")
                raw = run_trial(grid_size, delay=args.delay, bw=args.bw,
                               cores=args.cores, dv_config=dv_config,
                               observation_window_s=args.window)
                result = emu_trial_result(
                    grid_size=raw["grid_size"],
                    num_nodes=raw["num_nodes"],
                    num_links=raw["num_links"],
                    convergence_s=raw["convergence_s"],
                    transfer_ok=raw["transfer_ok"],
                    avg_mem_kb=raw["avg_mem_kb"],
                    trial=trial,
                    total_packets=raw["total_packets"],
                    total_bytes=raw["total_bytes"],
                    user_packets=raw["user_packets"],
                    user_bytes=raw["user_bytes"],
                    dv_packets=raw["dv_packets"],
                    dv_bytes=raw["dv_bytes"],
                )
                writer.write(result)
                info(f"  convergence={result.convergence_s}s  "
                     f"transfer={'OK' if result.transfer_ok else 'FAIL'}  "
                     f"mem={result.avg_mem_kb}KB  "
                     f"user_interest={result.user_packets - raw['user_data_packets']}pkts  "
                     f"user_data={raw['user_data_packets']}pkts/{raw['user_data_bytes']}B  "
                     f"dv_pkts={result.dv_packets}  "
                     f"total_pkts={result.total_packets}\n")

    info(f"\nResults written to {csv_path}\n")


if __name__ == "__main__":
    setLogLevel("info")
    main()
