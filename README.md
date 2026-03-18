# ATLAS Scenarios

Emulation scenarios for NDN using [Mini-NDN](https://github.com/named-data/mini-ndn) with [NDNd](https://github.com/named-data/ndnd) (YaNFD forwarder + DV routing) instead of NFD + NLSR.

Everything runs inside a Docker container — no manual setup required.

## Prerequisites

- Docker

## Quick Start

Build the image (one-time):

```bash
docker build -t atlas-scenarios .
```

Run the included demo (3-node file transfer test):

```bash
docker run --rm --privileged atlas-scenarios
```

Run a specific experiment:

```bash
docker run --rm --privileged atlas-scenarios emu/ndnd_demo.py
```

Drop into an interactive shell inside the container:

```bash
docker run --rm --privileged -it atlas-scenarios bash
```

## Repository Structure

```
emu/
├── ndnd.py       # NDNd_FW  — Mini-NDN Application for the YaNFD forwarder
├── dv.py         # NDNd_DV  — Mini-NDN Application for the DV routing daemon
├── dv_util.py    # setup() / converge() helpers for DV routing
├── ndnd_demo.py  # Example experiment: 3-node file transfer test
```

## Writing Your Own Experiment

Add a new Python file under `emu/`, rebuild the image, and run it:

```bash
docker build -t atlas-scenarios .
docker run --rm --privileged atlas-scenarios emu/my_experiment.py
```

Minimal experiment template — replace `Nfd`/`Nlsr` with NDNd:

```python
from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd import NDNd_FW
from minindn.helpers import dv_util

NETWORK = "/minindn"

# ... build topology, create Minindn instance ...

ndn = Minindn(topo=topo)
ndn.start()

# 1) Start forwarder on all nodes (replaces Nfd)
AppManager(ndn, ndn.net.hosts, NDNd_FW)

# 2) Start DV routing on all nodes (replaces NLSR)
dv_util.setup(ndn, network=NETWORK)

# 3) Wait for routing to converge
dv_util.converge(ndn.net.hosts, network=NETWORK)

# Ready — all nodes can now reach each other via NDN names.
```

### Key differences from NFD + NLSR

| NFD / NLSR | NDNd equivalent |
|---|---|
| `from minindn.apps.nfd import Nfd` | `from minindn.apps.ndnd import NDNd_FW` |
| `from minindn.apps.nlsr import Nlsr` | `from minindn.helpers import dv_util` |
| `AppManager(ndn, hosts, Nfd)` | `AppManager(ndn, hosts, NDNd_FW)` |
| `AppManager(ndn, hosts, Nlsr, ...)` | `dv_util.setup(ndn, network=...)` |
| `Minindn.verifyDependencies()` | Skip (it checks for `nfd`/`nlsr`) |
| `nfdc route list` | `ndnd fw route-list` |
| `nfdc face list` | `ndnd fw face-list` |

### NDNd_FW options

```python
AppManager(ndn, ndn.net.hosts, NDNd_FW,
    config={},       # extra YaNFD config dict (merged with defaults)
    logLevel='INFO', # NONE, INFO, DEBUG, TRACE
    threads=2,       # forwarding threads
)
```

### dv_util options

```python
dv_util.setup(ndn, network='/minindn')   # network prefix
dv_util.converge(nodes, deadline=30,      # seconds before giving up
                 network='/minindn',
                 use_nfdc=False)          # True if using NFD instead of NDNd
```

## References

- [NDNd repository](https://github.com/named-data/ndnd)
- [NDNd e2e tests](https://github.com/named-data/ndnd/tree/main/e2e) — the source of these integration modules
- [Mini-NDN documentation](https://minindn.memphis.edu/)
