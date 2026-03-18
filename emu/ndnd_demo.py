#!/usr/bin/env python3
# -*- Mode:python; c-file-style:"gnu"; indent-tabs-mode:nil -*- */
#
# Example: Using NDNd (YaNFD + DV) instead of NFD + NLSR in Mini-NDN
#
# Based on https://github.com/named-data/ndnd/tree/main/e2e
#
# Usage:
#   sudo python3 ndnd_demo.py

from subprocess import PIPE

from mininet.log import setLogLevel, info
from mininet.topo import Topo

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd import NDNd_FW
from minindn.helpers import dv_util
from minindn.util import MiniNDNCLI, getPopen

PREFIX = "/example"
NETWORK = "/minindn"


def printOutput(output):
    _out = output.decode("utf-8").split("\n")
    for _line in _out:
        info(_line + "\n")


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

    # ------ ndnping test ------
    info("Starting ndnpingserver on node c\n")
    pingserver_log = open(f"{ndn.workDir}/c/ndnpingserver.log", "w")
    getPopen(ndn.net["c"], f"ndnpingserver {PREFIX}",
             stdout=pingserver_log, stderr=pingserver_log)

    info("Running ndnping from a -> c\n")
    ping1 = getPopen(ndn.net["a"], f"ndnping {PREFIX} -c 5",
                      stdout=PIPE, stderr=PIPE)
    ping1.wait()
    printOutput(ping1.stdout.read())

    info("\nExperiment Completed!\n")
    MiniNDNCLI(ndn.net)
    ndn.stop()


if __name__ == '__main__':
    setLogLevel("info")
    run()
