"""Shared emulation helpers for MiniNDN grid scenarios.

Provides common infrastructure used by both emu/scalability.py and
emu/routing.py: grid setup, packet capture, and memory collection.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd_fw import NDNd_FW

from lib.topology import build_grid_topo, grid_stats, build_conf_topo, conf_stats

NETWORK = "/minindn"
NDND_TRAFFIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ndnd-traffic")


def setup_grid(grid_size, delay_ms, bw_mbps, cores=0):
    """Set up MiniNDN NxN grid with NDNd forwarder on every node.

    Returns (ndn, num_nodes, num_links).
    """
    Minindn.cleanUp()
    topo, _nodes = build_grid_topo(grid_size, delay=f"{delay_ms}ms", bw=bw_mbps)
    num_nodes, num_links = grid_stats(grid_size)
    ndn = Minindn(topo=topo, controller=None)
    ndn.start()
    if cores > 0:
        for host in ndn.net.hosts:
            host.setCPUs(cores=cores)
    AppManager(ndn, ndn.net.hosts, NDNd_FW)
    return ndn, num_nodes, num_links


def setup_conf_topo(conf_path, delay_ms, bw_mbps, cores=0):
    """Set up MiniNDN from a Mini-NDN .conf topology file.

    Returns (ndn, num_nodes, num_links).
    """
    Minindn.cleanUp()
    topo, _nodes = build_conf_topo(conf_path, delay=f"{delay_ms}ms", bw=bw_mbps)
    num_nodes, num_links = conf_stats(conf_path)
    ndn = Minindn(topo=topo, controller=None)
    ndn.start()
    if cores > 0:
        for host in ndn.net.hosts:
            host.setCPUs(cores=cores)
    AppManager(ndn, ndn.net.hosts, NDNd_FW)
    return ndn, num_nodes, num_links


def start_tcpdump(hosts, prefix="ndnd_cap"):
    """Start tcpdump on all hosts, capturing outbound UDP/6363.

    Returns (cap_tag, cap_paths) where cap_paths maps host name to pcap path.
    """
    cap_tag = f"{os.getpid()}_{int(time.time() * 1000)}"
    cap_paths = {}
    for host in hosts:
        cap = f"/tmp/{prefix}_{cap_tag}_{host.name}.pcap"
        cap_paths[host.name] = cap
        host.cmd(f"rm -f {cap}")
        host.cmd(f"tcpdump -i any -Q out -w {cap} udp port 6363 2>/dev/null &")
    time.sleep(0.3)
    return cap_tag, cap_paths


def stop_tcpdump(hosts, cap_tag, prefix="ndnd_cap"):
    """Stop tcpdump on all hosts."""
    for host in hosts:
        try:
            host.cmd(f"pkill -f 'tcpdump.*{prefix}_{cap_tag}_' 2>/dev/null; true")
        except (AssertionError, OSError):
            # Shell may be in a bad state from prior timer-thread failures;
            # wait for it to drain and retry once.
            time.sleep(0.5)
            try:
                host.waitOutput(verbose=False)
            except Exception:
                pass
            try:
                host.cmd(f"pkill -f 'tcpdump.*{prefix}_{cap_tag}_' 2>/dev/null; true")
            except (AssertionError, OSError):
                pass
    time.sleep(0.5)


def collect_memory(hosts, process_name="ndnd"):
    """Collect average RSS (KB) of a process across all hosts."""
    samples = []
    for host in hosts:
        rss = host.cmd(f"ps -C {process_name} -o rss= 2>/dev/null").strip()
        for val in rss.split("\n"):
            val = val.strip()
            if val.isdigit():
                samples.append(int(val))
    return sum(samples) // max(len(samples), 1)
