#!/usr/bin/env python3
"""Emulation prefix-scale study on the 10-node core/edge topology.

Measures DV routing convergence and control-plane traffic as a function of
the number of prefixes announced from edge nodes, for both twophase and
onephase ndnd.  Uses the pristine (unpatched) ndnd binary for each phase:
  - twophase  → /usr/local/bin/ndnd          (named-data/ndnd@dv2  a841cc2)
  - onephase  → /usr/local/bin/ndnd-onephase (named-data/ndnd@main 51774b8)

Usage (needs sudo):
    sudo ./run.sh emu prefix_scale --prefix-counts 0 1 2 3 4 5
    sudo ./run.sh --env onephase emu prefix_scale --prefix-counts 0 1 2 3 4 5
    sudo ./run.sh emu prefix_scale --prefix-counts 0 10 20 30 40 50 --out results/emu_prefix_scale
"""

import argparse
import csv
import json
import os
import sys
import time

from mininet.log import setLogLevel, info

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.pcap import collect_traffic
from lib.result_adapter import parse_router_reachable_logs, parse_dv_update_span_logs
from lib.table_metrics import (
    NODE_FIELDNAMES,
    ROLE_FIELDNAMES,
    collect_emu_table_metrics,
    summarize_role_table_metrics,
)
from minindn_ndnd import dv_util
from emu._helpers import (
    NETWORK,
    setup_core_edge,
    start_tcpdump, stop_tcpdump,
)
from lib.topology import core_edge_roles, core_edge_stats


RUN_FIELDNAMES = [
    "phase",
    "trial",
    "prefix_count",
    "num_nodes",
    "num_links",
    "router_reachability_s",
    "prefix_propagation_s",
    "prefix_fetch_success",
    "prefix_fetch_total",
    "control_packets",
    "control_bytes",
    "total_packets",
    "total_bytes",
]

DEFAULT_PREFIX_COUNTS = [0, 1, 2, 3, 4, 5]
OBSERVATION_WINDOW_S = 40.0


def current_phase_label():
    phase = os.environ.get("NDND_PHASE")
    if phase in {"onephase", "twophase"}:
        return phase
    return "twophase"


def ndnd_bin_for_phase(phase):
    """Return the ndnd binary name for the given phase."""
    return "ndnd-onephase" if phase == "onephase" else "ndnd"


def verify_prefix_reachability(net, edge_node_names, announced, ndnd_bin, timeout_s=5):
    """Fetch each announced prefix from a *different* edge node via ndnd cat.

    Samples one prefix per unique originating edge node and sends an Interest
    from a different edge node.  A successful fetch (exit 0) proves the
    Interest traversed core nodes and Data was returned end-to-end.

    Returns (success_count, total_count).
    """
    if not announced:
        return 0, 0

    # One prefix per unique originating host.
    seen: dict = {}
    for host, pfx in announced:
        if host.name not in seen:
            seen[host.name] = pfx

    success = 0
    total = 0
    for orig_name, pfx in seen.items():
        other_edges = [n for n in edge_node_names if n != orig_name]
        if not other_edges:
            continue
        fetcher = net[other_edges[0]]
        ret = fetcher.cmd(
            f'timeout {timeout_s} {ndnd_bin} cat "{pfx}" > /dev/null 2>&1; echo $?'
        ).strip()
        success += int(ret == "0")
        total += 1

    return success, total


def announce_prefixes(net, edge_node_names, prefix_count, ndnd_bin):
    """Run ``ndnd put --expose`` for each prefix on each edge node.

    Distributes prefix_count prefixes round-robin across the edge nodes.
    Returns list of (host, prefix) tuples for later cleanup.
    """
    announced = []
    for i in range(prefix_count):
        node_name = edge_node_names[i % len(edge_node_names)]
        host = net[node_name]
        pfx = f"/data/{node_name}/pfx{i}"
        host.cmd(f'{ndnd_bin} put --expose "{pfx}" < /dev/null > /dev/null 2>&1 &')
        announced.append((host, pfx))
    if announced:
        time.sleep(0.5)
    return announced


def withdraw_prefixes(announced):
    """Kill all ``ndnd put --expose`` background processes."""
    seen_hosts = set()
    for host, _pfx in announced:
        if host.name not in seen_hosts:
            host.cmd("pkill -f 'ndnd.*put --expose' 2>/dev/null; true")
            seen_hosts.add(host.name)
    time.sleep(0.3)


def warn_table_metrics(message):
    info(f"{message}\n")


