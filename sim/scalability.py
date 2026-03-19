#!/usr/bin/env python3
"""
ndndSIM DV scalability scenario — NxN grid topologies.

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
from lib.topology import generate_ndnsim_topo, grid_stats
from lib.result_adapter import ResultWriter, sim_trial_result
from sim._helpers import resolve_ns3_dir, run_scenario


def main():
    parser = argparse.ArgumentParser(description="ndndSIM DV scalability grid")
    parser.add_argument("--grids", nargs="+", type=int, default=[2, 3, 4, 5])
    parser.add_argument("--delay", type=int, default=10, help="Per-link delay in ms")
    parser.add_argument("--bw", default="10Mbps")
    parser.add_argument("--sim-time", type=float, default=60.0)
    parser.add_argument("--ns3-dir", default=None,
                        help="Path to ns-3 root (default: deps/ns-3 or NS3_DIR env)")
    parser.add_argument("--out", default="results/sim")
    parser.add_argument("--cores", type=int, default=0,
                        help="Parallel build cores for ns-3 (0 = all)")
    args = parser.parse_args()

    ns3_dir = resolve_ns3_dir(args.ns3_dir)
    os.makedirs(args.out, exist_ok=True)
    out_csv = os.path.join(args.out, "scalability.csv")

    with ResultWriter(out_csv) as writer:
        for grid_size in args.grids:
            num_nodes, num_links = grid_stats(grid_size)

            topo_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
            os.makedirs(topo_dir, exist_ok=True)
            topo_path = os.path.join(topo_dir, f"topo-grid-{grid_size}x{grid_size}-atlas.txt")
            generate_ndnsim_topo(grid_size, bw=args.bw, delay_ms=args.delay, path=topo_path)
            topo_rel = os.path.relpath(topo_path, ns3_dir)

            rate_csv = os.path.abspath(os.path.join(
                args.out, f"rate-trace-{grid_size}x{grid_size}.csv"))
            conv_file = os.path.abspath(os.path.join(
                args.out, f"conv-{grid_size}x{grid_size}.txt"))

            print(f"\n=== Sim grid {grid_size}x{grid_size} ===")
            run_scenario(
                ns3_dir,
                topo=topo_rel,
                rate_trace=rate_csv,
                sim_time=args.sim_time,
                cores=args.cores,
                conv_trace=conv_file,
            )

            result = sim_trial_result(grid_size, num_nodes, num_links,
                                      rate_csv, conv_trace_path=conv_file)
            writer.write(result)
            print(f"  convergence={result.convergence_s}s")

    print(f"\nResults written to {out_csv}")


if __name__ == "__main__":
    main()
