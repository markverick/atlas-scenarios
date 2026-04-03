#!/usr/bin/env python3
"""
Churn scenario -- two-phase measurement of routing traffic under dynamic events.

Phase 1 (convergence): DV boot -> converge -> announce prefixes -> stabilize.
Phase 2 (churn):       Link fail/recover + prefix withdraw/re-announce.

Supports any topology registered in lib/churn_common.KNOWN_TOPOLOGIES, as well
as arbitrary NxN grid topologies.  The topology type is selected by the JSON
config key "topology" (default: "grid").

For each topology (or grid size), runs three variants:
  1. baseline  -- no prefixes (pure DV overhead under churn)
  2. two_step  -- DV + PrefixSync under churn
  3. one_step  -- prefixes in DV adverts under churn

Usage:
    python3 sim/churn.py --config experiments/prefix_scale/scenarios/sprint_twostep_sim_0to50.json
"""

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import load_config, dv_config_from
from lib.topology import generate_ndnsim_topo, grid_stats, grid_links, grid_nodes
from lib.result_adapter import parse_conv_trace
from sim._helpers import resolve_ns3_dir, run_churn_scenario
from lib.churn_common import (
    FIELDNAMES, CATEGORIES, KNOWN_TOPOLOGIES,
    build_churn_events, build_random_churn_events,
    build_prefix_scaling_events,
    parse_packet_trace_by_phase,
    build_result_rows, make_tag, auto_plot,
    default_out_dir, grid_churn_targets,
)


def run_variant(ns3_dir, *, topo_rel, topology, topo_id_str,
                grid_size, num_nodes, num_links,
                trial, mode, num_prefixes, window_s,
                dv_config, sim_time, phase2_start,
                link_src, link_dst, churn_node,
                cores, out_dir, cfg=None,
                all_links=None, all_nodes=None):
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

    churn_after_conv = (cfg or {}).get("churn_after_convergence", False)
    churn_margin = (cfg or {}).get("convergence_margin_s", 10.0)
    churn_dur_cfg = (cfg or {}).get("churn_duration_s", 0.0)
    churn_duration = churn_dur_cfg if churn_dur_cfg > 0 else (sim_time / 2.0)

    # Build churn events -- relative offsets (from 0) when deferred,
    # absolute times when using fixed phase boundary.
    evt_start = 0.0 if churn_after_conv else phase2_start
    evt_end = churn_duration if churn_after_conv else sim_time

    churn_mode = (cfg or {}).get("churn_mode", "fixed")
    if churn_mode == "prefix_scaling":
        churn_events = build_prefix_scaling_events(
            pfx_count, evt_start,
            per_prefix_rate=cfg.get("per_prefix_rate", 0.1),
            churn_node=churn_node,
            window_end=evt_end,
            seed=cfg.get("churn_seed", 42),
            recovery_delay=cfg.get("churn_recovery_delay", 3.0),
            all_nodes=all_nodes)
    elif churn_mode == "random":
        churn_events = build_random_churn_events(
            pfx_count, evt_start,
            link_src=link_src, link_dst=link_dst, churn_node=churn_node,
            window_end=evt_end,
            seed=cfg.get("churn_seed", 42),
            num_cycles=cfg.get("churn_num_cycles", 3),
            interval=cfg.get("churn_interval", 5.0),
            recovery_delay=cfg.get("churn_recovery_delay", 3.0),
            all_links=all_links,
            all_nodes=all_nodes,
            prefix_churn_rate=cfg.get("churn_prefix_rate", 0.0))
    else:
        churn_events = build_churn_events(
            pfx_count, evt_start,
            link_src=link_src, link_dst=link_dst, churn_node=churn_node)

    churn_start_file = None
    if churn_after_conv:
        churn_start_file = os.path.abspath(
            os.path.join(out_dir, f"churn-start-{tag}.txt"))

    # When churn_after_convergence with churn_duration, the C++ scenario
    # stops dynamically.  Pass a large backstop so convergence has time.
    effective_sim_time = sim_time
    if churn_after_conv and churn_duration > 0:
        effective_sim_time = max(sim_time, 3600.0)

    print(f"\n=== {mode}: {topo_id_str} ({num_nodes} nodes), "
          f"prefixes={pfx_count}, trial {trial}"
          f"{' [churn-after-conv]' if churn_after_conv else ''} ===")
    run_churn_scenario(
        ns3_dir,
        topo=topo_rel,
        sim_time=effective_sim_time,
        cores=cores,
        conv_trace=conv_file,
        link_trace=link_csv,
        packet_trace=pkt_csv,
        event_log=evt_csv,
        churn_start_trace=churn_start_file,
        dv_config=dvc or None,
        num_prefixes=pfx_count,
        churn_events=churn_events,
        churn_after_convergence=churn_after_conv,
        churn_margin=churn_margin,
        churn_duration=churn_duration if churn_after_conv else 0.0,
        run_log=log_file,
    )

    conv = parse_conv_trace(conv_file)

    # Determine the actual phase boundary for traffic splitting
    if churn_after_conv and churn_start_file:
        actual_boundary = _read_churn_start(churn_start_file)
        if actual_boundary is not None and actual_boundary > 0:
            phase_boundary = actual_boundary
            print(f"  Churn started at t={actual_boundary:.2f}s "
                  f"(conv={conv:.2f}s + margin={churn_margin}s)")
        else:
            phase_boundary = phase2_start
            print(f"  WARNING: churn start not recorded, "
                  f"using fixed boundary {phase2_start}s")
    else:
        phase_boundary = phase2_start

    phases = parse_packet_trace_by_phase(pkt_csv, phase_boundary)

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
        phase2_start=phase_boundary,
        convergence_s=conv,
    )


