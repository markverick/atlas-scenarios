#!/usr/bin/env python3
"""
Churn scenario — two-phase measurement in emulation (Mini-NDN).

Phase 1 (convergence): DV boot → converge → announce prefixes → stabilize.
Phase 2 (churn):       Link fail/recover + prefix withdraw/re-announce.

Supports any topology registered in lib/churn_common.KNOWN_TOPOLOGIES, as well
as arbitrary NxN grid topologies.  The topology type is selected by the JSON
config key "topology" (default: "grid").

For each topology (or grid size), runs three variants:
  1. baseline  — no prefixes (pure DV overhead under churn)
  2. two_step  — DV + PrefixSync under churn
  3. one_step  — prefixes in DV adverts under churn

Usage (needs sudo):
  sudo python3 emu/churn.py --config scenarios/churn.json
  sudo python3 emu/churn.py --config scenarios/churn_4x4.json
  sudo python3 emu/churn.py --config scenarios/churn_sprint.json
"""

import argparse
import csv
import os
import sys
import time
import threading

from mininet.log import setLogLevel, info

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import load_config, dv_config_from
from lib.pcap import parse_pcap_packets
from lib.result_adapter import parse_router_reachable_logs
from emu._helpers import (
    NETWORK,
    setup_grid, setup_conf_topo, start_tcpdump, stop_tcpdump,
)
from minindn.helpers import dv_util
from lib.churn_common import (
    FIELDNAMES, KNOWN_TOPOLOGIES,
    parse_packet_events_by_phase, build_result_rows,
    make_tag, auto_plot, default_out_dir, grid_churn_targets,
)


# ---- Host-level prefix management (topology-agnostic) ----

def announce_prefixes(hosts, num_prefixes):
    """Announce synthetic prefixes on each host via ``ndnd put --expose``."""
    announced = []
    for host in hosts:
        for j in range(num_prefixes):
            pfx = f"/data/{host.name}/pfx{j}"
            host.cmd(f'ndnd put --expose "{pfx}" < /dev/null &')
            announced.append((host, pfx))
    time.sleep(0.5)
    return announced


def withdraw_prefix(host, pfx):
    """Kill background ``ndnd put --expose`` for a specific prefix."""
    host.cmd(f"pkill -f 'ndnd put --expose.*{pfx}' 2>/dev/null; true")


def withdraw_all(announced):
    """Kill all background ``ndnd put --expose`` processes."""
    for host, pfx in announced:
        withdraw_prefix(host, pfx)
    time.sleep(0.3)


# ---- Churn event scheduler ----

def schedule_churn_events(ndn, hosts, num_prefixes, phase2_start_epoch,
                          *, link_src, link_dst, churn_node):
    """Schedule churn events as timed threads (wall-clock based).

    Events:
      +0.1s : link_down  link_src -- link_dst
      +2.0s : prefix_withdraw on churn_node (if prefixes > 0)
      +5.1s : link_up    link_src -- link_dst
      +7.0s : prefix_announce  on churn_node (if prefixes > 0)
    """
    if link_src is None or link_dst is None:
        return []

    src_host = next(h for h in hosts if h.name == churn_node)
    timers = []

    def do_link_down():
        info(f"  CHURN: link DOWN {link_src}--{link_dst}\n")
        ndn.net.configLinkStatus(link_src, link_dst, "down")

    def do_link_up():
        info(f"  CHURN: link UP {link_src}--{link_dst}\n")
        ndn.net.configLinkStatus(link_src, link_dst, "up")

    t1 = threading.Timer(phase2_start_epoch + 0.1 - time.time(), do_link_down)
    t2 = threading.Timer(phase2_start_epoch + 5.1 - time.time(), do_link_up)
    t1.start()
    t2.start()
    timers.extend([t1, t2])

    if num_prefixes > 0 and churn_node:
        pfx = f"/data/{churn_node}/pfx0"

        def do_withdraw():
            info(f"  CHURN: prefix WITHDRAW {churn_node} {pfx}\n")
            withdraw_prefix(src_host, pfx)

        def do_reannounce():
            info(f"  CHURN: prefix ANNOUNCE {churn_node} {pfx}\n")
            src_host.cmd(f'ndnd put --expose "{pfx}" < /dev/null &')

        t3 = threading.Timer(phase2_start_epoch + 2.0 - time.time(), do_withdraw)
        t4 = threading.Timer(phase2_start_epoch + 7.0 - time.time(), do_reannounce)
        t3.start()
        t4.start()
        timers.extend([t3, t4])

    return timers


