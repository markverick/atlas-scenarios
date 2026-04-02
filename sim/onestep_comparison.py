#!/usr/bin/env python3
"""
One-step vs two-step routing comparison -- ndndSIM routing-only scenarios.

For each grid size, runs three variants:
  1. baseline  -- no prefixes announced (pure DV overhead)
  2. two_step  -- N prefixes per node, standard DV + PrefixSync
  3. one_step  -- N prefixes per node, prefixes in DV adverts (no PrefixSync)

Writes a per-category traffic breakdown CSV for plotting.

Usage:
  python3 sim/onestep_comparison.py --config scenarios/onestep_twostep.json
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import load_config, dv_config_from, add_config_arg
from lib.topology import generate_ndnsim_topo, grid_stats
from lib.result_adapter import parse_conv_trace
from sim._helpers import resolve_ns3_dir, run_routing_scenario


FIELDNAMES = [
    "grid_size", "num_nodes", "num_links", "trial", "mode", "num_prefixes",
    "convergence_s",
    "dv_advert_pkts", "dv_advert_bytes",
    "pfxsync_pkts", "pfxsync_bytes",
    "mgmt_pkts", "mgmt_bytes",
    "total_routing_pkts", "total_routing_bytes",
]

CATEGORIES = ["DvAdvert", "PrefixSync", "Mgmt",
              "UserInterest", "UserData", "Other"]


def parse_link_trace_detailed(path):
    """Parse a link-tracer CSV into per-category totals."""
    totals = {cat: {"pkts": 0, "bytes": 0} for cat in CATEGORIES}
    if not path or not os.path.isfile(path):
        return totals
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            for cat in CATEGORIES:
                totals[cat]["pkts"] += int(row.get(f"{cat}_Pkts", 0))
                totals[cat]["bytes"] += int(row.get(f"{cat}_Bytes", 0))
    return totals


def run_variant(ns3_dir, *, topo_rel, grid_size, trial, mode, num_prefixes,
                dv_config, sim_time, cores, out_dir):
    """Run one variant and return a result dict."""
    tag = f"{mode}-{grid_size}x{grid_size}-p{num_prefixes}-t{trial}"
    conv_file = os.path.abspath(os.path.join(out_dir, f"conv-{tag}.txt"))
    link_csv = os.path.abspath(os.path.join(out_dir, f"link-trace-{tag}.csv"))
    pkt_csv = os.path.abspath(os.path.join(out_dir, f"packet-trace-{tag}.csv"))
    log_file = os.path.abspath(os.path.join(out_dir, f"log-{tag}.txt"))

    # Set up dv_config for this variant
    dvc = dict(dv_config) if dv_config else {}
    if mode in ("one_step", "baseline"):
        # Baseline uses one_step=true with 0 prefixes so PrefixSync SVS
        # is disabled -- giving a pure-DV floor with no sync overhead.
        dvc["one_step"] = True
    else:
        dvc.pop("one_step", None)

    pfx_count = num_prefixes if mode != "baseline" else 0

    print(f"\n=== {mode}: grid {grid_size}x{grid_size}, "
          f"prefixes={pfx_count}, trial {trial} ===")
    run_routing_scenario(
        ns3_dir,
        topo=topo_rel,
        sim_time=sim_time,
        cores=cores,
        conv_trace=conv_file,
        link_trace=link_csv,
        packet_trace=pkt_csv,
        dv_config=dvc or None,
        num_prefixes=pfx_count,
        run_log=log_file,
    )

    conv = parse_conv_trace(conv_file)
    traffic = parse_link_trace_detailed(link_csv)
    num_nodes, num_links = grid_stats(grid_size)

    routing_pkts = sum(traffic[c]["pkts"] for c in ("DvAdvert", "PrefixSync", "Mgmt"))
    routing_bytes = sum(traffic[c]["bytes"] for c in ("DvAdvert", "PrefixSync", "Mgmt"))

    return {
        "grid_size": grid_size,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "trial": trial,
        "mode": mode,
        "num_prefixes": pfx_count,
        "convergence_s": conv,
        "dv_advert_pkts": traffic["DvAdvert"]["pkts"],
        "dv_advert_bytes": traffic["DvAdvert"]["bytes"],
        "pfxsync_pkts": traffic["PrefixSync"]["pkts"],
        "pfxsync_bytes": traffic["PrefixSync"]["bytes"],
        "mgmt_pkts": traffic["Mgmt"]["pkts"],
        "mgmt_bytes": traffic["Mgmt"]["bytes"],
        "total_routing_pkts": routing_pkts,
        "total_routing_bytes": routing_bytes,
    }


def main():
    parser = argparse.ArgumentParser(
        description="One-step vs two-step routing comparison")
    parser.add_argument("--config", required=True,
                        help="JSON scenario config file")
    parser.add_argument("--out", default="results/sim_onestep",
                        help="Output directory (default: results/sim_onestep)")
    parser.add_argument("--ns3-dir", default=None,
                        help="Path to ns-3 root (default: deps/ns-3)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    dv_config = dv_config_from(cfg)
    ns3_dir = resolve_ns3_dir(args.ns3_dir)
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
            # Generate topology
            topo_dir = os.path.join(
                ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
            os.makedirs(topo_dir, exist_ok=True)
            topo_path = os.path.join(
                topo_dir, f"topo-grid-{grid_size}x{grid_size}-atlas.txt")
            generate_ndnsim_topo(grid_size, bw=f"{bw_mbps}Mbps",
                                delay_ms=delay_ms, path=topo_path)
            topo_rel = os.path.relpath(topo_path, ns3_dir)

            for trial in range(1, trials + 1):
                for mode in ("baseline", "two_step", "one_step"):
                    row = run_variant(
                        ns3_dir,
                        topo_rel=topo_rel,
                        grid_size=grid_size,
                        trial=trial,
                        mode=mode,
                        num_prefixes=num_prefixes,
                        dv_config=dv_config,
                        sim_time=sim_time,
                        cores=cores,
                        out_dir=out_dir,
                    )
                    writer.writerow(row)
                    f.flush()
                    print(f"  conv={row['convergence_s']}s"
                          f"  dv={row['dv_advert_bytes']}B"
                          f"  pfx={row['pfxsync_bytes']}B"
                          f"  total={row['total_routing_bytes']}B")

    print(f"\nResults written to {out_csv}")


if __name__ == "__main__":
    main()
