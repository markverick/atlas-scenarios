#!/usr/bin/env python3
"""
Sim multi-hop DV routing changes test.

Topology:  a -- b -- c -- d  (linear, 4-node)

Tests that NDNd DV correctly handles link failure/recovery and
prefix withdrawal/re-announcement in ndnSIM simulation.

Reads scenario definition from scenarios/multihop.json, generates
topology, runs the C++ multihop scenario, and reports results.

Usage:
    ./run.sh sim multihop
    python3 sim/multihop.py --ns3-dir deps/ns-3
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.topology import generate_ndnsim_linear_topo
from sim._helpers import resolve_ns3_dir, run_multihop_scenario

DEFAULT_SCENARIO = os.path.join(
    os.path.dirname(__file__), "..", "scenarios", "multihop.json"
)


def main():
    parser = argparse.ArgumentParser(description="ndndSIM multi-hop DV routing test")
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO,
                        help="Path to scenario JSON file")
    parser.add_argument("--ns3-dir", default=None)
    parser.add_argument("--out", default="results/sim")
    parser.add_argument("--cores", type=int, default=0,
                        help="Parallel build cores for ns-3 (0 = all)")
    parser.add_argument("--sim-time", type=float, default=90.0,
                        help="Total simulation time in seconds")
    args = parser.parse_args()

    with open(args.scenario) as f:
        scenario = json.load(f)

    ns3_dir = resolve_ns3_dir(args.ns3_dir)
    os.makedirs(args.out, exist_ok=True)

    # DV config from scenario
    dv_config = {}
    if scenario.get("advertise_interval"):
        dv_config["advertise_interval"] = scenario["advertise_interval"]
    if scenario.get("router_dead_interval"):
        dv_config["router_dead_interval"] = scenario["router_dead_interval"]

    # Generate topology file
    node_names = scenario["topology"]["nodes"]
    links = scenario["topology"]["links"]
    delay_ms = int(links[0].get("delay", "10ms").replace("ms", ""))
    bw = f"{links[0].get('bw', 10)}Mbps"

    topo_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
    topo_path = os.path.join(topo_dir, "topo-linear-4-multihop.txt")
    generate_ndnsim_linear_topo(node_names, bw=bw, delay_ms=delay_ms, path=topo_path)
    topo_rel = os.path.relpath(topo_path, ns3_dir)

    results_file = os.path.abspath(os.path.join(args.out, "multihop-results.json"))
    rate_csv = os.path.abspath(os.path.join(args.out, "multihop-rate-trace.csv"))
    run_log = os.path.abspath(os.path.join(args.out, "multihop-run.log"))

    # Find link to fail from scenario phases
    link_down_src = "b"
    link_down_dst = "c"
    for phase in scenario["phases"]:
        for action in phase.get("actions", []):
            if action["type"] == "link_down":
                link_down_src = action["src"]
                link_down_dst = action["dst"]
                break

    network = scenario.get("network", "/minindn")
    prefix = scenario.get("app_prefix", "/app/data")
    consumer = scenario.get("consumer", "a")
    producer = scenario.get("producer", "d")

    print(f"=== Sim multihop: {' -- '.join(node_names)} ===")
    print(f"    prefix={prefix}  consumer={consumer}  producer={producer}")
    print(f"    link_fail={link_down_src}--{link_down_dst}")
    print(f"    dv_config={dv_config}")

    run_multihop_scenario(
        ns3_dir,
        topo=topo_rel,
        results_file=results_file,
        rate_trace=rate_csv,
        prefix=prefix,
        network=network,
        consumer=consumer,
        producer=producer,
        link_down_src=link_down_src,
        link_down_dst=link_down_dst,
        sim_time=args.sim_time,
        dv_config=dv_config or None,
        cores=args.cores,
        run_log=run_log,
    )

    # Parse and display results
    with open(results_file) as f:
        results = json.load(f)

    print(f"\n{'=' * 60}")
    print("Results")
    passed = 0
    total = len(results)
    for r in results:
        tag = "PASS" if r["passed"] else "FAIL"
        print(f"  [{tag}] {r['phase']}: {r['assertion']}")
        if r["passed"]:
            passed += 1

    print(f"\n{passed}/{total} assertions passed")

    if passed < total:
        # Print the run log for debugging
        if os.path.isfile(run_log):
            print(f"\n--- Simulation log ({run_log}) ---")
            with open(run_log) as f:
                print(f.read())

    return passed == total


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
