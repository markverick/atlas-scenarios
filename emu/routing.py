#!/usr/bin/env python3
"""
Routing-only emulation — measure DV routing traffic burst (no app traffic).

Usage (inside container, needs sudo):
    python3 emu/routing.py
    python3 emu/routing.py --grids 2 3 4 --out results/emu_routing
"""

import argparse
import json
import os
import shutil
import sys
import time

from mininet.log import setLogLevel, info

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from minindn_ndnd import dv_util
from lib.config import add_grid_scenario_args, apply_config_overrides
from lib.result_adapter import TrialResult, parse_router_reachable_logs
from emu._helpers import (
    NETWORK,
    finish_grid_trial, run_grid_experiment, start_grid_trial,
)


def run_trial(grid_size, delay_ms=10, bw_mbps=10, cores=0, dv_config=None,
              observation_window_s=30):
    """Run one routing-only trial on a grid_size x grid_size grid."""
    state = start_grid_trial(grid_size, delay_ms, bw_mbps, cores, dv_config,
                             capture_prefix="ndnd_rcap")
    ndn = state["ndn"]
    num_nodes = state["num_nodes"]
    num_links = state["num_links"]
    dv_start = state["dv_start"]

    # No probe prefix — convergence is measured event-driven from DV
    # "Router is now reachable" log events (identical to sim approach).

    try:
        dv_util.converge(ndn.net.hosts, deadline=120,
                         network=NETWORK, start=dv_start)
    except Exception:
        pass

    window_end = dv_start + observation_window_s
    now = time.time()
    if now < window_end:
        time.sleep(window_end - now)

    dv_log_paths = [
        os.path.join(h.params['params']['homeDir'], 'log', 'dv.log')
        for h in ndn.net.hosts
    ]
    avg_mem_kb, traffic = finish_grid_trial(state)
    conv_time = parse_router_reachable_logs(dv_log_paths, num_nodes=num_nodes)

    return {
        "grid_size": grid_size,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "convergence_s": conv_time,
        "avg_mem_kb": avg_mem_kb,
        "traffic": traffic,
        "pcap_paths": list(state["cap_paths"].values()),
        "dv_start": dv_start,
    }


def main():
    parser = argparse.ArgumentParser(
        description="NDNd DV routing-only traffic measurement")
    add_grid_scenario_args(parser, default_out="results/emu_routing",
                           default_window=30.0)
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]

    delay_ms, bw_mbps, dv_config = apply_config_overrides(args)

    def execute_trial(grid_size, _trial):
        return run_trial(
            grid_size,
            delay_ms=delay_ms,
            bw_mbps=bw_mbps,
            cores=args.cores,
            dv_config=dv_config,
            observation_window_s=args.window,
        )

    def save_artifacts(raw, grid_size, trial):
        tag = f"routing-{grid_size}x{grid_size}-t{trial}"
        saved_pcaps = []
        for index, src in enumerate(raw["pcap_paths"]):
            dst = os.path.join(args.out, f"pcap-{tag}-n{index}.pcap")
            if os.path.isfile(src):
                shutil.copy2(src, dst)
                saved_pcaps.append(dst)
        manifest = {"pcap_paths": saved_pcaps, "dv_start": raw["dv_start"]}
        with open(os.path.join(args.out, f"pcap-manifest-{tag}.json"), "w") as handle:
            json.dump(manifest, handle)

    def build_result(raw, trial):
        t = raw["traffic"]
        return TrialResult(
            grid_size=raw["grid_size"],
            num_nodes=raw["num_nodes"],
            num_links=raw["num_links"],
            trial=trial,
            convergence_s=raw["convergence_s"],
            convergence_scope="router_reachability",
            transfer_ok=raw["convergence_s"] >= 0,
            avg_mem_kb=raw["avg_mem_kb"],
            total_packets=t.routing_packets,
            total_bytes=t.routing_bytes,
            control_packets=t.routing_packets,
            control_bytes=t.routing_bytes,
        )

    run_grid_experiment(
        args,
        run_trial=execute_trial,
        build_result=build_result,
        header=lambda grid_size, trial: f"\n=== Routing-only: Grid {grid_size}x{grid_size}, trial {trial} ===\n",
        summary=lambda result: (
            f"  convergence={result.convergence_s}s  "
            f"control_pkts={result.control_packets}  "
            f"control_bytes={result.control_bytes}  "
            f"mem={result.avg_mem_kb}KB\n"
        ),
        log=info,
        after_trial=save_artifacts,
    )


if __name__ == "__main__":
    setLogLevel("info")
    main()
