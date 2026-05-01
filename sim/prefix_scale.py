#!/usr/bin/env python3
"""ndndSIM core/edge prefix-scale table study."""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.result_adapter import parse_conv_trace, parse_link_trace
from lib.table_metrics import (
    NODE_FIELDNAMES,
    ROLE_FIELDNAMES,
    parse_table_trace,
    summarize_role_table_metrics,
)
from lib.topology import (core_edge_roles, core_edge_stats,
                          generate_ndnsim_core_edge_topo,
                          generate_ndnsim_rocketfuel_2914_topo,
                          generate_ndnsim_rocketfuel_sample_4755_topo,
                          rocketfuel_2914_roles,
                          rocketfuel_2914_stats,
                          rocketfuel_sample_4755_path,
                          rocketfuel_sample_4755_roles,
                          rocketfuel_sample_4755_stats)
from sim._helpers import resolve_ns3_dir, run_prefix_scale_scenario


RUN_FIELDNAMES = [
    "phase",
    "trial",
    "prefix_count",
    "num_nodes",
    "num_links",
    "router_reachability_s",
    "control_packets",
    "control_bytes",
    "total_packets",
    "total_bytes",
]

DEFAULT_PREFIX_COUNTS = {
    "core_edge": [0, 1, 2, 3, 4, 5],
    "rocketfuel_2914": [0, 100, 200, 300, 400, 500],
    "rocketfuel_4755": [0, 100, 200, 300, 400, 500],
}


def current_phase_label():
    phase = os.environ.get("NDND_PHASE")
    if phase in {"onephase", "twophase"}:
        return phase

    build_out = os.environ.get("NS3_BUILD_OUT", "build")
    return "onephase" if build_out.endswith("-op") else "twophase"


def cli_dv_config(args):
    dv_config = {}
    if args.adv_interval:
        dv_config["advertise_interval"] = args.adv_interval
    if args.dead_interval:
        dv_config["router_dead_interval"] = args.dead_interval
    return dv_config or None


def parse_dv_config_json(text, *, field_name):
    if not text:
        return None

    try:
        dv_config = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc}") from exc

    if not isinstance(dv_config, dict):
        raise ValueError(f"{field_name} must decode to a JSON object")

    return dv_config or None


def merge_dv_configs(shared_config, role_config):
    if not shared_config and not role_config:
        return None

    merged = {}
    if shared_config:
        merged.update(shared_config)
    if role_config:
        merged.update(role_config)
    return merged or None


def cli_role_dv_overrides(args):
    core_dv_config = parse_dv_config_json(
        args.core_dv_config_json,
        field_name="--core-dv-config-json",
    )
    edge_dv_config = parse_dv_config_json(
        args.edge_dv_config_json,
        field_name="--edge-dv-config-json",
    )

    if args.core_disable_prefix_egress_replication:
        core_dv_config = {
            **(core_dv_config or {}),
            "prefix_egre_state_replicate": False,
        }
    if args.edge_disable_prefix_egress_replication:
        edge_dv_config = {
            **(edge_dv_config or {}),
            "prefix_egre_state_replicate": False,
        }

    return core_dv_config or None, edge_dv_config or None


def effective_role_dv_configs(shared_dv_config, core_override, edge_override):
    if not core_override and not edge_override:
        return shared_dv_config, None, None

    return (
        None,
        merge_dv_configs(shared_dv_config, core_override),
        merge_dv_configs(shared_dv_config, edge_override),
    )


def default_prefix_counts(topology):
    return list(DEFAULT_PREFIX_COUNTS[topology])


