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

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd_fw import NDNd_FW
from minindn.helpers import dv_util

# Allow imports from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.topology import build_grid_topo, grid_stats
from lib.result_adapter import ResultWriter, emu_trial_result

NETWORK = "/minindn"
TEST_FILE = "/tmp/test.bin"


def run_trial(grid_size, delay="10ms", bw=10, cores=0):
    """Run one trial on a grid_size x grid_size grid.

    Returns a dict with metrics.
    """
    Minindn.cleanUp()

    topo, nodes = build_grid_topo(grid_size, delay=delay, bw=bw)
    num_nodes, num_links = grid_stats(grid_size)

    ndn = Minindn(topo=topo, controller=None)
    ndn.start()

    if cores > 0:
        for host in ndn.net.hosts:
            host.setCPUs(cores=cores)

    AppManager(ndn, ndn.net.hosts, NDNd_FW)
    dv_start = dv_util.setup(ndn, network=NETWORK)

    try:
        conv_time = dv_util.converge(ndn.net.hosts, deadline=120, network=NETWORK, start=dv_start)
    except Exception:
        conv_time = -1

    # File transfer test: corner-to-corner
    transfer_ok = False
    if conv_time > 0:
        src_name = "n0_0"
        dst_name = f"n{grid_size - 1}_{grid_size - 1}"
        data_name = f"{NETWORK}/{dst_name}/test"

        os.system(f"dd if=/dev/urandom of={TEST_FILE} bs=1K count=64 2>/dev/null")
        ndn.net[dst_name].cmd(f'ndnd put --expose "{data_name}" < {TEST_FILE} &')
        time.sleep(2)
        ndn.net[src_name].cmd(f'ndnd cat "{data_name}" > /tmp/recv.bin 2>/dev/null')
        diff = ndn.net[src_name].cmd(f"diff {TEST_FILE} /tmp/recv.bin").strip()
        transfer_ok = diff == ""

    # Collect per-node memory usage (RSS of ndnd fw processes)
    mem_samples = []
    for host in ndn.net.hosts:
        rss = host.cmd("ps -C ndnd -o rss= 2>/dev/null").strip()
        for val in rss.split("\n"):
            val = val.strip()
            if val.isdigit():
                mem_samples.append(int(val))
    avg_mem_kb = sum(mem_samples) // max(len(mem_samples), 1)

    ndn.stop()

    return {
        "grid_size": grid_size,
        "num_nodes": num_nodes,
        "num_links": num_links,
        "convergence_s": conv_time,
        "transfer_ok": transfer_ok,
        "avg_mem_kb": avg_mem_kb,
    }


def main():
    parser = argparse.ArgumentParser(description="NDNd DV scalability test")
    parser.add_argument("--grids", nargs="+", type=int, default=[2, 3, 4, 5],
                        help="Grid sizes to test (default: 2 3 4 5)")
    parser.add_argument("--trials", type=int, default=1,
                        help="Repetitions per grid size (default: 1)")
    parser.add_argument("--delay", default="10ms",
                        help="Per-link delay (default: 10ms)")
    parser.add_argument("--bw", type=int, default=10,
                        help="Per-link bandwidth in Mbps (default: 10)")
    parser.add_argument("--out", default="results/emu",
                        help="Output directory (default: results/emu)")
    parser.add_argument("--cores", type=int, default=0,
                        help="Limit CPU cores per node (0 = no limit)")
    args = parser.parse_args()

    # Clear sys.argv so Minindn's internal argparse doesn't choke on our flags
    sys.argv = [sys.argv[0]]

    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "scalability.csv")

    with ResultWriter(csv_path) as writer:
        for grid_size in args.grids:
            for trial in range(1, args.trials + 1):
                info(f"\n=== Grid {grid_size}x{grid_size}, trial {trial} ===\n")
                raw = run_trial(grid_size, delay=args.delay, bw=args.bw,
                               cores=args.cores)
                result = emu_trial_result(
                    grid_size=raw["grid_size"],
                    num_nodes=raw["num_nodes"],
                    num_links=raw["num_links"],
                    convergence_s=raw["convergence_s"],
                    transfer_ok=raw["transfer_ok"],
                    avg_mem_kb=raw["avg_mem_kb"],
                    trial=trial,
                )
                writer.write(result)
                info(f"  convergence={result.convergence_s}s  "
                     f"transfer={'OK' if result.transfer_ok else 'FAIL'}  "
                     f"mem={result.avg_mem_kb}KB\n")

    info(f"\nResults written to {csv_path}\n")


if __name__ == "__main__":
    setLogLevel("info")
    main()
