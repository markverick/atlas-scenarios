import time

from mininet.log import info

from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager

from minindn_ndnd.ndnd_dv import NDNd_DV, DEFAULT_NETWORK


def setup(ndn: Minindn, network=DEFAULT_NETWORK, dv_config=None, ndnd_bin='ndnd',
          node_dv_configs=None) -> float:
    """Start DV routing on all nodes (initializes trust, creates keys).

    Args:
        node_dv_configs: optional dict mapping node name -> dv_config override.
            Nodes not in the dict use the shared dv_config.

    Returns the wall-clock timestamp of when DV apps were started, so
    callers can accurately measure convergence from the announcement event.
    """
    time.sleep(1)  # wait for fw to start

    NDNd_DV.init_trust(network, ndnd_bin=ndnd_bin)
    info('Starting ndn-dv on nodes\n')
    if node_dv_configs:
        # Start DV per-node so each can receive its own config.
        apps = []
        for host in ndn.net.hosts:
            cfg = node_dv_configs.get(host.name, dv_config)
            app = NDNd_DV(host, network=network, dv_config=cfg, ndnd_bin=ndnd_bin)
            app.start()
            apps.append(app)
        ndn.cleanups.append(lambda: [app.stop() for app in apps])
    else:
        AppManager(ndn, ndn.net.hosts, NDNd_DV, network=network,
                   dv_config=dv_config, ndnd_bin=ndnd_bin)
    return time.time()


def converge(nodes, deadline=30, network=DEFAULT_NETWORK, start=None, ndnd_bin='ndnd') -> float:
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
        if _is_converged(nodes, network=network, ndnd_bin=ndnd_bin):
            total = round(time.time() - start, 2)
            info(f'Routing converged in {total} seconds\n')
            return total

    raise Exception('Routing did not converge')


def _is_converged(nodes, network=DEFAULT_NETWORK, ndnd_bin='ndnd') -> bool:
    for node in nodes:
        routes = node.cmd(f'{ndnd_bin} fw route-list')
        for other in nodes:
            if other.name == node.name:
                continue  # self-route is not installed in FIB (always local)
            if f'{network}/{other.name}' not in routes:
                info(f'Routing not converged on {node.name} for {other.name}\n')
                return False
    return True
