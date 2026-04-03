# ATLAS Scenarios

Emulation and simulation scenarios for NDN using [NDNd](https://github.com/named-data/ndnd) (YaNFD forwarder + DV routing).

| Mode | Engine | What it measures |
|---|---|---|
| **Emulation** | [Mini-NDN](https://github.com/named-data/mini-ndn) + real NDNd processes | Convergence, transfer, memory, total traffic |
| **Simulation** | [ndndSIM](https://github.com/markverick/ndndSIM) (ns-3 + NDNd via CGo) | Convergence (RIB-based), total traffic, DV/user traffic split |

Scenarios include scalability tests (NxN grids with app traffic), routing-only
measurement (DV traffic burst with no app traffic), one-step vs two-step
prefix routing comparisons, churn testing under link failures and prefix
events (grid and Sprint topologies), and multi-hop DV routing change tests.

Both produce CSV results in the same schema so they can be plotted side-by-side.

### How Emu and Sim Stay Aligned

The two modes are designed to produce comparable measurements by sharing
the same NDNd codebase and aligning their configurations:

| Aspect | Emulation | Simulation |
|--------|-----------|------------|
| **Forwarder** | Real NDNd (Go binary) | Same NDNd `fw.Thread` via CGo |
| **DV routing** | NDNd DV protocol (SVS v3) | Same DV protocol in Go |
| **Security** | Ed25519 signing (`ndn-cxx` keychain) | Ed25519 signing (Go `SimTrust` keychain) |
| **Byte counting** | UDP payload (= NDNLPv2 wire bytes) | `NdnPayloadTag` (= same LP bytes) |
| **Network prefix** | Configurable (`/minindn` default) | Same, via `--network` CLI param |
| **Time window** | Filtered to `[0, window_s]` | Sim duration = `window_s` |
| **DV intervals** | `0` = use NDNd defaults | Same defaults |
| **Topology** | Mininet P2P links | ns-3 `PointToPointNetDevice` links |

Both paths produce identical per-packet average sizes for user traffic (Interest
~41.6 B, Data ~1113.6 B) and DV advertisements (steady-state ~300 B/pkt) when
run with matching parameters.

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

### Routing-Only Traffic Measurement

```bash
sudo ./run.sh emu routing
./run.sh sim routing
```

Pure DV routing measurement with **no application traffic**. Measures routing
protocol overhead (packet counts, bytes, convergence time) on NxN grids.

Both sim and emu record per-packet event data:
- **Sim**: `NdndLinkTracer` per-packet mode → `packet-trace-*.csv`
- **Emu**: tcpdump pcap → parsed per-packet with `lib/pcap.py`

Convergence is measured identically on both sides: span from the first
`RouterReachable` event to the event completing all FIBs.

### Prefix-Scale Experiment

```bash
# Prefix-scaling queue (Sprint topology, timestamped outputs)
sudo ./jobs.sh start --fresh prefix_scale/sprint_twostep_0to50
./jobs.sh status prefix_scale/sprint_twostep_0to50
```

Each queue run writes to a unique timestamped output root under:

- `experiments/prefix_scale/results/sprint_twostep_0to50/<timestamp>/sim`
- `experiments/prefix_scale/results/sprint_twostep_0to50/<timestamp>/emu`
- `experiments/prefix_scale/results/sprint_twostep_0to50/<timestamp>/compare`

PrefixSync snapshots are disabled by default in two-step mode. This avoids the
bootstrap snapshot cliff around the historical threshold near 50 prefixes and
makes prefix-scaling results follow the incremental-fetch path by default.
To opt back into snapshot behavior explicitly, set
`"disable_prefix_snap": false` in an experiment scenario config.

The churn framework is modular — adding a new topology requires only:
1. Add an entry to `KNOWN_TOPOLOGIES` in `lib/churn_common.py`
2. Create a scenario JSON with `"topology": "<name>"`

Scenario definitions:
- `experiments/prefix_scale/scenarios/*.json` — Prefix-scaling experiment scenarios

Output: `experiments/prefix_scale/results/sprint_twostep_0to50/<timestamp>/{sim,emu,compare}`.

For modular experiment queues, use `./jobs.sh list` to discover experiment folders, scenarios, and queue selectors instead of remembering queue file paths.
Running `./jobs.sh` with no arguments opens a numbered interactive menu.
For `start`, `run`, `attach`, `stop`, and `log`, `./jobs.sh` will prompt for sudo automatically when needed.

The JSON schema is implemented in `lib/config.py`:

- `grids`: list of grid sizes (grid topologies)
- `topology`: topology type — `"grid"` (default) or a named topology (e.g. `"sprint"`)
- `delay_ms`: per-link delay in ms
- `bandwidth_mbps`: per-link bandwidth
- `trials`: repetitions per grid size
- `window_s`: common observation window for both emu and sim
- `num_prefixes`: synthetic prefixes per node (for routing comparison scenarios)
- `advertise_interval`: DV advertisement interval (ms, `0` = default)
- `router_dead_interval`: DV dead interval (ms, `0` = default)
- `prefix_sync_delay`: delay (ms) before starting PrefixSync SVS (`0` = immediate)
- `disable_prefix_snap`: disable PrefixSync snapshots (`true` by default)
- `prefix_snap_threshold`: snapshot threshold override when snapshots are enabled (`0` = Go default)
- `per_prefix_rate`: per-prefix churn rate (events/s/prefix) for prefix-scaling mode
- `prefix_counts`: list of num_prefixes to sweep; empty = use `num_prefixes`
- `modes`: routing modes to run; empty = `["baseline", "two_step", "one_step"]`
- `cores`: CPU core limit (`0` = no limit)

### Prefix-Scale Plots

```bash
python3 experiments/prefix_scale/plot.py --data experiments/prefix_scale/results/.../emu --data2 experiments/prefix_scale/results/.../sim --out experiments/prefix_scale/results/.../compare
```

### All Options

```bash
./run.sh                     # Show help

# Emulation
sudo ./run.sh emu scalability --grids 2 3 4 5 6 --trials 3 --delay 10ms --bw 10 --window 60

# Simulation
./run.sh sim scalability --grids 2 3 4 5 6 --delay 10 --window 60

# Queue-driven prefix-scale pipeline
sudo ./jobs.sh start --fresh prefix_scale/sprint_twostep_0to50
```

---

## Repository Structure

```
setup.sh                    # Build all deps from source
run.sh                      # Unified experiment runner
lib/                        # Shared Python modules
├── topology.py             #   Grid + conf topology builder (emu + sim)
├── result_adapter.py       #   Unified result adapter (TrialResult, CSV writer)
├── config.py               #   JSON scenario config loader
├── pcap.py                 #   NDN-over-UDP pcap parser (per-packet + aggregate)
└── churn_common.py         #   Shared churn constants, topology registry, parsers
sim/                        # Simulation scenarios
├── atlas-scenario.cc       #   Parameterised ndndSIM C++ scenario
├── atlas-multihop-scenario.cc  # Multi-hop DV routing changes C++ scenario
├── atlas-routing-scenario.cc   # Routing-only scenario (no app traffic)
├── atlas-churn-scenario.cc     # Churn scenario (link/prefix events)
├── _helpers.py             #   Shared ns-3 build/run utilities
├── demo.py                 #   3-node linear ndndSIM demo
├── scalability.py          #   NxN grid ndndSIM scalability test
├── multihop.py             #   Multi-hop DV routing test runner
├── routing.py              #   Routing-only traffic measurement
├── onestep_comparison.py   #   One-step vs two-step routing comparison
├── churn.py                #   Unified churn driver (grid + conf topologies)
└── churn_sprint.py         #   Sprint churn wrapper (backward compat)
minindn_ndnd/               # Mini-NDN integration for NDNd
├── ndnd_fw.py              #   NDNd_FW — YaNFD forwarder Application
├── ndnd_dv.py              #   NDNd_DV — DV routing Application
└── dv_util.py              #   setup() / converge() helpers
emu/                        # Emulation scenarios
├── _helpers.py             #   Shared emu helpers (grid/conf setup, tcpdump, etc.)
├── demo.py                 #   3-node file transfer demo
├── scalability.py          #   NxN grid scalability test
├── multihop.py             #   Multi-hop DV routing test runner
├── routing.py              #   Routing-only traffic measurement
├── onestep_comparison.py   #   One-step vs two-step routing comparison
├── churn.py                #   Unified churn driver (grid + conf topologies)
└── churn_sprint.py         #   Sprint churn wrapper (backward compat)
experiments/prefix_scale/plot.py  # Prefix-scaling overhead plots
experiments/                # Experiment-specific scenarios, queues, and plots
deps/                       # Built dependencies (gitignored)
experiments/prefix_scale/results/  # Experiment outputs (gitignored)
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

### Scalability CSV

Both emu and sim produce identical CSV columns:

```csv
grid_size,num_nodes,num_links,trial,convergence_s,transfer_ok,avg_mem_kb,total_packets,total_bytes,dv_packets,dv_bytes,user_packets,user_bytes
```

The `dv_*` columns cover DV advertisements + prefix sync. The `user_*` columns
cover application Interests and Data. All byte counts are at the NDNLPv2 wire
level (excluding L2 headers) so emu and sim are directly comparable.

### Churn / Routing Comparison CSV

The churn and one-step comparison scenarios produce a classified-traffic schema:

```csv
topology,grid_size,num_nodes,num_links,trial,mode,num_prefixes,window_s,convergence_s,phase,dv_advert_pkts,dv_advert_bytes,pfxsync_pkts,pfxsync_bytes,mgmt_pkts,mgmt_bytes,total_routing_pkts,total_routing_bytes
```

- `topology`: `"grid"` or a named topology (e.g. `"sprint"`)
- `mode`: `"baseline"`, `"two_step"`, or `"one_step"`
- `phase`: `"convergence"` or `"churn"`
- Traffic is split into DV advertisements, PrefixSync, and management categories

---

## Architecture Notes

### Emulation (Mini-NDN)

Each Mininet host runs a real NDNd process. Traffic is captured on virtual
interfaces using `ndnd-traffic` (a custom CLI tool built from NDNd), which
reads raw UDP payloads and classifies NDN packets by TLV type and name
prefix. The capture window is filtered to `[0, window_s]` to match the
simulation duration.

### Simulation (ndndSIM)

Each ns-3 node runs a real NDNd `fw.Thread` (FIB, PIT, CS) bridged via CGo.
The `NdndLinkTracer` classifies L2 frames by NDN packet type at the MAC layer.
An `NdnPayloadTag` marks the LP-level payload start so byte counts exclude
Ethernet/PPP headers — matching the emu's UDP payload counting.

The link tracer supports two modes:
- **Interval-sampled** (default): aggregates counters over configurable periods
- **Per-packet**: logs every packet with exact ns-3 timestamp, category, and size

DV routing uses the same Go DV protocol with SVS v3 sync. Ed25519 trust
(root key + per-node certificates) is set up automatically by the Go
`SimTrust` module, producing the same signing overhead as real deployments.

Routing convergence is measured event-driven via `RouterReachableEvent` in the
Go DV code — span from the first event to the event completing all FIBs.
No probe prefix or app traffic is needed.

See the [ndndSIM README](https://github.com/markverick/ndndSIM) for the full
simulation API including stack helpers, tracers, and DV routing configuration.

---

## Links

- [NDNd](https://github.com/named-data/ndnd) — upstream forwarder
- [NDNd fork](https://github.com/markverick/ndnd) — fork with `sim/` package for ndndSIM
- [ndndSIM](https://github.com/markverick/ndndSIM) — ns-3 contrib module
- [Mini-NDN](https://github.com/named-data/mini-ndn) — Mininet-based NDN emulator
- [ns-3](https://www.nsnam.org/) — discrete-event network simulator