def _read_churn_start(path):
    """Read the churn start time written by the C++ scenario."""
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def _run_grid(ns3_dir, cfg, dv_config, out_dir, writer, f):
    """Run churn experiments over one or more NxN grid topologies."""
    num_prefixes = cfg.get("num_prefixes", 10)
    churn_dur_cfg = cfg.get("churn_duration_s", 0.0)
    p2_cfg = cfg.get("phase2_start_s", 0.0)
    if p2_cfg > 0 and churn_dur_cfg > 0:
        sim_time = p2_cfg + churn_dur_cfg
        phase2_start = p2_cfg
    else:
        sim_time = cfg["window_s"]
        phase2_start = sim_time / 2.0
    delay_ms = cfg["delay_ms"]
    bw_mbps = cfg["bandwidth_mbps"]
    cores = cfg["cores"]
    trials = cfg["trials"]

    for grid_size in cfg["grids"]:
        link_src, link_dst, churn_node = grid_churn_targets(grid_size)
        all_links_list = grid_links(grid_size)
        all_nodes_list = grid_nodes(grid_size)

        topo_dir = os.path.join(
            ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
        os.makedirs(topo_dir, exist_ok=True)
        topo_path = os.path.join(
            topo_dir, f"topo-grid-{grid_size}x{grid_size}-atlas.txt")
        generate_ndnsim_topo(grid_size, bw=f"{bw_mbps}Mbps",
                             delay_ms=delay_ms, path=topo_path,
                             queue_size=cfg.get("queue_size", 100))
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
                    cfg=cfg,
                    all_links=all_links_list,
                    all_nodes=all_nodes_list,
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

    conf_nodes, conf_links = parse_minindn_conf(conf_path)
    all_links_list = [(s, d) for s, d, _ in conf_links]
    all_nodes_list = conf_nodes

    num_prefixes = cfg.get("num_prefixes", 5)
    churn_dur_cfg = cfg.get("churn_duration_s", 0.0)
    p2_cfg = cfg.get("phase2_start_s", 0.0)
    if p2_cfg > 0 and churn_dur_cfg > 0:
        sim_time = p2_cfg + churn_dur_cfg
        phase2_start = p2_cfg
    else:
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
        conf_path, bw=f"{bw_mbps}Mbps", delay_ms=delay_ms, path=topo_path,
        queue_size=cfg.get("queue_size", 100))
    topo_rel = os.path.relpath(topo_path, ns3_dir)

    prefix_counts = cfg.get("prefix_counts", [])
    if not prefix_counts:
        prefix_counts = [num_prefixes]
    sweeping = len(prefix_counts) > 1

    modes = cfg.get("modes", []) or ["baseline", "two_step", "one_step"]

    for trial in range(1, trials + 1):
        baseline_done = False
        for pfx_count in prefix_counts:
            for mode in modes:
                # When sweeping prefix counts, baseline (0 prefixes)
                # is identical for every count -- run it only once.
                if sweeping and mode == "baseline" and baseline_done:
                    continue
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
                    num_prefixes=pfx_count,
                    window_s=sim_time,
                    dv_config=dv_config,
                    sim_time=sim_time,
                    phase2_start=phase2_start,
                    link_src=link_src,
                    link_dst=link_dst,
                    churn_node=churn_node,
                    cores=cores,
                    out_dir=out_dir,
                    cfg=cfg,
                    all_links=all_links_list,
                    all_nodes=all_nodes_list,
                )
                _write_rows(writer, f, rows)
                if mode == "baseline":
                    baseline_done = True


def _write_rows(writer, f, rows):
    for row in rows:
        writer.writerow(row)
        f.flush()
        print(f"  [{row['phase']}] dv={row['dv_advert_bytes']}B"
              f"  pfx={row['pfxsync_bytes']}B"
              f"  total={row['total_routing_bytes']}B")


def main():
    parser = argparse.ArgumentParser(
        description="Churn scenario -- two-phase routing traffic measurement")
    parser.add_argument("--config", required=True,
                        help="JSON scenario config file")
    parser.add_argument("--out", default=None,
                        help="Output directory (auto-derived from config)")
    parser.add_argument("--ns3-dir", default=None,
                        help="Path to ns-3 root (default: deps/ns-3)")
    parser.add_argument("--mode", default=None,
                        help="Run only this mode (baseline/two_step/one_step)")
    parser.add_argument("--prefixes", type=int, default=None,
                        help="Run only this prefix count")
    parser.add_argument("--append", action="store_true",
                        help="Append to CSV instead of overwriting")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.mode is not None:
        cfg["modes"] = [args.mode]
    if args.prefixes is not None:
        cfg["prefix_counts"] = [args.prefixes]
    dv_config = dv_config_from(cfg)
    ns3_dir = resolve_ns3_dir(args.ns3_dir)

    topo_name = cfg.get("topology", "grid")

    if args.out is None:
        args.out = default_out_dir(cfg, "sim")
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    out_csv = os.path.join(out_dir, "churn.csv")
    csv_mode = "a" if args.append and os.path.exists(out_csv) else "w"
    with open(out_csv, csv_mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if csv_mode == "w":
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

    # Auto-generate plots and summary (auto-detects sibling emu dir)
    plot_kind = "prefix_scale" if cfg.get("churn_mode") == "prefix_scaling" else "churn"
    auto_plot(out_dir, sim_dir=out_dir, plot_kind=plot_kind)


if __name__ == "__main__":
    main()