# ---- Variant runner ----

def _run_one_variant(*, ndn_factory, topology, topo_id_str,
                     grid_size, num_nodes, num_links,
                     link_src, link_dst, churn_node,
                     trial, mode, num_prefixes, window_s,
                     dv_config, sim_time, deadline, out_dir):
    """Run one variant and return a list of result dicts."""
    tag = make_tag(mode, topo_id_str, num_prefixes, trial)
    pfx_count = num_prefixes if mode != "baseline" else 0
    phase2_start_rel = sim_time / 2.0

    info(f"\n=== {mode}: {topo_id_str} ({num_nodes} nodes), "
         f"prefixes={pfx_count}, trial {trial} ===\n")

    dvc = dict(dv_config) if dv_config else {}
    if mode in ("one_step", "baseline"):
        dvc["one_step"] = True
    else:
        dvc.pop("one_step", None)

    ndn, num_nodes, num_links = ndn_factory()
    cap_tag, cap_paths = start_tcpdump(ndn.net.hosts, prefix="ndnd_churn")

    dv_start = dv_util.setup(ndn, network=NETWORK, dv_config=dvc or None)

    try:
        dv_util.converge(ndn.net.hosts, deadline=deadline,
                         network=NETWORK, start=dv_start)
    except Exception:
        pass

    # Announce synthetic prefixes
    announced = []
    if pfx_count > 0:
        announced = announce_prefixes(ndn.net.hosts, pfx_count)

    # Schedule churn events
    phase2_start_epoch = dv_start + phase2_start_rel
    timers = schedule_churn_events(
        ndn, ndn.net.hosts, pfx_count, phase2_start_epoch,
        link_src=link_src, link_dst=link_dst, churn_node=churn_node)

    # Wait for observation window
    window_end = dv_start + sim_time
    now = time.time()
    if now < window_end:
        time.sleep(window_end - now)

    for t in timers:
        t.cancel()

    stop_tcpdump(ndn.net.hosts, cap_tag, prefix="ndnd_churn")

    # Parse per-packet events
    pkt_events = parse_pcap_packets(cap_paths.values(), time_origin=dv_start)

    # Save per-packet CSV
    pkt_csv = os.path.join(out_dir, f"packet-trace-{tag}.csv")
    with open(pkt_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time", "Category", "Bytes"])
        for t_s, cat, b in pkt_events:
            w.writerow([f"{t_s:.6f}", cat, b])

    # Split traffic by phase
    phases = parse_packet_events_by_phase(pkt_events, phase2_start_rel)

    # Convergence from DV logs
    dv_log_paths = [
        os.path.join(h.params['params']['homeDir'], 'log', 'dv.log')
        for h in ndn.net.hosts
    ]
    conv_time = parse_router_reachable_logs(dv_log_paths, num_nodes=num_nodes)

    if announced:
        withdraw_all(announced)
    ndn.stop()

    return build_result_rows(
        phases,
        topology=topology,
        grid_size=grid_size,
        num_nodes=num_nodes,
        num_links=num_links,
        trial=trial,
        mode=mode,
        num_prefixes=pfx_count,
        window_s=window_s,
        convergence_s=conv_time,
    )


# ---- Topology dispatchers ----

def _run_grid(cfg, dv_config, out_dir, writer, f):
    """Run churn experiments over one or more NxN grid topologies."""
    from lib.topology import grid_stats

    num_prefixes = cfg.get("num_prefixes", 10)
    sim_time = cfg["window_s"]
    delay_ms = cfg["delay_ms"]
    bw_mbps = cfg["bandwidth_mbps"]
    cores = cfg["cores"]
    trials = cfg["trials"]

    for grid_size in cfg["grids"]:
        link_src, link_dst, churn_node = grid_churn_targets(grid_size)
        num_nodes, num_links = grid_stats(grid_size)

        def ndn_factory(gs=grid_size):
            return setup_grid(gs, delay_ms, bw_mbps, cores)

        for trial in range(1, trials + 1):
            for mode in ("baseline", "two_step", "one_step"):
                rows = _run_one_variant(
                    ndn_factory=ndn_factory,
                    topology="grid",
                    topo_id_str=f"{grid_size}x{grid_size}",
                    grid_size=grid_size,
                    num_nodes=num_nodes,
                    num_links=num_links,
                    link_src=link_src,
                    link_dst=link_dst,
                    churn_node=churn_node,
                    trial=trial,
                    mode=mode,
                    num_prefixes=num_prefixes,
                    window_s=sim_time,
                    dv_config=dv_config,
                    sim_time=sim_time,
                    deadline=120,
                    out_dir=out_dir,
                )
                _write_rows(writer, f, rows)


def _run_conf(cfg, dv_config, out_dir, writer, f, topo_name):
    """Run churn experiments on a conf-based topology (Sprint, etc.)."""
    from lib.topology import conf_stats

    info_entry = KNOWN_TOPOLOGIES[topo_name]
    conf_path = os.path.abspath(info_entry["conf_path"])
    link_src, link_dst = info_entry["churn_link"]
    churn_node = info_entry["churn_node"]

    num_prefixes = cfg.get("num_prefixes", 5)
    sim_time = cfg["window_s"]
    delay_ms = cfg["delay_ms"]
    bw_mbps = cfg["bandwidth_mbps"]
    cores = cfg["cores"]
    trials = cfg["trials"]

    num_nodes, num_links = conf_stats(conf_path)
    info(f"{topo_name} topology: {num_nodes} nodes, {num_links} links\n")

    def ndn_factory():
        return setup_conf_topo(conf_path, delay_ms, bw_mbps, cores)

    for trial in range(1, trials + 1):
        for mode in ("baseline", "two_step", "one_step"):
            rows = _run_one_variant(
                ndn_factory=ndn_factory,
                topology=topo_name,
                topo_id_str=topo_name,
                grid_size=0,
                num_nodes=num_nodes,
                num_links=num_links,
                link_src=link_src,
                link_dst=link_dst,
                churn_node=churn_node,
                trial=trial,
                mode=mode,
                num_prefixes=num_prefixes,
                window_s=sim_time,
                dv_config=dv_config,
                sim_time=sim_time,
                deadline=300,
                out_dir=out_dir,
            )
            _write_rows(writer, f, rows)


def _write_rows(writer, f, rows):
    for row in rows:
        writer.writerow(row)
        f.flush()
        print(f"  [{row['phase']}] dv={row['dv_advert_bytes']}B"
              f"  pfx={row['pfxsync_bytes']}B"
              f"  total={row['total_routing_bytes']}B")


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(
        description="Emu: churn scenario — two-phase routing traffic measurement")
    parser.add_argument("--config", required=True,
                        help="JSON scenario config file")
    parser.add_argument("--out", default=None,
                        help="Output directory (auto-derived from config)")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]

    cfg = load_config(args.config)
    dv_config = dv_config_from(cfg)

    topo_name = cfg.get("topology", "grid")

    if args.out is None:
        args.out = default_out_dir(cfg, "emu")
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    out_csv = os.path.join(out_dir, "churn.csv")
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

        if topo_name == "grid":
            _run_grid(cfg, dv_config, out_dir, writer, f)
        elif topo_name in KNOWN_TOPOLOGIES:
            _run_conf(cfg, dv_config, out_dir, writer, f, topo_name)
        else:
            print(f"Unknown topology '{topo_name}'. "
                  f"Known: grid, {', '.join(KNOWN_TOPOLOGIES)}")
            sys.exit(1)

    print(f"\nResults written to {out_csv}")

    auto_plot(out_dir, emu_dir=out_dir)


if __name__ == "__main__":
    setLogLevel("info")
    main()
