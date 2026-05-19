#!/usr/bin/env python3
"""ndndSIM DV scalability and routing-only traffic scenarios."""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import add_grid_scenario_args, apply_config_overrides
from lib.topology import (
    core_edge_stats,
    generate_ndnsim_core_edge_topo,
    generate_ndnsim_rocketfuel_1755_topo,
    generate_ndnsim_sprint_pop_topo,
    generate_ndnsim_topo,
    grid_stats,
    rocketfuel_1755_stats,
    sprint_pop_stats,
)
from lib.result_adapter import ResultWriter, TrialResult, parse_conv_trace, parse_link_trace, sim_trial_result
from sim._helpers import resolve_ns3_dir, run_routing_scenario, run_scenario


def _routing_topologies(args, *, ns3_dir, topo_dir, bw_mbps, delay_ms):
    if args.topology == "grid":
        topologies = []
        for grid_size in args.grids:
            num_nodes, num_links = grid_stats(grid_size)
            topo_path = os.path.join(topo_dir, f"topo-grid-{grid_size}x{grid_size}-atlas.txt")
            generate_ndnsim_topo(grid_size, bw=f"{bw_mbps}Mbps", delay_ms=delay_ms, path=topo_path)
            topologies.append({
                "label": f"{grid_size}x{grid_size}",
                "grid_size": grid_size,
                "num_nodes": num_nodes,
                "num_links": num_links,
                "topo_rel": os.path.relpath(topo_path, ns3_dir),
            })
        return topologies

    if args.topology == "core_edge":
        topo_path = os.path.join(topo_dir, "topo-core-edge-atlas.txt")
        generate_ndnsim_core_edge_topo(
            bw=f"{bw_mbps}Mbps",
            delay_ms=delay_ms,
            path=topo_path,
            queue_size=args.queue_size,
        )
        num_nodes, num_links = core_edge_stats()
    elif args.topology == "rocketfuel_1755":
        topo_path = os.path.join(topo_dir, "topo-rocketfuel-1755-atlas.txt")
        generate_ndnsim_rocketfuel_1755_topo(
            bw=f"{bw_mbps}Mbps",
            delay_ms=delay_ms,
            path=topo_path,
            queue_size=args.queue_size,
        )
        num_nodes, num_links = rocketfuel_1755_stats()
    elif args.topology == "sprint":
        topo_path = os.path.join(topo_dir, "topo-sprint-pop-atlas.txt")
        generate_ndnsim_sprint_pop_topo(
            bw=f"{bw_mbps}Mbps",
            delay_ms=delay_ms,
            path=topo_path,
            queue_size=args.queue_size,
        )
        num_nodes, num_links = sprint_pop_stats()
    else:
        raise ValueError(f"Unsupported routing topology: {args.topology}")

    return [{
        "label": args.topology,
        "grid_size": 0,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "topo_rel": os.path.relpath(topo_path, ns3_dir),
    }]