def prepare_prefix_scale_topology(topology, *, ns3_dir, topo_dir, bw_mbps, delay_ms):
    if topology == "core_edge":
        topo_path = os.path.join(topo_dir, "topo-core-edge-atlas.txt")
        generate_ndnsim_core_edge_topo(
            bw=f"{bw_mbps}Mbps",
            delay_ms=delay_ms,
            path=topo_path,
        )
        roles = core_edge_roles()
        num_nodes, num_links = core_edge_stats()
    elif topology == "rocketfuel_4755":
        maps_path = rocketfuel_sample_4755_path(ns3_dir)
        topo_path = os.path.join(topo_dir, "topo-rocketfuel-4755-atlas.txt")
        generate_ndnsim_rocketfuel_sample_4755_topo(
            maps_path=maps_path,
            bw=f"{bw_mbps}Mbps",
            delay_ms=delay_ms,
            path=topo_path,
        )
        roles = rocketfuel_sample_4755_roles(maps_path)
        num_nodes, num_links = rocketfuel_sample_4755_stats(maps_path)
    elif topology == "rocketfuel_2914":
        topo_path = os.path.join(topo_dir, "topo-rocketfuel-2914-atlas.txt")
        generate_ndnsim_rocketfuel_2914_topo(
            bw=f"{bw_mbps}Mbps",
            delay_ms=delay_ms,
            path=topo_path,
        )
        roles = rocketfuel_2914_roles()
        num_nodes, num_links = rocketfuel_2914_stats()
    else:
        raise ValueError(f"Unsupported topology: {topology}")

    if not roles["edge"]:
        raise ValueError(f"Topology {topology} has no edge nodes for prefix announcements")

    return {
        "topo_rel": os.path.relpath(topo_path, ns3_dir),
        "roles": roles,
        "num_nodes": num_nodes,
        "num_links": num_links,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="ndndSIM prefix-scale table measurement"
    )
    parser.add_argument("--ns3-dir", default=None,
                        help="Path to ns-3 root (default: deps/ns-3 or NS3_DIR env)")
    parser.add_argument("--topology", choices=sorted(DEFAULT_PREFIX_COUNTS),
                        default="core_edge",
                        help="Topology preset to run (default: core_edge)")
    parser.add_argument("--prefix-counts", nargs="+", type=int,
                        default=None,
                        help="Total prefixes to sweep across edge routers")
    parser.add_argument("--delay", type=int, default=10,
                        help="Per-link delay in ms (default: 10)")
    parser.add_argument("--bw", type=int, default=10,
                        help="Per-link bandwidth in Mbps (default: 10)")
    parser.add_argument("--window", type=float, default=40.0,
                        help="Maximum simulation duration in seconds (default: 40). "
                             "Stage-2 runs (--snap-import with prefixes) stop early "
                             "once prefix propagation converges.")
    parser.add_argument("--out", default="results/sim_prefix_scale",
                        help="Output directory (default: results/sim_prefix_scale)")
    parser.add_argument("--cores", type=int, default=0,
                        help="Parallel build / CPU cores (0 = all)")
    parser.add_argument("--trials", type=int, default=1,
                        help="Repetitions per prefix count (default: 1)")
    parser.add_argument("--adv-interval", type=int, default=0,
                        help="DV advertisement interval in ms (0 = default)")
    parser.add_argument("--dead-interval", type=int, default=0,
                        help="DV router dead interval in ms (0 = default)")
    parser.add_argument("--core-dv-config-json", default="",
                        help="JSON DV config overlay applied only to core nodes")
    parser.add_argument("--edge-dv-config-json", default="",
                        help="JSON DV config overlay applied only to edge nodes")
    parser.add_argument(
        "--core-disable-prefix-egress-replication",
        action="store_true",
        help=(
            "Set prefix_egre_state_replicate=false on core nodes so remote "
            "prefix-egress state is not replicated into PET"
        ),
    )
    parser.add_argument(
        "--edge-disable-prefix-egress-replication",
        action="store_true",
        help=(
            "Set prefix_egre_state_replicate=false on edge nodes so remote "
            "prefix-egress state is not replicated into PET"
        ),
    )
    parser.add_argument(
        "--snap-export",
        default=None,
        metavar="PATH",
        help=(
            "Export DV routing state snapshot to PATH after routing converges. "
            "Useful for Stage 1 of a 3-stage pipeline (use with --prefix-counts 0)."
        ),
    )
    parser.add_argument(
        "--snap-import",
        default=None,
        metavar="PATH",
        help=(
            "Import DV routing state snapshot from PATH before the simulation "
            "starts, skipping DV convergence wait. "
            "Useful for Stage 2/3 of a 3-stage pipeline."
        ),
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    phase = current_phase_label()
    shared_dv_config = cli_dv_config(args)
    try:
        core_dv_override, edge_dv_override = cli_role_dv_overrides(args)
    except ValueError as exc:
        parser.error(str(exc))

    dv_config, core_dv_config, edge_dv_config = effective_role_dv_configs(
        shared_dv_config,
        core_dv_override,
        edge_dv_override,
    )
    ns3_dir = resolve_ns3_dir(args.ns3_dir)
    topo_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "examples", "topologies")
    os.makedirs(args.out, exist_ok=True)
    os.makedirs(topo_dir, exist_ok=True)

    if args.prefix_counts is None:
        args.prefix_counts = default_prefix_counts(args.topology)

    topology = prepare_prefix_scale_topology(
        args.topology,
        ns3_dir=ns3_dir,
        topo_dir=topo_dir,
        bw_mbps=args.bw,
        delay_ms=args.delay,
    )
    topo_rel = topology["topo_rel"]
    roles = topology["roles"]
    num_nodes = topology["num_nodes"]
    num_links = topology["num_links"]

    metadata_path = os.path.join(args.out, "metadata.json")
    with open(metadata_path, "w") as handle:
        json.dump({
            "topology": args.topology,
            "num_nodes": num_nodes,
            "num_links": num_links,
            "role_counts": {role: len(nodes) for role, nodes in roles.items()},
            "roles": roles,
            "prefix_counts": args.prefix_counts,
            "shared_dv_config": shared_dv_config,
            "effective_dv_config_by_role": {
                "core": core_dv_config or dv_config,
                "edge": edge_dv_config or dv_config,
            },
        }, handle, indent=2, sort_keys=True)

    runs_path = os.path.join(args.out, "runs.csv")
    node_path = os.path.join(args.out, "node_table_metrics.csv")
    role_path = os.path.join(args.out, "role_table_summary.csv")

    with open(runs_path, "w", newline="") as runs_handle, \
            open(node_path, "w", newline="") as node_handle, \
            open(role_path, "w", newline="") as role_handle:
        runs_writer = csv.DictWriter(runs_handle, fieldnames=RUN_FIELDNAMES)
        node_writer = csv.DictWriter(node_handle, fieldnames=NODE_FIELDNAMES)
        role_writer = csv.DictWriter(role_handle, fieldnames=ROLE_FIELDNAMES)
        runs_writer.writeheader()
        node_writer.writeheader()
        role_writer.writeheader()

        for prefix_count in args.prefix_counts:
            for trial in range(1, args.trials + 1):
                tag = f"{phase}-p{prefix_count}-t{trial}"
                conv_file = os.path.abspath(os.path.join(args.out, f"conv-{tag}.txt"))
                link_csv = os.path.abspath(os.path.join(args.out, f"link-trace-{tag}.csv"))
                table_csv = os.path.abspath(os.path.join(args.out, f"tables-{tag}.csv"))
                run_log = os.path.abspath(os.path.join(args.out, f"run-{tag}.log"))

                print(
                    f"\n=== Prefix scale: topology {args.topology}, phase {phase}, "
                    f"prefixes {prefix_count}, trial {trial} ==="
                )
                # For twophase stage-2 runs (snap-import + prefixes), use
                # event-driven convergence: stop once NdndSimGetPrefixRemoteAddCount
                # has been stable for 2 × adv_interval seconds.  In twophase, DV
                # prefix events fire simultaneously with table updates, so the
                # counter is a reliable convergence signal.
                #
                # For onephase, the FIB is installed asynchronously after the DV
                # event, so the counter stabilises before the FIB is fully
                # populated.  Pass stableWindow=0 to disable the checker and rely
                # on the hard --simTime ceiling instead.
                stable_window: float | None = None
                if args.snap_import and prefix_count > 0:
                    if phase == "twophase":
                        adv_interval_ms = args.adv_interval if args.adv_interval > 0 else 1000
                        stable_window = round(2 * adv_interval_ms / 1000.0, 3)
                    else:
                        stable_window = 0.0  # disable checker for onephase
                run_prefix_scale_scenario(
                    ns3_dir,
                    topo=topo_rel,
                    edge_nodes=roles["edge"],
                    sim_time=args.window,
                    cores=args.cores,
                    conv_trace=conv_file,
                    link_trace=link_csv,
                    table_trace=table_csv,
                    dv_config=dv_config,
                    core_dv_config=core_dv_config,
                    edge_dv_config=edge_dv_config,
                    num_prefixes=prefix_count,
                    export_snap=args.snap_export,
                    import_snap=args.snap_import,
                    stable_window=stable_window,
                    run_log=run_log,
                )

                conv = parse_conv_trace(conv_file)
                link_stats = parse_link_trace(link_csv)
                table_rows = parse_table_trace(table_csv)
                role_rows = summarize_role_table_metrics(table_rows)

                runs_writer.writerow({
                    "phase": phase,
                    "trial": trial,
                    "prefix_count": prefix_count,
                    "num_nodes": num_nodes,
                    "num_links": num_links,
                    "router_reachability_s": conv,
                    "control_packets": link_stats["control_packets"],
                    "control_bytes": link_stats["control_bytes"],
                    "total_packets": link_stats["total_packets"],
                    "total_bytes": link_stats["total_bytes"],
                })

                for row in table_rows:
                    node_writer.writerow({
                        "phase": phase,
                        "trial": trial,
                        "prefix_count": prefix_count,
                        **row,
                    })

                for row in role_rows:
                    role_writer.writerow({
                        "phase": phase,
                        "trial": trial,
                        "prefix_count": prefix_count,
                        **row,
                    })

                print(f"  routing_convergence={conv}s"
                      f"  control_pkts={link_stats['control_packets']}"
                      f"  control_bytes={link_stats['control_bytes']}")

    print(f"\nResults written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())