def run_trial(phase, prefix_count, *, delay_ms=10, bw_mbps=10, cores=0,
              dv_config=None, window_s=OBSERVATION_WINDOW_S):
    """Run one prefix-scale trial and return raw measurements."""
    ndnd_bin = ndnd_bin_for_phase(phase)
    num_nodes, num_links = core_edge_stats()

    ndn, roles = setup_core_edge(delay_ms, bw_mbps, ndnd_bin=ndnd_bin, cores=cores)
    edge_node_names = roles["edge"]
    core_node_names = roles["core"]

    cap_tag, cap_paths = start_tcpdump(ndn.net.hosts, prefix="ndnd_pscap")
    cap_start = time.time()

    # In twophase, core nodes must not replicate prefix egress state into their
    # local PET -- they are transit routers, not egress points.  The emulation
    # demonstrates that this flag does not prevent prefix propagation to edge
    # nodes via the DV routing mechanism.
    node_dv_configs = None
    if ndnd_bin == 'ndnd':
        core_cfg = {**(dv_config or {}), 'prefix_egre_state_replicate': False}
        node_dv_configs = {name: core_cfg for name in core_node_names}

    dv_start = dv_util.setup(ndn, network=NETWORK, dv_config=dv_config,
                             ndnd_bin=ndnd_bin, node_dv_configs=node_dv_configs)

    # Collect DV log paths for convergence analysis.
    dv_log_paths = [
        os.path.join(h.params['params']['homeDir'], 'log', 'dv.log')
        for h in ndn.net.hosts
    ]

    # Wait for router-level routing convergence.
    router_reachability_s = -1
    try:
        dv_util.converge(ndn.net.hosts, deadline=120,
                         network=NETWORK, start=dv_start, ndnd_bin=ndnd_bin)
        router_reachability_s = parse_router_reachable_logs(
            dv_log_paths, num_nodes=num_nodes)
    except Exception as exc:
        info(f"WARNING: routing did not converge within deadline: {exc}\n")

    # Announce prefixes from edge nodes after routing converges.
    announced = announce_prefixes(ndn.net, edge_node_names, prefix_count,
                                  ndnd_bin=ndnd_bin)

    # Wait for the observation window to elapse from DV start.
    window_end = dv_start + window_s
    remaining = window_end - time.time()
    if remaining > 0:
        time.sleep(remaining)

    # Measure prefix propagation from DV logs.
    prefix_propagation_s = -1
    if prefix_count > 0:
        # Collect representative prefixes (one per edge node, first prefix).
        sample_prefixes = [
            f"/data/{edge_node_names[i % len(edge_node_names)]}/pfx{i}"
            for i in range(min(prefix_count, len(edge_node_names)))
        ]
        spans = [
            parse_dv_update_span_logs(dv_log_paths, prefix=pfx)
            for pfx in sample_prefixes
        ]
        valid = [s for s in spans if s >= 0]
        if valid:
            prefix_propagation_s = round(max(valid), 4)

    role_by_node = {
        **{name: "core" for name in core_node_names},
        **{name: "edge" for name in edge_node_names},
    }
    table_rows = collect_emu_table_metrics(
        ndn.net.hosts,
        role_by_node,
        phase,
        ndnd_bin=ndnd_bin,
        warn=warn_table_metrics,
    )

    # Verify data-plane reachability: fetch each prefix from a remote edge node.
    prefix_fetch_success, prefix_fetch_total = verify_prefix_reachability(
        ndn.net, edge_node_names, announced, ndnd_bin=ndnd_bin
    )

    withdraw_prefixes(announced)
    stop_tcpdump(ndn.net.hosts, cap_tag, prefix="ndnd_pscap")
    traffic = collect_traffic(cap_paths.values(), start_ts=cap_start)

    ndn.stop()

    return {
        "num_nodes": num_nodes,
        "num_links": num_links,
        "router_reachability_s": router_reachability_s,
        "prefix_propagation_s": prefix_propagation_s,
        "prefix_fetch_success": prefix_fetch_success,
        "prefix_fetch_total": prefix_fetch_total,
        "control_packets": traffic.routing_packets,
        "control_bytes": traffic.routing_bytes,
        "total_packets": traffic.total_packets,
        "total_bytes": traffic.total_bytes,
        "table_rows": table_rows,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Emulation prefix-scale table measurement on core/edge topology"
    )
    parser.add_argument("--prefix-counts", nargs="+", type=int,
                        default=DEFAULT_PREFIX_COUNTS,
                        help="Prefix counts to sweep (default: 0 1 2 3 4 5)")
    parser.add_argument("--trials", type=int, default=1,
                        help="Repetitions per prefix count (default: 1)")
    parser.add_argument("--delay", type=int, default=10,
                        help="Per-link delay in ms (default: 10)")
    parser.add_argument("--bw", type=int, default=10,
                        help="Per-link bandwidth in Mbps (default: 10)")
    parser.add_argument("--window", type=float, default=OBSERVATION_WINDOW_S,
                        help=f"Observation window in seconds (default: {OBSERVATION_WINDOW_S})")
    parser.add_argument("--cores", type=int, default=0,
                        help="CPU cores per Mininet node (0 = no limit)")
    parser.add_argument("--adv-interval", type=int, default=0,
                        help="DV advertisement interval in ms (0 = default)")
    parser.add_argument("--dead-interval", type=int, default=0,
                        help="DV router dead interval in ms (0 = default)")
    parser.add_argument("--out", default="results/emu_prefix_scale",
                        help="Output directory (default: results/emu_prefix_scale)")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]  # prevent MiniNDN from re-parsing our flags

    phase = current_phase_label()
    info(f"Prefix-scale emulation: phase={phase}, "
         f"prefix_counts={args.prefix_counts}, trials={args.trials}\n")

    dv_config = {}
    if args.adv_interval:
        dv_config["advertise_interval"] = args.adv_interval
    if args.dead_interval:
        dv_config["router_dead_interval"] = args.dead_interval
    dv_config = dv_config or None

    os.makedirs(args.out, exist_ok=True)

    num_nodes, num_links = core_edge_stats()
    roles = core_edge_roles()
    metadata = {
        "topology": "core_edge",
        "phase": phase,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "role_counts": {role: len(nodes) for role, nodes in roles.items()},
        "roles": roles,
        "prefix_counts": args.prefix_counts,
        "dv_config": dv_config,
    }
    with open(os.path.join(args.out, "metadata.json"), "w") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)

    node_metrics_path = os.path.join(args.out, "node_table_metrics.csv")
    role_summary_path = os.path.join(args.out, "role_table_summary.csv")
    runs_path = os.path.join(args.out, "runs.csv")
    with open(runs_path, "w", newline="") as runs_handle, \
            open(node_metrics_path, "w", newline="") as node_handle, \
            open(role_summary_path, "w", newline="") as role_handle:
        writer = csv.DictWriter(runs_handle, fieldnames=RUN_FIELDNAMES)
        node_writer = csv.DictWriter(node_handle, fieldnames=NODE_FIELDNAMES)
        role_writer = csv.DictWriter(role_handle, fieldnames=ROLE_FIELDNAMES)
        writer.writeheader()
        node_writer.writeheader()
        role_writer.writeheader()

        for prefix_count in args.prefix_counts:
            for trial in range(1, args.trials + 1):
                info(f"\n=== Prefix scale (emu): topology core_edge, phase {phase}, "
                     f"prefixes {prefix_count}, trial {trial} ===\n")
                raw = run_trial(
                    phase, prefix_count,
                    delay_ms=args.delay,
                    bw_mbps=args.bw,
                    cores=args.cores,
                    dv_config=dv_config,
                    window_s=args.window,
                )
                row = {
                    "phase": phase,
                    "trial": trial,
                    "prefix_count": prefix_count,
                    "num_nodes": raw["num_nodes"],
                    "num_links": raw["num_links"],
                    "router_reachability_s": raw["router_reachability_s"],
                    "prefix_propagation_s": raw["prefix_propagation_s"],
                    "prefix_fetch_success": raw["prefix_fetch_success"],
                    "prefix_fetch_total": raw["prefix_fetch_total"],
                    "control_packets": raw["control_packets"],
                    "control_bytes": raw["control_bytes"],
                    "total_packets": raw["total_packets"],
                    "total_bytes": raw["total_bytes"],
                }
                role_rows = summarize_role_table_metrics(raw["table_rows"])
                writer.writerow(row)
                runs_handle.flush()
                for node_row in raw["table_rows"]:
                    node_writer.writerow({
                        "phase": phase,
                        "trial": trial,
                        "prefix_count": prefix_count,
                        **node_row,
                    })
                for role_row in role_rows:
                    role_writer.writerow({
                        "phase": phase,
                        "trial": trial,
                        "prefix_count": prefix_count,
                        **role_row,
                    })
                info(f"  router_reachability={raw['router_reachability_s']}s"
                     f"  prefix_propagation={raw['prefix_propagation_s']}s"
                     f"  prefix_fetch={raw['prefix_fetch_success']}/{raw['prefix_fetch_total']}"
                     f"  table_rows={len(raw['table_rows'])}"
                     f"  control_pkts={raw['control_packets']}"
                     f"  control_bytes={raw['control_bytes']}\n")

    info(f"\nResults written to {runs_path}\n")
    return 0


if __name__ == "__main__":
    setLogLevel("info")
    raise SystemExit(main())
