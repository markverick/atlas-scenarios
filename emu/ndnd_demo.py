#!/usr/bin/env python3
# -*- Mode:python; c-file-style:"gnu"; indent-tabs-mode:nil -*- */
#
# Example: Using NDNd (YaNFD + DV) instead of NFD + NLSR in Mini-NDN
#
# Based on https://github.com/named-data/ndnd/tree/main/e2e
#
# Usage:
#   sudo python3 ndnd_demo.py

import os
import time

from mininet.log import setLogLevel, info
from mininet.topo import Topo

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd import NDNd_FW
from minindn.helpers import dv_util
from minindn.util import MiniNDNCLI

NETWORK = "/minindn"
TEST_FILE = "/tmp/test.bin"


def run():
    Minindn.cleanUp()

    info("Building topology\n")
    topo = Topo()
    a = topo.addHost('a')
    b = topo.addHost('b')
    c = topo.addHost('c')
    topo.addLink(a, b, delay='10ms', bw=10)
    topo.addLink(b, c, delay='10ms', bw=10)

    ndn = Minindn(topo=topo)
    ndn.start()

    # Start NDNd forwarder (YaNFD) on every node
    info("Starting NDNd forwarder on every node\n")
    AppManager(ndn, ndn.net.hosts, NDNd_FW)

    # Start DV routing on every node (initializes trust, creates keys, waits for convergence)
    dv_util.setup(ndn, network=NETWORK)
    dv_util.converge(ndn.net.hosts, network=NETWORK)

    # ------ file transfer test (a -> c via b) ------
    # Create a small test file
    os.system(f"dd if=/dev/urandom of={TEST_FILE} bs=1K count=64 2>/dev/null")

    # Publish data on node c
    data_name = f"{NETWORK}/c/test"
    info(f"Publishing data on node c as {data_name}\n")
    ndn.net["c"].cmd(f'ndnd put --expose "{data_name}" < {TEST_FILE} &')
    time.sleep(2)

    # Fetch data from node a (routes through b)
    info("Fetching data from node a -> c\n")
    ndn.net["a"].cmd(f'ndnd cat "{data_name}" > /tmp/recv.bin 2> /tmp/cat.log')

    diff = ndn.net["a"].cmd(f"diff {TEST_FILE} /tmp/recv.bin").strip()
    if diff:
        info("FAIL: file contents do not match!\n")
        info(ndn.net["a"].cmd("cat /tmp/cat.log") + "\n")
    else:
        info("SUCCESS: file transferred correctly from c to a\n")

    info("\nExperiment Completed!\n")
    MiniNDNCLI(ndn.net)
    ndn.stop()


if __name__ == '__main__':
    setLogLevel("info")
    run()
