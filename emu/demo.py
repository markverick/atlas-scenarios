#!/usr/bin/env python3
"""
Quick demo: 3-node linear topology with NDNd file transfer.

Topology:  a -- b -- c
Transfers a 64 KB file from c to a using ndnd put/cat.

Usage:
    python3 emu/demo.py
"""

import os
import time

from mininet.log import setLogLevel, info
from mininet.topo import Topo

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd_fw import NDNd_FW
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

    ndn = Minindn(topo=topo, controller=None)
    ndn.start()

    info("Starting NDNd forwarder on every node\n")
    AppManager(ndn, ndn.net.hosts, NDNd_FW)

    dv_start = dv_util.setup(ndn, network=NETWORK)
    dv_util.converge(ndn.net.hosts, network=NETWORK, start=dv_start)

    # ------ file transfer test (a -> c via b) ------
    os.system(f"dd if=/dev/urandom of={TEST_FILE} bs=1K count=64 2>/dev/null")

    data_name = f"{NETWORK}/c/test"
    info(f"Publishing data on node c as {data_name}\n")
    ndn.net["c"].cmd(f'ndnd put --expose "{data_name}" < {TEST_FILE} &')
    time.sleep(2)

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
