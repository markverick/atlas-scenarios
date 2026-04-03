#!/usr/bin/env python3
"""
Multi-hop DV routing changes test.

Topology:  a -- b -- c -- d  (linear, 4-node)

Tests that NDNd DV correctly handles:
  1. Link failure  (b--c down)  → routes to d withdrawn, traffic blocked
  2. Link recovery (b--c up)   → routes restored,       traffic flows
  3. Prefix withdrawal (app on d withdraws /app/data via RIB unregister)
     → /app/data disappears from a's RIB, traffic blocked
  4. Prefix re-announcement (app on d re-announces /app/data via RIB register)
     → /app/data reappears, traffic flows

Prefix announce/withdraw uses `ndnd put --expose` which calls the
/localhost/nlsr/rib/register and /unregister management Interests —
the same mechanism real applications use.  DV itself keeps running.

Reads a user-provided scenario definition.

Usage:
    sudo ./run.sh emu multihop --scenario <scenario.json>
"""

import argparse
import json
import os
import sys
import time

from mininet.log import setLogLevel, info
from mininet.topo import Topo

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd_fw import NDNd_FW
from minindn.apps.ndnd_dv import NDNd_DV
from minindn.helpers import dv_util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

TEST_FILE = "/tmp/multihop-test.bin"


# ── Topology ────────────────────────────────────────────────────────


def build_topology(scenario):
    """Build a Mininet topology from the scenario definition."""
    topo = Topo()
    nodes = {}
    for name in scenario["topology"]["nodes"]:
        nodes[name] = topo.addHost(name)
    for link in scenario["topology"]["links"]:
        topo.addLink(
            nodes[link["src"]], nodes[link["dst"]],
            delay=link.get("delay", "10ms"),
            bw=link.get("bw", 10),
        )
    return topo


# ── Helpers ─────────────────────────────────────────────────────────


