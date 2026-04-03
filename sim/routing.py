#!/usr/bin/env python3
"""
ndndSIM routing-only scenario -- measure DV routing traffic burst.

Runs DV routing on NxN grid topologies with NO application traffic.
Measures routing packet counts, traffic volume, and convergence time.

Usage:
  python3 sim/routing.py
    python3 sim/routing.py --grids 2 3 4 --out results/sim_routing
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import add_grid_scenario_args, apply_config_overrides
from lib.topology import generate_ndnsim_topo, grid_stats
from lib.result_adapter import ResultWriter, TrialResult, parse_conv_trace, parse_link_trace
from sim._helpers import resolve_ns3_dir, run_routing_scenario


def main():
    parser = argparse.ArgumentParser(description="ndndSIM routing-only traffic measurement")
    add_grid_scenario_args(parser, default_out="results/sim_routing",
                           default_window=30.0)
    parser.add_argument("--ns3-dir", default=None,
                        help="Path to ns-3 root (default: deps/ns-3 or NS3_DIR env)")
    args = parser.parse_args()

    delay_ms, bw_mbps, dv_config = apply_config_overrides(args)

    ns3_dir = resolve_ns3_dir(args.ns3_dir)
    os.makedirs(args.out, exist_ok=True)
    out_csv = os.path.join(args.out, "scalability.csv")

    with ResultWriter(out_csv) as writer:
        for grid_size in args.grids:
            num_nodes, num_links = grid_stats(grid_size)

            topo_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
            os.makedirs(topo_dir, exist_ok=True)
            topo_path = os.path.join(topo_dir, f"topo-grid-{grid_size}x{grid_size}-atlas.txt")
            generate_ndnsim_topo(grid_size, bw=f"{bw_mbps}Mbps",
                                delay_ms=delay_ms, path=topo_path)
            topo_rel = os.path.relpath(topo_path, ns3_dir)

            for trial in range(1, args.trials + 1):
                tag = f"routing-{grid_size}x{grid_size}-t{trial}"
                conv_file = os.path.abspath(os.path.join(
                    args.out, f"conv-{tag}.txt"))
                link_csv = os.path.abspath(os.path.join(
                    args.out, f"link-trace-{tag}.csv"))
                pkt_csv = os.path.abspath(os.path.join(
                    args.out, f"packet-trace-{tag}.csv"))

                print(f"\n=== Routing-only: grid {grid_size}x{grid_size}, trial {trial} ===")
                run_routing_scenario(
                    ns3_dir,
                    topo=topo_rel,
                    sim_time=args.window,
                    cores=args.cores,
                    conv_trace=conv_file,
                    link_trace=link_csv,
                    packet_trace=pkt_csv,
                    dv_config=dv_config or None,
                )

                conv = parse_conv_trace(conv_file)
                traffic = parse_link_trace(link_csv)
                result = TrialResult(
                    grid_size=grid_size,
                    num_nodes=num_nodes,
                    num_links=num_links,
                    trial=trial,
                    convergence_s=conv,
                    transfer_ok=conv >= 0,
                    **traffic,
                )
                writer.write(result)
                print(f"  convergence={result.convergence_s}s"
                      f"  dv_pkts={result.dv_packets}"
                      f"  dv_bytes={result.dv_bytes}"
                      f"  total_pkts={result.total_packets}"
                      f"  total_bytes={result.total_bytes}")

    print(f"\nResults written to {out_csv}")


if __name__ == "__main__":
    main()
