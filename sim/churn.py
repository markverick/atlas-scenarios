#!/usr/bin/env python3
"""
Churn scenario — two-phase measurement of routing traffic under dynamic events.

Phase 1 (convergence): DV boot → converge → announce prefixes → stabilize.
Phase 2 (churn):       Link fail/recover + prefix withdraw/re-announce.

Supports any topology registered in lib/churn_common.KNOWN_TOPOLOGIES, as well
as arbitrary NxN grid topologies.  The topology type is selected by the JSON
config key "topology" (default: "grid").

For each topology (or grid size), runs three variants:
  1. baseline  — no prefixes (pure DV overhead under churn)
  2. two_step  — DV + PrefixSync under churn
  3. one_step  — prefixes in DV adverts under churn

Usage:
  python3 sim/churn.py --config scenarios/churn.json
  python3 sim/churn.py --config scenarios/churn_4x4.json
  python3 sim/churn.py --config scenarios/churn_sprint.json
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import load_config, dv_config_from
from lib.topology import generate_ndnsim_topo, grid_stats
from lib.result_adapter import parse_conv_trace
from sim._helpers import resolve_ns3_dir, run_churn_scenario
from lib.churn_common import (
    FIELDNAMES, CATEGORIES, KNOWN_TOPOLOGIES,
    build_churn_events, parse_packet_trace_by_phase,
    build_result_rows, make_tag, auto_plot,
    default_out_dir, grid_churn_targets,
)


def run_variant(ns3_dir, *, topo_rel, topology, topo_id_str,
                grid_size, num_nodes, num_links,
                trial, mode, num_prefixes, window_s,
                dv_config, sim_time, phase2_start,
                link_src, link_dst, churn_node,
                cores, out_dir):
    """Run one variant and return a list of result dicts (one per phase)."""
    tag = make_tag(mode, topo_id_str, num_prefixes, trial)
    pfx_count = num_prefixes if mode != "baseline" else 0

    conv_file = os.path.abspath(os.path.join(out_dir, f"conv-{tag}.txt"))
    link_csv = os.path.abspath(os.path.join(out_dir, f"link-trace-{tag}.csv"))
    pkt_csv = os.path.abspath(os.path.join(out_dir, f"packet-trace-{tag}.csv"))
    evt_csv = os.path.abspath(os.path.join(out_dir, f"event-log-{tag}.csv"))
    log_file = os.path.abspath(os.path.join(out_dir, f"log-{tag}.txt"))

    dvc = dict(dv_config) if dv_config else {}
    if mode in ("one_step", "baseline"):
        dvc["one_step"] = True
    else:
        dvc.pop("one_step", None)

    churn_events = build_churn_events(
        pfx_count, phase2_start,
        link_src=link_src, link_dst=link_dst, churn_node=churn_node)

    print(f"\n=== {mode}: {topo_id_str} ({num_nodes} nodes), "
          f"prefixes={pfx_count}, trial {trial} ===")
    run_churn_scenario(
        ns3_dir,
        topo=topo_rel,
        sim_time=sim_time,
        cores=cores,
        conv_trace=conv_file,
        link_trace=link_csv,
        packet_trace=pkt_csv,
        event_log=evt_csv,
        dv_config=dvc or None,
        num_prefixes=pfx_count,
        churn_events=churn_events,
        run_log=log_file,
    )

    conv = parse_conv_trace(conv_file)
    phases = parse_packet_trace_by_phase(pkt_csv, phase2_start)

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
        convergence_s=conv,
    )


def _run_grid(ns3_dir, cfg, dv_config, out_dir, writer, f):
    """Run churn experiments over one or more NxN grid topologies."""
    num_prefixes = cfg.get("num_prefixes", 10)
    sim_time = cfg["window_s"]
    phase2_start = sim_time / 2.0
    delay_ms = cfg["delay_ms"]
    bw_mbps = cfg["bandwidth_mbps"]
    cores = cfg["cores"]
    trials = cfg["trials"]

    for grid_size in cfg["grids"]:
        link_src, link_dst, churn_node = grid_churn_targets(grid_size)

        topo_dir = os.path.join(
            ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
        os.makedirs(topo_dir, exist_ok=True)
        topo_path = os.path.join(
            topo_dir, f"topo-grid-{grid_size}x{grid_size}-atlas.txt")
        generate_ndnsim_topo(grid_size, bw=f"{bw_mbps}Mbps",
                             delay_ms=delay_ms, path=topo_path)
        topo_rel = os.path.relpath(topo_path, ns3_dir)
        num_nodes, num_links = grid_stats(grid_size)

        for trial in range(1, trials + 1):
            for mode in ("baseline", "two_step", "one_step"):
                rows = run_variant(
                    ns3_dir,
                    topo_rel=topo_rel,
                    topology="grid",
                    topo_id_str=f"{grid_size}x{grid_size}",
                    grid_size=grid_size,
                    num_nodes=num_nodes,
                    num_links=num_links,
                    trial=trial,
                    mode=mode,
                    num_prefixes=num_prefixes,
                    window_s=sim_time,
                    dv_config=dv_config,
                    sim_time=sim_time,
                    phase2_start=phase2_start,
                    link_src=link_src,
                    link_dst=link_dst,
                    churn_node=churn_node,
                    cores=cores,
                    out_dir=out_dir,
                )
                _write_rows(writer, f, rows)


def _run_conf(ns3_dir, cfg, dv_config, out_dir, writer, f, topo_name):
    """Run churn experiments on a conf-based topology (Sprint, etc.)."""
    from lib.topology import (
        parse_minindn_conf, conf_stats, generate_ndnsim_topo_from_conf,
    )

    info = KNOWN_TOPOLOGIES[topo_name]
    conf_path = os.path.abspath(info["conf_path"])
    link_src, link_dst = info["churn_link"]
    churn_node = info["churn_node"]

    num_prefixes = cfg.get("num_prefixes", 5)
    sim_time = cfg["window_s"]
    phase2_start = sim_time / 2.0
    delay_ms = cfg["delay_ms"]
    bw_mbps = cfg["bandwidth_mbps"]
    cores = cfg["cores"]
    trials = cfg["trials"]

    num_nodes, num_links = conf_stats(conf_path)
    print(f"{topo_name} topology: {num_nodes} nodes, {num_links} links")

    topo_dir = os.path.join(
        ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
    os.makedirs(topo_dir, exist_ok=True)
    topo_path = os.path.join(topo_dir, f"topo-{topo_name}-atlas.txt")
    generate_ndnsim_topo_from_conf(
        conf_path, bw=f"{bw_mbps}Mbps", delay_ms=delay_ms, path=topo_path)
    topo_rel = os.path.relpath(topo_path, ns3_dir)

    for trial in range(1, trials + 1):
        for mode in ("baseline", "two_step", "one_step"):
            rows = run_variant(
                ns3_dir,
                topo_rel=topo_rel,
                topology=topo_name,
                topo_id_str=topo_name,
                grid_size=0,
                num_nodes=num_nodes,
                num_links=num_links,
                trial=trial,
                mode=mode,
                num_prefixes=num_prefixes,
                window_s=sim_time,
                dv_config=dv_config,
                sim_time=sim_time,
                phase2_start=phase2_start,
                link_src=link_src,
                link_dst=link_dst,
                churn_node=churn_node,
                cores=cores,
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


def main():
    parser = argparse.ArgumentParser(
        description="Churn scenario — two-phase routing traffic measurement")
    parser.add_argument("--config", required=True,
                        help="JSON scenario config file")
    parser.add_argument("--out", default=None,
                        help="Output directory (auto-derived from config)")
    parser.add_argument("--ns3-dir", default=None,
                        help="Path to ns-3 root (default: deps/ns-3)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    dv_config = dv_config_from(cfg)
    ns3_dir = resolve_ns3_dir(args.ns3_dir)

    topo_name = cfg.get("topology", "grid")

    if args.out is None:
        args.out = default_out_dir(cfg, "sim")
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    out_csv = os.path.join(out_dir, "churn.csv")
    with open(out_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()

        if topo_name == "grid":
            _run_grid(ns3_dir, cfg, dv_config, out_dir, writer, f)
        elif topo_name in KNOWN_TOPOLOGIES:
            _run_conf(ns3_dir, cfg, dv_config, out_dir, writer, f, topo_name)
        else:
            print(f"Unknown topology '{topo_name}'. "
                  f"Known: grid, {', '.join(KNOWN_TOPOLOGIES)}")
            sys.exit(1)

    print(f"\nResults written to {out_csv}")

    # Auto-generate plots and summary
    emu_dir = ""
    if topo_name != "grid":
        emu_dir = ""  # no cross-runner pairing
    auto_plot(out_dir, sim_dir=out_dir, emu_dir=emu_dir)


if __name__ == "__main__":
    main()
