#!/usr/bin/env python3
"""
One-step vs two-step routing comparison — emulation (Mini-NDN).

For each grid size, runs three variants:
  1. baseline  — no prefixes announced (pure DV overhead)
  2. two_step  — N prefixes per node, standard DV + PrefixSync
  3. one_step  — N prefixes per node, prefixes in DV adverts (no PrefixSync)

Writes a per-category traffic breakdown CSV matching the sim format.

Usage (needs sudo):
  sudo python3 emu/onestep_comparison.py --config scenarios/onestep_twostep.json
"""

import argparse
import csv
import json
import os
import shutil
import sys
import time

from mininet.log import setLogLevel, info

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import load_config, dv_config_from
from lib.pcap import collect_traffic, parse_pcap_packets
from lib.result_adapter import parse_router_reachable_logs
from emu._helpers import (
    NETWORK,
    setup_grid, start_tcpdump, stop_tcpdump, collect_memory,
)
from minindn.helpers import dv_util

FIELDNAMES = [
    "grid_size", "num_nodes", "num_links", "trial", "mode", "num_prefixes",
    "convergence_s",
    "dv_advert_pkts", "dv_advert_bytes",
    "pfxsync_pkts", "pfxsync_bytes",
    "mgmt_pkts", "mgmt_bytes",
    "total_routing_pkts", "total_routing_bytes",
]


def announce_prefixes(hosts, num_prefixes):
    """Announce synthetic prefixes on each host via `ndnd put --expose`.

    Returns list of (host, prefix) pairs for cleanup.
    """
    announced = []
    for host in hosts:
        for j in range(num_prefixes):
            pfx = f"/data/{host.name}/pfx{j}"
            # `ndnd put --expose` reads stdin for data; /dev/null = empty payload.
            # It stays running to keep the prefix announced.
            host.cmd(f'ndnd put --expose "{pfx}" < /dev/null &')
            announced.append((host, pfx))
    time.sleep(0.5)
    return announced


def withdraw_prefixes(announced):
    """Kill background `ndnd put --expose` processes."""
    for host, pfx in announced:
        host.cmd(f"pkill -f 'ndnd put --expose.*{pfx}' 2>/dev/null; true")
    time.sleep(0.3)


def run_variant(grid_size, trial, mode, num_prefixes,
                delay_ms, bw_mbps, cores, dv_config, sim_time, out_dir):
    """Run one variant and return a result dict."""
    tag = f"{mode}-{grid_size}x{grid_size}-p{num_prefixes}-t{trial}"
    pfx_count = num_prefixes if mode != "baseline" else 0

    info(f"\n=== {mode}: grid {grid_size}x{grid_size}, "
         f"prefixes={pfx_count}, trial {trial} ===\n")

    # Set up dv_config for this variant
    dvc = dict(dv_config) if dv_config else {}
    if mode in ("one_step", "baseline"):
        # Baseline uses one_step=true with 0 prefixes so PrefixSync SVS
        # is disabled — giving a pure-DV floor with no sync overhead.
        dvc["one_step"] = True
    else:
        dvc.pop("one_step", None)

    ndn, num_nodes, num_links = setup_grid(grid_size, delay_ms, bw_mbps, cores)
    cap_tag, cap_paths = start_tcpdump(ndn.net.hosts, prefix="ndnd_os")

    dv_start = dv_util.setup(ndn, network=NETWORK, dv_config=dvc or None)

    try:
        dv_util.converge(ndn.net.hosts, deadline=120,
                         network=NETWORK, start=dv_start)
    except Exception:
        pass

    # Announce synthetic prefixes now that DV has converged.
    announced = []
    if pfx_count > 0:
        announced = announce_prefixes(ndn.net.hosts, pfx_count)

    # Wait for observation window
    window_end = dv_start + sim_time
    now = time.time()
    if now < window_end:
        time.sleep(window_end - now)

    stop_tcpdump(ndn.net.hosts, cap_tag, prefix="ndnd_os")

    # Parse traffic
    traffic = collect_traffic(cap_paths.values())

    # Parse per-packet events for I/O graph
    pkt_events = parse_pcap_packets(cap_paths.values(), time_origin=dv_start)
    pkt_csv = os.path.join(out_dir, f"packet-trace-{tag}.csv")
    with open(pkt_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time", "Category", "Bytes"])
        for t_s, cat, b in pkt_events:
            w.writerow([f"{t_s:.6f}", cat, b])

    # Save pcap copies
    saved_pcaps = []
    for i, (hname, src) in enumerate(sorted(cap_paths.items())):
        dst = os.path.join(out_dir, f"pcap-{tag}-n{i}.pcap")
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            saved_pcaps.append(dst)
    manifest = {"pcap_paths": saved_pcaps, "dv_start": dv_start}
    with open(os.path.join(out_dir, f"pcap-manifest-{tag}.json"), "w") as mf:
        json.dump(manifest, mf)

    # Convergence from DV logs
    dv_log_paths = [
        os.path.join(h.params['params']['homeDir'], 'log', 'dv.log')
        for h in ndn.net.hosts
    ]
    conv_time = parse_router_reachable_logs(dv_log_paths, num_nodes=num_nodes)

    # Cleanup
    if announced:
        withdraw_prefixes(announced)
    ndn.stop()

    return {
        "grid_size": grid_size,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "trial": trial,
        "mode": mode,
        "num_prefixes": pfx_count,
        "convergence_s": conv_time,
        "dv_advert_pkts": traffic.dv_packets,
        "dv_advert_bytes": traffic.dv_bytes,
        "pfxsync_pkts": traffic.pfxsync_packets,
        "pfxsync_bytes": traffic.pfxsync_bytes,
        "mgmt_pkts": traffic.mgmt_packets,
        "mgmt_bytes": traffic.mgmt_bytes,
        "total_routing_pkts": traffic.routing_packets,
        "total_routing_bytes": traffic.routing_bytes,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Emu: one-step vs two-step routing comparison")
    parser.add_argument("--config", required=True,
                        help="JSON scenario config file")
    parser.add_argument("--out", default="results/emu_onestep",
                        help="Output directory (default: results/emu_onestep)")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]  # clear args before Minindn sees them

    cfg = load_config(args.config)
    dv_config = dv_config_from(cfg)
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    num_prefixes = cfg.get("num_prefixes", 10)
    sim_time = cfg["window_s"]
    cores = cfg["cores"]
    trials = cfg["trials"]
    delay_ms = cfg["delay_ms"]
    bw_mbps = cfg["bandwidth_mbps"]

    out_csv = os.path.join(out_dir, "comparison.csv")
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

        for grid_size in cfg["grids"]:
            for trial in range(1, trials + 1):
                for mode in ("baseline", "two_step", "one_step"):
                    row = run_variant(
                        grid_size=grid_size,
                        trial=trial,
                        mode=mode,
                        num_prefixes=num_prefixes,
                        delay_ms=delay_ms,
                        bw_mbps=bw_mbps,
                        cores=cores,
                        dv_config=dv_config,
                        sim_time=sim_time,
                        out_dir=out_dir,
                    )
                    writer.writerow(row)
                    f.flush()
                    info(f"  conv={row['convergence_s']}s"
                         f"  dv={row['dv_advert_bytes']}B"
                         f"  pfx={row['pfxsync_bytes']}B"
                         f"  total={row['total_routing_bytes']}B\n")

    info(f"\nResults written to {out_csv}\n")


if __name__ == "__main__":
    setLogLevel("info")
    main()
