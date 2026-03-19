#!/usr/bin/env python3
"""
Sim demo: 3-node linear topology with NDNd DV routing.

Topology:  a -- b -- c
Consumer at a, Producer at c.

Mirrors emu/demo.py but runs in ndndSIM instead of Mini-NDN.

Usage:
    python3 sim/demo.py
    python3 sim/demo.py --ns3-dir deps/ns-3 --sim-time 20
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.topology import generate_ndnsim_linear_topo
from lib.result_adapter import parse_conv_trace, parse_sim_convergence
from sim._helpers import resolve_ns3_dir, run_scenario

NODES = ["a", "b", "c"]


def main():
    parser = argparse.ArgumentParser(description="ndndSIM 3-node demo")
    parser.add_argument("--delay", type=int, default=10, help="Per-link delay in ms")
    parser.add_argument("--bw", default="10Mbps")
    parser.add_argument("--sim-time", type=float, default=20.0)
    parser.add_argument("--ns3-dir", default=None)
    parser.add_argument("--out", default="results/sim")
    parser.add_argument("--cores", type=int, default=0,
                        help="Parallel build cores for ns-3 (0 = all)")
    args = parser.parse_args()

    ns3_dir = resolve_ns3_dir(args.ns3_dir)
    os.makedirs(args.out, exist_ok=True)

    # Write topology file
    topo_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
    topo_path = os.path.join(topo_dir, "topo-linear-3-atlas.txt")
    generate_ndnsim_linear_topo(NODES, bw=args.bw, delay_ms=args.delay, path=topo_path)
    topo_rel = os.path.relpath(topo_path, ns3_dir)

    rate_csv = os.path.abspath(os.path.join(args.out, "demo-rate-trace.csv"))
    conv_file = os.path.abspath(os.path.join(args.out, "demo-conv.txt"))

    print("=== Sim demo: 3-node linear (a -- b -- c) ===")
    run_scenario(
        ns3_dir,
        topo=topo_rel,
        rate_trace=rate_csv,
        sim_time=args.sim_time,
        consumer="a",
        producer="c",
        prefix="/ndn/c/test",
        cores=args.cores,
        conv_trace=conv_file,
    )

    conv = parse_conv_trace(conv_file)
    if conv >= 0:
        print(f"SUCCESS: DV converged in {conv}s (direct RIB measurement)")
    else:
        # Fallback to rate-trace heuristic
        conv = parse_sim_convergence(rate_csv)
        if conv >= 0:
            print(f"SUCCESS: DV converged, first Data at ~{conv}s after producer start")
        else:
            print("FAIL: no Data packets received")


if __name__ == "__main__":
    main()
