import time

from mininet.log import info

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager

from minindn.apps.ndnd_dv import NDNd_DV, DEFAULT_NETWORK


def setup(ndn: Minindn, network=DEFAULT_NETWORK, dv_config=None) -> float:
    """Start DV routing on all nodes (initializes trust, creates keys).

    Returns the wall-clock timestamp of when DV apps were started, so
    callers can accurately measure convergence from the announcement event.
    """
    time.sleep(1)  # wait for fw to start

    NDNd_DV.init_trust(network)
    info('Starting ndn-dv on nodes\n')
    AppManager(ndn, ndn.net.hosts, NDNd_DV, network=network,
               dv_config=dv_config)
    return time.time()


def converge(nodes, deadline=30, network=DEFAULT_NETWORK, start=None) -> float:
    """Wait for DV routing to converge on all nodes.

    Args:
        start: wall-clock time when DV was started (from setup()).
               If None, starts counting from now.

    Returns convergence time in seconds (float, 0.05 s resolution).
    Raises Exception if deadline is exceeded.
    """
    if start is None:
        start = time.time()
    info('Waiting for routing to converge\n')
    while time.time() - start < deadline:
        time.sleep(0.05)
        if _is_converged(nodes, network=network):
            total = round(time.time() - start, 2)
            info(f'Routing converged in {total} seconds\n')
            return total

    raise Exception('Routing did not converge')


def _is_converged(nodes, network=DEFAULT_NETWORK) -> bool:
    for node in nodes:
        routes = node.cmd('ndnd fw route-list')
        for other in nodes:
            if f'{network}/{other.name}' not in routes:
                info(f'Routing not converged on {node.name} for {other.name}\n')
                return False
    return True
