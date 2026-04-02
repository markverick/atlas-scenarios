#!/usr/bin/env python3
"""
ndndSIM DV scalability scenario -- NxN grid topologies.

Generates topology files, runs the parameterized atlas scenario for
each grid size, and writes results through the result adapter.

Usage:
  python3 sim/scalability.py
  python3 sim/scalability.py --grids 2 3 4 5 --delay 10 --sim-time 60
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import add_grid_scenario_args, apply_config_overrides
from lib.topology import generate_ndnsim_topo, grid_stats
from lib.result_adapter import ResultWriter, sim_trial_result
from sim._helpers import resolve_ns3_dir, run_scenario


def main():
    parser = argparse.ArgumentParser(description="ndndSIM DV scalability grid")
    add_grid_scenario_args(parser, default_out="results/sim")
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
                tag = f"{grid_size}x{grid_size}-t{trial}"
                rate_csv = os.path.abspath(os.path.join(
                    args.out, f"rate-trace-{tag}.csv"))
                conv_file = os.path.abspath(os.path.join(
                    args.out, f"conv-{tag}.txt"))
                link_csv = os.path.abspath(os.path.join(
                    args.out, f"link-trace-{tag}.csv"))

                print(f"\n=== Sim grid {grid_size}x{grid_size}, trial {trial} ===")
                run_scenario(
                    ns3_dir,
                    topo=topo_rel,
                    rate_trace=rate_csv,
                    sim_time=args.window,
                    cores=args.cores,
                    conv_trace=conv_file,
                    link_trace=link_csv,
                    dv_config=dv_config or None,
                )

                result = sim_trial_result(grid_size, num_nodes, num_links,
                                          rate_csv, trial=trial,
                                          conv_trace_path=conv_file,
                                          link_trace_path=link_csv)
                writer.write(result)
                print(f"  convergence={result.convergence_s}s"
                      f"  total_pkts={result.total_packets}"
                      f"  total_bytes={result.total_bytes}"
                      f"  dv_bytes={result.dv_bytes}")

    print(f"\nResults written to {out_csv}")


if __name__ == "__main__":
    main()
