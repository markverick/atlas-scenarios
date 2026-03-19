# ATLAS Scenarios

Emulation and simulation scenarios for NDN using [NDNd](https://github.com/named-data/ndnd) (YaNFD forwarder + DV routing).

| Mode | Engine | What it measures |
|---|---|---|
| **Emulation** | [Mini-NDN](https://github.com/named-data/mini-ndn) + real NDNd processes | Convergence, transfer, memory |
| **Simulation** | [ndndSIM](https://github.com/markverick/ndndSIM) (ns-3 + NDNd via CGo) | Convergence (deterministic) |

Both produce CSV results in the same schema so they can be plotted side-by-side.

---

## Prerequisites

Only these need to be installed system-wide. Everything else is built from source by `setup.sh`.

| Tool | Minimum version |
|---|---|
| Go | 1.22+ |
| GCC / G++ | 11+ |
| CMake | 3.16+ |
| Python 3 | 3.8+ |
| git, sudo | any |

On Ubuntu 22.04+:

```bash
# Go (if not already installed)
wget -qO- https://go.dev/dl/go1.24.1.linux-amd64.tar.gz | sudo tar -C /usr/local -xz
export PATH="/usr/local/go/bin:$PATH"

# Build tools (if not already installed)
sudo apt install build-essential cmake git python3-pip
```

---

## Setup

Clone and run the setup script. It builds **everything** locally under `deps/`:

```bash
git clone <this-repo> atlas-scenarios
cd atlas-scenarios
./setup.sh
```

This installs:
- **Mininet** from source → `deps/mininet`
- **Mini-NDN** from source (with NDNd integration modules) → `deps/mini-ndn`
- **NDNd** forwarder from Go source → `deps/bin/ndnd`
- **ns-3** (tag `ns-3.47`) + **ndndSIM** contrib module → `deps/ns-3`
- Python plotting deps (`matplotlib`, `numpy`)

---

## Running Experiments

All experiments are run through `./run.sh`:

### Demo (3-node linear)

```bash
sudo ./run.sh emu demo          # emulation (Mini-NDN)
./run.sh sim demo               # simulation (ndndSIM)
```

Topology: a — b — c. Transfers data from c to a.

### Scalability (NxN grid)

```bash
sudo ./run.sh emu scalability --grids 2 3 4 5 --trials 1
./run.sh sim scalability --grids 2 3 4 5
```

Output: `results/emu/scalability.csv`, `results/sim/scalability.csv`

### Comparison Plots

```bash
./run.sh plot
```

Output: `results/plots/convergence.png`, `results/plots/memory.png`

### All Options

```bash
./run.sh                     # Show help

# Emulation
sudo ./run.sh emu scalability --grids 2 3 4 5 6 --trials 3 --delay 10ms --bw 10

# Simulation
./run.sh sim scalability --grids 2 3 4 5 6 --delay 10 --sim-time 60

# Plots
./run.sh plot --emu results/emu/scalability.csv --sim results/sim/scalability.csv --out results/plots
```

---

## Repository Structure

```
setup.sh                    # Build all deps from source
run.sh                      # Unified experiment runner
lib/                        # Shared Python modules
├── topology.py             #   Grid topology builder (emu + sim)
└── result_adapter.py       #   Unified result adapter (TrialResult, CSV writer)
sim/                        # Simulation scenarios
├── atlas-scenario.cc       #   Parameterised ndndSIM C++ scenario
├── _helpers.py             #   Shared ns-3 build/run utilities
├── demo.py                 #   3-node linear ndndSIM demo
└── scalability.py          #   NxN grid ndndSIM scalability test
minindn_ndnd/               # Mini-NDN integration for NDNd
├── ndnd_fw.py              #   NDNd_FW — YaNFD forwarder Application
├── ndnd_dv.py              #   NDNd_DV — DV routing Application
└── dv_util.py              #   setup() / converge() helpers
emu/                        # Emulation scenarios
├── demo.py                 #   3-node file transfer demo
└── scalability.py          #   NxN grid scalability test
plot.py                     # Comparison plot generator
deps/                       # Built dependencies (gitignored)
results/                    # Output CSVs and plots (gitignored)
```

---

## Writing Your Own Experiment

### Emulation

Add a Python file under `emu/` and run it:

```bash
sudo ./run.sh emu my_experiment.py
```

Minimal template:

```python
from mininet.topo import Topo
from minindn.minindn import Minindn
from minindn.apps.app_manager import AppManager
from minindn.apps.ndnd_fw import NDNd_FW
from minindn.helpers import dv_util

NETWORK = "/minindn"

topo = Topo()
a = topo.addHost("a")
b = topo.addHost("b")
topo.addLink(a, b, delay="10ms", bw=10)

ndn = Minindn(topo=topo, controller=None)
ndn.start()

AppManager(ndn, ndn.net.hosts, NDNd_FW)
dv_util.setup(ndn, network=NETWORK)
dv_util.converge(ndn.net.hosts, network=NETWORK)

# Transfer data with: ndnd put --expose "/name" < file
#                     ndnd cat "/name" > output
```

### Simulation

Use `sim/demo.py` or `sim/scalability.py` as templates. C++ ns-3 scenario generation pattern:

```cpp
ndndsim::NdndStackHelper stackHelper;
stackHelper.Install(nodes);
ndndsim::NdndStackHelper::EnableDvRouting("/ndn", nodes);
```

See the [ndndSIM README](https://github.com/markverick/ndndSIM) for the full API.

---

## CSV Schema

Both emu and sim produce identical CSV columns:

```csv
grid_size,num_nodes,num_links,trial,convergence_s,transfer_ok,avg_mem_kb
```

---

## Links

- [NDNd](https://github.com/named-data/ndnd)
- [ndndSIM](https://github.com/markverick/ndndSIM)
- [Mini-NDN](https://github.com/named-data/mini-ndn)
- [ns-3](https://www.nsnam.org/)
