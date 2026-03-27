#!/usr/bin/env python3
"""Quick one_step churn test with debug logging check."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mininet.log import setLogLevel, info
from emu._helpers import NETWORK, setup_grid
from minindn.helpers import dv_util

setLogLevel("info")

grid_size = 2
dvc = {"one_step": True}

ndn, num_nodes, num_links = setup_grid(grid_size, 10, 10, 0)
dv_start = dv_util.setup(ndn, network=NETWORK, dv_config=dvc)

try:
    dv_util.converge(ndn.net.hosts, deadline=60, network=NETWORK, start=dv_start)
except Exception as e:
    info(f"  converge: {e}\n")

h0 = ndn.net.hosts[0]
pfx = "/data/n0_0/testpfx"
home = h0.params['params']['homeDir']

info(f"\n*** Announcing prefix {pfx} on {h0.name}\n")
h0.cmd(f'ndnd put --expose "{pfx}" < /dev/null &')
time.sleep(3)

info(f"\n*** Processes:\n")
info(h0.cmd("ps aux | grep 'ndnd put' | grep -v grep") + "\n")

info(f"\n*** DV log MGMT lines BEFORE withdrawal:\n")
info(h0.cmd(f"grep -i 'MGMT' {home}/log/dv.log | tail -10") + "\n")

info(f"\n*** Withdrawing prefix via pkill\n")
h0.cmd("pkill -f 'ndnd put --expose.*testpfx' 2>/dev/null; true")
time.sleep(1)

info(f"\n*** Processes after withdrawal:\n")
info(h0.cmd("ps aux | grep 'ndnd put' | grep -v grep") + "\n")

time.sleep(3)
info(f"\n*** DV log MGMT lines AFTER withdrawal:\n")
info(h0.cmd(f"grep -i 'MGMT' {home}/log/dv.log | tail -20") + "\n")

info(f"\n*** Full DV log tail (last 50 lines):\n")
info(h0.cmd(f"tail -50 {home}/log/dv.log") + "\n")

ndn.stop()
