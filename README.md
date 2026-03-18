# ATLAS Scenarios

Emulation scenarios for NDN using [Mini-NDN](https://github.com/named-data/mini-ndn) with [NDNd](https://github.com/named-data/ndnd) (YaNFD forwarder + DV routing) instead of NFD + NLSR.

## Prerequisites

A running Mini-NDN Docker container:

```bash
docker run -m 4g --cpus=4 -it --privileged \
    -v /lib/modules:/lib/modules \
    ghcr.io/named-data/mini-ndn:master bash
```

## Setup (inside the container)

### 1. Install Go 1.24+

The container ships Go 1.18 which is too old for NDNd. Install a newer version:

```bash
wget -q https://go.dev/dl/go1.24.1.linux-amd64.tar.gz -O /tmp/go.tar.gz
rm -rf /usr/local/go && tar -C /usr/local -xzf /tmp/go.tar.gz
export PATH=/usr/local/go/bin:$HOME/go/bin:$PATH
```

### 2. Install NDNd

```bash
go install github.com/named-data/ndnd/cmd/ndnd@latest
cp ~/go/bin/ndnd /usr/local/bin/
```

Verify:

```bash
ndnd --help
```

### 3. Install Mini-NDN NDNd modules

Copy the three integration files into your Mini-NDN installation:

```bash
cp emu/ndnd.py   /mini-ndn/minindn/apps/ndnd.py
cp emu/dv.py     /mini-ndn/minindn/apps/dv.py
cp emu/dv_util.py /mini-ndn/minindn/helpers/dv_util.py
```

That's it — no other changes to Mini-NDN are needed.

## Repository Structure

```
emu/
├── ndnd.py       # NDNd_FW  — Mini-NDN Application for the YaNFD forwarder
├── dv.py         # NDNd_DV  — Mini-NDN Application for the DV routing daemon
├── dv_util.py    # setup() / converge() helpers for DV routing
└── ndnd_demo.py  # Example experiment: 3-node ping test
```

## Quick Start

```bash
# (inside the container, after setup)
sudo python3 /root/atlas-scenarios/emu/ndnd_demo.py
```

## Writing Your Own Experiment

Minimal example — replace `Nfd`/`Nlsr` with NDNd:

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
#    Automatically initializes trust, generates per-node keys,
#    discovers neighbors from the topology, and starts ndn-dv.
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