def main(argv=None, routing=False):
    parser = argparse.ArgumentParser(
        description="ndndSIM routing-only traffic measurement" if routing else "ndndSIM DV scalability grid"
    )
    add_grid_scenario_args(
        parser,
        default_out="results/sim_routing" if routing else "results/sim",
        default_window=30.0 if routing else 60.0,
    )
    parser.add_argument("--ns3-dir", default=None,
                        help="Path to ns-3 root (default: deps/ns-3 or NS3_DIR env)")
    if routing:
        parser.add_argument("--topology", choices=("grid", "core_edge", "rocketfuel_1755", "sprint"),
                            default="grid",
                            help="Topology preset for routing-only measurement")
        parser.add_argument("--queue-size", type=int, default=100,
                            help="Per-link queue size in packets for preset topologies")
        parser.add_argument("--total-prefixes", type=int, default=None,
                            help="Total prefixes to introduce from node0")
        parser.add_argument("--prefix-introduce-time", type=float, default=None,
                            help="Simulation time to introduce total-prefixes from node0")
        parser.add_argument("--allow-no-convergence", action="store_true",
                            help="Keep routing outputs even when convergence_s stays -1")
    if not routing:
        parser.add_argument(
            "--allow-no-convergence",
            action="store_true",
            help="Keep trial outputs even when prefix propagation never completes (convergence_s stays -1)",
        )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    delay_ms, bw_mbps, dv_config = apply_config_overrides(args)
    ns3_dir = resolve_ns3_dir(args.ns3_dir)
    topo_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(topo_dir, exist_ok=True)

    out_csv = os.path.join(args.out, "scalability.csv")
    with ResultWriter(out_csv) as writer:
        topologies = (
            _routing_topologies(args, ns3_dir=ns3_dir, topo_dir=topo_dir,
                                bw_mbps=bw_mbps, delay_ms=delay_ms)
            if routing else None
        )
        if not routing:
            topologies = []
            for grid_size in args.grids:
                num_nodes, num_links = grid_stats(grid_size)
                topo_path = os.path.join(topo_dir, f"topo-grid-{grid_size}x{grid_size}-atlas.txt")
                generate_ndnsim_topo(grid_size, bw=f"{bw_mbps}Mbps", delay_ms=delay_ms, path=topo_path)
                topologies.append({
                    "label": f"{grid_size}x{grid_size}",
                    "grid_size": grid_size,
                    "num_nodes": num_nodes,
                    "num_links": num_links,
                    "topo_rel": os.path.relpath(topo_path, ns3_dir),
                })

        for topology in topologies:
            for trial in range(1, args.trials + 1):
                if routing:
                    tag = f"routing-{topology['label']}-t{trial}"
                    conv_file = os.path.abspath(os.path.join(args.out, f"conv-{tag}.txt"))
                    link_csv = os.path.abspath(os.path.join(args.out, f"link-trace-{tag}.csv"))
                    pkt_csv = os.path.abspath(os.path.join(args.out, f"packet-trace-{tag}.csv"))
                    print(f"\n=== Routing-only: topology {topology['label']}, trial {trial} ===")
                    run_routing_scenario(
                        ns3_dir,
                        topo=topology["topo_rel"],
                        sim_time=args.window,
                        cores=args.cores,
                        conv_trace=conv_file,
                        link_trace=link_csv,
                        packet_trace=pkt_csv,
                        dv_config=dv_config or None,
                        total_prefixes=args.total_prefixes,
                        prefix_introduce_time=args.prefix_introduce_time,
                        allow_no_convergence=args.allow_no_convergence,
                    )
                    conv = parse_conv_trace(conv_file)
                    result = TrialResult(
                        grid_size=topology["grid_size"],
                        num_nodes=topology["num_nodes"],
                        num_links=topology["num_links"],
                        trial=trial,
                        convergence_s=conv,
                        convergence_scope="router_reachability",
                        router_reachability_s=conv,
                        transfer_ok=conv >= 0,
                        **parse_link_trace(link_csv),
                    )
                    print(f"  convergence={result.convergence_s}s"
                          f"  control_pkts={result.control_packets}"
                          f"  control_bytes={result.control_bytes}"
                          f"  total_pkts={result.total_packets}"
                          f"  total_bytes={result.total_bytes}")
                else:
                    tag = f"{topology['label']}-t{trial}"
                    rate_csv = os.path.abspath(os.path.join(args.out, f"rate-trace-{tag}.csv"))
                    conv_file = os.path.abspath(os.path.join(args.out, f"conv-{tag}.txt"))
                    link_csv = os.path.abspath(os.path.join(args.out, f"link-trace-{tag}.csv"))
                    print(f"\n=== Sim grid {topology['label']}, trial {trial} ===")
                    run_scenario(
                        ns3_dir,
                        topo=topology["topo_rel"],
                        rate_trace=rate_csv,
                        sim_time=args.window,
                        cores=args.cores,
                        conv_trace=conv_file,
                        link_trace=link_csv,
                        dv_config=dv_config or None,
                        require_convergence=not args.allow_no_convergence,
                    )
                    result = sim_trial_result(
                        topology["grid_size"],
                        topology["num_nodes"],
                        topology["num_links"],
                        rate_csv,
                        trial=trial,
                        conv_trace_path=conv_file,
                        link_trace_path=link_csv,
                    )
                    print(f"  convergence={result.convergence_s}s"
                          f"  total_pkts={result.total_packets}"
                          f"  total_bytes={result.total_bytes}"
                          f"  control_bytes={result.control_bytes}")

                writer.write(result)

    print(f"\nResults written to {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