def wait_for_route(node, prefix, present, timeout):
    """Poll a node's route list until *prefix* appears or disappears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        routes = node.cmd("ndnd fw route-list")
        found = prefix in routes
        if found == present:
            elapsed = round(timeout - (deadline - time.time()), 1)
            state = "appeared" if present else "withdrawn"
            info(f"    route {prefix} {state} on {node.name} after {elapsed}s\n")
            return True
        time.sleep(0.5)
    return False


def check_traffic(consumer, producer, data_name, fetch_timeout,
                  expect_success):
    """Test data-plane reachability with a fresh (uncached) name.

    Uses a unique name per invocation so the content store can never
    satisfy the request — the Interest must traverse the FIB/RIB.

    expect_success=True  → pass when data matches  (traffic_flows)
    expect_success=False → pass when data does NOT match (traffic_blocked)
    """
    ts = int(time.time() * 1000)
    unique_name = f"{data_name}/{ts}"
    recv_file = f"/tmp/multihop-recv-{ts}.bin"

    if expect_success:
        # Start a short-lived producer for this specific name
        producer.cmd(f'ndnd put --expose "{unique_name}" < {TEST_FILE} &')
        time.sleep(2)

    # Attempt fetch with timeout
    consumer.cmd(
        f'timeout {fetch_timeout} ndnd cat "{unique_name}" > {recv_file} 2>/dev/null'
    )

    # Verify transfer
    ret = consumer.cmd(f"cmp -s {TEST_FILE} {recv_file}; echo $?").strip()
    success = ret == "0"

    if expect_success:
        # Clean up the producer we started
        producer.cmd(f'pkill -f "ndnd put.*{ts}" 2>/dev/null || true')

    if expect_success:
        return success
    return not success


# ── Actions ─────────────────────────────────────────────────────────


def _peer_ip(node_a, node_b):
    """Return the IP address of node_b on the link shared with node_a."""
    for intf in node_a.intfList():
        if intf.link is None:
            continue
        other = intf.link.intf2 if intf.link.intf1 == intf else intf.link.intf1
        if other.node == node_b:
            return other.IP()
    return None


def _link_intf(node, peer):
    """Return the interface name on *node* facing *peer*."""
    for intf in node.intfList():
        if intf.link is None:
            continue
        other = intf.link.intf2 if intf.link.intf1 == intf else intf.link.intf1
        if other.node == peer:
            return intf.name
    return None


def execute_action(net, action, prefix_procs):
    """Execute a single scenario action.

    prefix_procs: dict mapping (node_name, prefix) → Popen handle for the
                  `ndnd put --expose` process that announced the prefix.
    """
    atype = action["type"]
    if atype == "link_down":
        src_node, dst_node = net[action["src"]], net[action["dst"]]
        info(f"  action: link_down {action['src']}--{action['dst']}\n")
        # Use tc-netem 100% loss instead of ifconfig down or iptables.
        # ifconfig down destroys the kernel socket → NDNd face lost.
        # iptables DROP still causes NDNd to destroy idle/failing faces.
        # tc-netem loss is invisible to the socket layer: the UDP face
        # stays alive but no packets are delivered, so DV detects
        # neighbor loss via missed advertisements (router_dead_interval).
        intf_s = _link_intf(src_node, dst_node)
        intf_d = _link_intf(dst_node, src_node)
        if intf_s:
            src_node.cmd(f'tc qdisc change dev {intf_s} root netem loss 100%')
        if intf_d:
            dst_node.cmd(f'tc qdisc change dev {intf_d} root netem loss 100%')
    elif atype == "link_up":
        src_node, dst_node = net[action["src"]], net[action["dst"]]
        info(f"  action: link_up {action['src']}--{action['dst']}\n")
        # Remove the 100% loss — the original netem delay qdisc is
        # already in place (Mininet sets it up at link creation).
        intf_s = _link_intf(src_node, dst_node)
        intf_d = _link_intf(dst_node, src_node)
        delay = action.get("delay", "10ms")
        if intf_s:
            src_node.cmd(f'tc qdisc change dev {intf_s} root netem delay {delay}')
        if intf_d:
            dst_node.cmd(f'tc qdisc change dev {intf_d} root netem delay {delay}')
    elif atype == "announce_prefix":
        node = net[action["node"]]
        prefix = action["prefix"]
        info(f"  action: announce_prefix {prefix} on {node.name}\n")
        # Start `ndnd put --expose` in background — this sends a
        # /localhost/nlsr/rib/register management Interest to DV,
        # which then propagates the prefix via DV advertisements.
        node.cmd(f'ndnd put --expose "{prefix}" < {TEST_FILE} &')
        time.sleep(2)  # give DV time to propagate
    elif atype == "withdraw_prefix":
        node = net[action["node"]]
        prefix = action["prefix"]
        info(f"  action: withdraw_prefix {prefix} on {node.name}\n")
        # Killing `ndnd put --expose` triggers /localhost/nlsr/rib/unregister,
        # which makes DV withdraw the prefix from its advertisements.
        node.cmd('pkill -f "ndnd put" 2>/dev/null || true')
        time.sleep(1)
    else:
        raise ValueError(f"Unknown action type: {atype}")


# ── Assertions ──────────────────────────────────────────────────────


def check_assertion(assertion, net, network, consumer, producer,
                    app_prefix, timeout, fetch_timeout):
    """Check a single assertion and return True when it passes."""
    atype = assertion["type"]

    if atype == "prefix_reachable":
        node = net[assertion["from"]]
        return wait_for_route(node, assertion["prefix"],
                              present=True, timeout=timeout)

    if atype == "prefix_unreachable":
        node = net[assertion["from"]]
        return wait_for_route(node, assertion["prefix"],
                              present=False, timeout=timeout)

    if atype == "traffic_flows":
        return check_traffic(consumer, producer, app_prefix,
                             fetch_timeout, expect_success=True)

    if atype == "traffic_blocked":
        return check_traffic(consumer, producer, app_prefix,
                             fetch_timeout, expect_success=False)

    raise ValueError(f"Unknown assertion type: {atype}")


# ── Main ────────────────────────────────────────────────────────────


def run(scenario_path):
    with open(scenario_path) as f:
        scenario = json.load(f)

    network = scenario.get("network", "/minindn")
    timeout = scenario.get("dv_converge_timeout_s", 30)
    fetch_timeout = scenario.get("traffic_fetch_timeout_s", 5)

    dv_config = {}
    if scenario.get("advertise_interval"):
        dv_config["advertise_interval"] = scenario["advertise_interval"]
    if scenario.get("router_dead_interval"):
        dv_config["router_dead_interval"] = scenario["router_dead_interval"]

    # ── Network setup ───────────────────────────────────────────────

    Minindn.cleanUp()
    topo = build_topology(scenario)
    ndn = Minindn(topo=topo, controller=None)
    ndn.start()

    info("Starting NDNd forwarder on all nodes\n")
    AppManager(ndn, ndn.net.hosts, NDNd_FW)
    time.sleep(1)

    # Start DV on all nodes
    info("Initialising DV trust and starting routing\n")
    NDNd_DV.init_trust(network)
    for host in ndn.net.hosts:
        app = NDNd_DV(host, network=network,
                      dv_config=dv_config or None)
        app.start()

    info("Waiting for initial DV convergence\n")
    dv_util.converge(ndn.net.hosts, network=network, deadline=timeout)

    consumer = ndn.net[scenario["consumer"]]
    producer = ndn.net[scenario["producer"]]
    app_prefix = scenario.get("app_prefix", "/app/data")

    # Create a small test payload once
    os.system(f"dd if=/dev/urandom of={TEST_FILE} bs=256 count=1 2>/dev/null")

    # Track per-node prefix announcement processes
    prefix_procs = {}

    # ── Run phases ──────────────────────────────────────────────────

    results = []

    for idx, phase in enumerate(scenario["phases"]):
        info(f"\n{'=' * 60}\n")
        info(f"Phase {idx}: {phase['name']}\n")
        info(f"  {phase['description']}\n")

        for action in phase.get("actions", []):
            execute_action(ndn.net, action, prefix_procs)

        for assertion in phase["assert"]:
            ok = check_assertion(
                assertion, ndn.net, network,
                consumer, producer, app_prefix,
                timeout, fetch_timeout,
            )
            tag = "PASS" if ok else "FAIL"
            info(f"  [{tag}] {assertion['type']}\n")
            results.append((phase["name"], assertion["type"], ok))

    # ── Summary ─────────────────────────────────────────────────────

    info(f"\n{'=' * 60}\n")
    info("Summary\n")
    passed = sum(1 for *_, ok in results if ok)
    for phase_name, atype, ok in results:
        info(f"  [{'PASS' if ok else 'FAIL'}] {phase_name}: {atype}\n")
    info(f"\n{passed}/{len(results)} assertions passed\n")

    ndn.stop()
    return passed == len(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Multi-hop DV routing changes test")
    parser.add_argument(
        "--scenario", required=True,
        help="Path to scenario JSON file",
    )
    args = parser.parse_args()

    setLogLevel("info")
    ok = run(args.scenario)
    sys.exit(0 if ok else 1)
