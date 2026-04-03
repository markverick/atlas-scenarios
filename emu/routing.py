#!/usr/bin/env python3
"""
Routing-only emulation — measure DV routing traffic burst (no app traffic).

Usage (inside container, needs sudo):
    python3 emu/routing.py
    python3 emu/routing.py --grids 2 3 4 --out results/emu_routing
"""

import argparse
import json
import os
import shutil
import sys
import time

from mininet.log import setLogLevel, info
from minindn.helpers import dv_util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import add_grid_scenario_args, apply_config_overrides
from lib.pcap import collect_traffic
from lib.result_adapter import ResultWriter, TrialResult, parse_router_reachable_logs
from emu._helpers import (
    NETWORK,
    setup_grid, start_tcpdump, stop_tcpdump, collect_memory,
)


def run_trial(grid_size, delay_ms=10, bw_mbps=10, cores=0, dv_config=None,
              observation_window_s=30):
    """Run one routing-only trial on a grid_size x grid_size grid."""
    ndn, num_nodes, num_links = setup_grid(grid_size, delay_ms, bw_mbps, cores)
    cap_tag, cap_paths = start_tcpdump(ndn.net.hosts, prefix="ndnd_rcap")

    dv_start = dv_util.setup(ndn, network=NETWORK, dv_config=dv_config)

    # No probe prefix — convergence is measured event-driven from DV
    # "Router is now reachable" log events (identical to sim approach).

    try:
        dv_util.converge(ndn.net.hosts, deadline=120,
                         network=NETWORK, start=dv_start)
    except Exception:
        pass

    window_end = dv_start + observation_window_s
    now = time.time()
    if now < window_end:
        time.sleep(window_end - now)

    avg_mem_kb = collect_memory(ndn.net.hosts)
    stop_tcpdump(ndn.net.hosts, cap_tag, prefix="ndnd_rcap")

    traffic = collect_traffic(cap_paths.values())

    dv_log_paths = [
        os.path.join(h.params['params']['homeDir'], 'log', 'dv.log')
        for h in ndn.net.hosts
    ]
    conv_time = parse_router_reachable_logs(dv_log_paths, num_nodes=num_nodes)

    ndn.stop()

    return {
        "grid_size": grid_size,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "convergence_s": conv_time,
        "avg_mem_kb": avg_mem_kb,
        "traffic": traffic,
        "pcap_paths": list(cap_paths.values()),
        "dv_start": dv_start,
    }


def main():
    parser = argparse.ArgumentParser(
        description="NDNd DV routing-only traffic measurement")
    add_grid_scenario_args(parser, default_out="results/emu_routing",
                           default_window=30.0)
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]

    delay_ms, bw_mbps, dv_config = apply_config_overrides(args)

    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "scalability.csv")

    with ResultWriter(csv_path) as writer:
        for grid_size in args.grids:
            for trial in range(1, args.trials + 1):
                info(f"\n=== Routing-only: Grid {grid_size}x{grid_size}, trial {trial} ===\n")
                raw = run_trial(grid_size, delay_ms=delay_ms, bw_mbps=bw_mbps,
                               cores=args.cores, dv_config=dv_config,
                               observation_window_s=args.window)
                t = raw["traffic"]

                # Save pcap copies and per-packet manifest for time-series plotting
                tag = f"routing-{grid_size}x{grid_size}-t{trial}"
                saved_pcaps = []
                for i, src in enumerate(raw["pcap_paths"]):
                    dst = os.path.join(args.out, f"pcap-{tag}-n{i}.pcap")
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                        saved_pcaps.append(dst)
                manifest = {
                    "pcap_paths": saved_pcaps,
                    "dv_start": raw["dv_start"],
                }
                with open(os.path.join(args.out, f"pcap-manifest-{tag}.json"), "w") as mf:
                    json.dump(manifest, mf)

                result = TrialResult(
                    grid_size=raw["grid_size"],
                    num_nodes=raw["num_nodes"],
                    num_links=raw["num_links"],
                    trial=trial,
                    convergence_s=raw["convergence_s"],
                    transfer_ok=raw["convergence_s"] >= 0,
                    avg_mem_kb=raw["avg_mem_kb"],
                    total_packets=t.routing_packets,
                    total_bytes=t.routing_bytes,
                    dv_packets=t.dv_packets + t.pfxsync_packets,
                    dv_bytes=t.dv_bytes + t.pfxsync_bytes,
                )
                writer.write(result)
                info(f"  convergence={result.convergence_s}s  "
                     f"dv_pkts={result.dv_packets}  "
                     f"dv_bytes={result.dv_bytes}  "
                     f"mem={result.avg_mem_kb}KB\n")

    info(f"\nResults written to {csv_path}\n")


if __name__ == "__main__":
    setLogLevel("info")
    main()
