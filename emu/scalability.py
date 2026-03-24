#!/usr/bin/env python3
"""
Scalability test for NDNd DV routing on NxN grid topologies.

Measures DV convergence time, file-transfer success, and memory usage
across increasing grid sizes. Results are written to a CSV file that
can be plotted with plot.py.

Usage (inside container):
    python3 emu/scalability.py
    python3 emu/scalability.py --grids 2 3 4 5 --trials 3 --out results/emu
"""

import argparse
import os
import sys
import time

from mininet.log import setLogLevel, info
from minindn.helpers import dv_util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import add_grid_scenario_args, apply_config_overrides
from lib.pcap import collect_traffic
from lib.result_adapter import ResultWriter, TrialResult
from emu._helpers import (
    NDND_TRAFFIC, NETWORK,
    setup_grid, start_tcpdump, stop_tcpdump, collect_memory,
)


def run_trial(grid_size, delay_ms=10, bw_mbps=10, cores=0, dv_config=None,
              observation_window_s=0):
    """Run one trial on a grid_size x grid_size grid.

    Returns a dict with metrics and a TrafficCounters instance.
    """
    ndn, num_nodes, num_links = setup_grid(grid_size, delay_ms, bw_mbps, cores)
    cap_tag, cap_paths = start_tcpdump(ndn.net.hosts)

    dv_start = dv_util.setup(ndn, network=NETWORK, dv_config=dv_config)

    # Match sim behavior: producer and consumer both start at t=0.5s.
    src_name = "n0_0"
    dst_name = f"n{grid_size - 1}_{grid_size - 1}"
    app_prefix = "/ndn/test"
    consumer_log = "/tmp/emu-traffic-client.log"

    transfer_ok = False
    producer_started = consumer_started = False

    if observation_window_s > 0:
        start_at = dv_start + 0.5
        now = time.time()
        if now < start_at:
            time.sleep(start_at - now)

        ndn.net[dst_name].cmd(
            f'{NDND_TRAFFIC} traffic producer {app_prefix}'
            f' --payload 1024 --freshness 2000 --expose'
            f' > /tmp/emu-traffic-server.log 2>/dev/null &'
        )
        producer_started = True

        ndn.net[src_name].cmd(
            f'{NDND_TRAFFIC} traffic consumer {app_prefix}'
            f' --interval 100 --lifetime 4000'
            f' > {consumer_log} 2>/dev/null &'
        )
        consumer_started = True

    try:
        conv_time = dv_util.converge(ndn.net.hosts, deadline=120,
                                     network=NETWORK, start=dv_start)
    except Exception:
        conv_time = -1

    # Match sim stop times: consumer at simTime-2, producer at simTime.
    if observation_window_s > 0:
        window_end = dv_start + observation_window_s
        consumer_stop = window_end - 2.0

        now = time.time()
        if consumer_started and now < consumer_stop:
            time.sleep(consumer_stop - now)
        if consumer_started:
            ndn.net[src_name].cmd(
                "pkill -f 'ndnd-traffic traffic consumer' 2>/dev/null; true")

        now = time.time()
        if producer_started and now < window_end:
            time.sleep(window_end - now)
        if producer_started:
            ndn.net[dst_name].cmd(
                "pkill -f 'ndnd-traffic traffic producer' 2>/dev/null; true")

        if consumer_started:
            out = ndn.net[src_name].cmd(f"cat {consumer_log} 2>/dev/null")
            transfer_ok = "received" in out

    avg_mem_kb = collect_memory(ndn.net.hosts)
    stop_tcpdump(ndn.net.hosts, cap_tag)

    cap_start = dv_start if observation_window_s > 0 else None
    cap_end = (dv_start + observation_window_s) if observation_window_s > 0 else None
    traffic = collect_traffic(cap_paths.values(),
                              start_ts=cap_start, end_ts=cap_end)

    ndn.stop()

    return {
        "grid_size": grid_size,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "convergence_s": conv_time,
        "transfer_ok": transfer_ok,
        "avg_mem_kb": avg_mem_kb,
        "traffic": traffic,
    }


def main():
    parser = argparse.ArgumentParser(description="NDNd DV scalability test")
    add_grid_scenario_args(parser, default_out="results/emu")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]  # prevent MiniNDN from re-parsing our flags

    delay_ms, bw_mbps, dv_config = apply_config_overrides(args)

    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "scalability.csv")

    with ResultWriter(csv_path) as writer:
        for grid_size in args.grids:
            for trial in range(1, args.trials + 1):
                info(f"\n=== Grid {grid_size}x{grid_size}, trial {trial} ===\n")
                raw = run_trial(grid_size, delay_ms=delay_ms, bw_mbps=bw_mbps,
                               cores=args.cores, dv_config=dv_config,
                               observation_window_s=args.window)
                t = raw["traffic"]
                result = TrialResult(
                    grid_size=raw["grid_size"],
                    num_nodes=raw["num_nodes"],
                    num_links=raw["num_links"],
                    trial=trial,
                    convergence_s=raw["convergence_s"],
                    transfer_ok=raw["transfer_ok"],
                    avg_mem_kb=raw["avg_mem_kb"],
                    total_packets=t.total_packets,
                    total_bytes=t.total_bytes,
                    user_packets=t.user_packets,
                    user_bytes=t.user_bytes,
                    dv_packets=t.dv_packets,
                    dv_bytes=t.dv_bytes,
                )
                writer.write(result)
                info(f"  convergence={result.convergence_s}s  "
                     f"transfer={'OK' if result.transfer_ok else 'FAIL'}  "
                     f"mem={result.avg_mem_kb}KB  "
                     f"dv_pkts={result.dv_packets}  "
                     f"total_pkts={result.total_packets}\n")

    info(f"\nResults written to {csv_path}\n")


if __name__ == "__main__":
    setLogLevel("info")
    main()
