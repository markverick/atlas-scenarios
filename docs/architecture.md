# atlas-scenarios / ndndSIM Architecture Notes

This file is the authoritative reference for AI assistants and contributors.
Keep it in sync with the code — update it when behaviour changes.

---

## BUILD SYSTEM

### File mutability rules (critical)
- `.transformed-ndnd-twophase/` and `.transformed-ndnd-onephase/` are **GENERATED** — wiped every build. NEVER edit them.
- To change behaviour: edit `transform/rules.go`, `transform/rewrite.go`, or `transform/inject.go`.
- To add net-new files (not patching upstream): put them in `overlay/` (shared) or `overlay-twophase/` / `overlay-onephase/`.
- Full workflow doc: `deps/ns-3/contrib/ndndSIM/go/transform/README.md`

### Adding a transform rule requires EXACTLY THREE edits (missing one is the most common failure)
1. `inject.go` — snippet constant (only if injecting new Go declarations)
2. `rewrite.go` — (a) iota constant, (b) wire to target file in each phase block, (c) dispatch `case`
3. `rules.go` — `applyXxx(file *ast.File) bool` implementation

### Rebuild commands by change type
| Change | Command |
|---|---|
| `transform/*.go` or `overlay/**` | `cmake --build deps/ns-3/cmake-cache --target ndndSIM` |
| C++ ns-3 only | `cmake --build deps/ns-3/cmake-cache` |
| No binary change | `./run.sh sim --no-build …` |
| Full clean build | `./run.sh build` |

### AST insertion pitfall
When inserting a statement before the final `return` in a function body, use:
```go
fd.Body.List = append(fd.Body.List[:n-1], newStmt, fd.Body.List[n-1])
```
NOT `append(fd.Body.List, newStmt)` — that places it **after** the return → `missing return` compile error.

### Jobs CLI (queue runner)
- Run queue: `python3 -m jobs.cli run prefix_scale/<queue_name>`
- Reset queue: `python3 -m jobs.cli reset prefix_scale/<queue_name>`
- Queue files: `experiments/prefix_scale/queues/*.json`

---

## DATA STRUCTURES

All tables are per-node. The two phases have fundamentally different prefix-forwarding architectures; do not conflate them.

---

### Onephase (`ndnd@main`)

Prefixes are installed in the forwarder FIB directly, alongside router entries.

#### Forwarder tables
| Table | What it stores |
|---|---|
| `forwarder_rib` | NFD's Routing Information Base. One entry per distinct registered prefix; each entry holds one or more `Route` records (face ID, origin, cost). Fed by nfdc `rib register` commands. Asynchronously installs into FIB. |
| `forwarder_fib` | LPM forwarding table. Holds entries for both router names and application prefixes (e.g. `/data/eX/pfxN`). **Convergence metric for onephase**: `NdndSimGetConvergenceMetric()` counts FIB entries on all nodes. |

#### DV tables
| Table | What it stores |
|---|---|
| `dv_rib` | Distance-vector RIB: one entry per reachable remote router, holding (router-name, nexthop-face, cost). Source of truth for which nexthop faces reach which router. |
| `dv_neighbors` | Directly connected DV peers. One entry per adjacent face that has completed the DV hello exchange. |
| `dv_prefix_table` | Tracks (prefix, announcing-router, cost) learned from PES SVS publications. `dv.pfx.EntryCount()`. |

#### Onephase prefix update chain
```
PES SVS publication received
  → dv_prefix_table update
  → updateFib()
    → nfdc rib register (router names AND all application prefixes)
      → forwarder_rib
        → async FIB install → forwarder_fib  ← convergence metric
```

#### Onephase router update chain
```
DV advertisement received → updateRib() → updateFib()
  → nfdc rib register (router names + prefix-sync-group prefix)
    → forwarder_rib → async FIB install → forwarder_fib
```

---

### Twophase (`ndnd@dv2`)

Application prefixes bypass the forwarder RIB/FIB entirely. They are tracked in a dedicated Prefix Egress Table (PET) updated synchronously by DV prefix events.

#### Forwarder tables
| Table | What it stores |
|---|---|
| `forwarder_rib` | NFD's Routing Information Base (same structure as onephase). Only holds router-name entries (not application prefixes). |
| `forwarder_fib` | LPM forwarding table. Only holds router-name entries — no per-prefix application entries. Not used as a convergence metric in twophase. |
| `forwarder_pet` | Prefix Egress Table. Maps (prefix, egress-router-name) → nexthop face IDs. Updated **synchronously** by DV prefix events (no nfdc, no async step). **Convergence metric for twophase.** Edge nodes get ~p entries (all global prefixes). Core nodes also replicate PES by default; set `--core-disable-prefix-egress-replication` (`prefix_egre_state_replicate: False`) to suppress replication on core nodes. |

#### DV tables
| Table | What it stores |
|---|---|
| `dv_rib` | Distance-vector RIB (same structure as onephase). Drives router-name FIB entries only. |
| `dv_neighbors` | Directly connected DV peers (same as onephase). |
| `dv_prefix_egress_state` | Tracks (prefix, announcing-edge-router) pairs learned from PES SVS. One entry per (prefix, edge-router) pair. `dv.pfx.EntryCount()`. Synchronously updates `forwarder_pet` on change. |

#### Twophase prefix update chain
```
PES SVS publication received
  → dv_prefix_egress_state update
  → forwarder_pet update (synchronous, no nfdc, no RIB step)  ← convergence metric
```

#### Twophase router update chain (same as onephase but router names only)
```
DV advertisement received → updateRib() → updateFib()
  → nfdc rib register (router names only, no application prefixes)
    → forwarder_rib → async FIB install → forwarder_fib
```

---

### Key concepts

**RIB** (Routing Information Base): the forwarder's route registration table, managed by nfdc. `GetAllEntries()` returns one `RibEntry` per distinct prefix that has at least one registered `Route` record (face ID, origin, cost). Asynchronously installs into FIB. Distinct from the DV RIB (`dv_rib`).

**DV** (Distance Vector): the routing protocol. Routers exchange **distance-vector advertisements** using SVS-format state-vector sync Interests (carrying a sequence number) and signed NDN Data objects with router reachability info. Do NOT call these LSAs — that is link-state (OSPF) terminology. Builds `dv_rib` in both phases.

**DV advertisement sync** (both phases): implemented by `advertModule` in `advert_sync.go`. Uses SVS state-vector Interests manually (not via a library `SvSync` object). Driven by the heartbeat timer — in simulation, `RunHeartbeat()` is called by DES events scheduled in `overlay/sim/dv.go`. `dv.client` (started in `Init()`) is an NDN **object fetch client** for retrieving advertisement Data objects, not an SVS instance.

**SVS** (State Vector Sync): pub/sub sync library. Used by `pfxSvs` for prefix dissemination in both phases. Not used directly for DV advertisements.

**PES SVS** (`pfxSvs`): a `SvSync` instance per node that synchronises prefix announcements across all nodes. Present in both phases; the consequence of delivery differs:
- **Onephase**: updates `dv_prefix_table` → `updateFib()` → FIB entries for application prefixes
- **Twophase**: updates `dv_prefix_egress_state` → `forwarder_pet` (synchronous, no FIB involvement)

**Deferred start**: `pfxSvs` is **not started at `Init()`**. It starts only after DV routing converges: `runConvergenceHook` → `startPfxOnce` → `pfxSvs.Start()` (after one `AdvertisementSyncInterval` debounce). Starting it too early causes broadcast storms over BroadcastStrategy before PET/FIB nexthops exist.

**PES** (Prefix Egress State): the conceptual layer that propagates "edge node eX announces prefix P" to all nodes via `pfxSvs`.

**PET** (Prefix Egress Table): `forwarder_pet`, twophase only. The forwarder's per-prefix forwarding table scoped to egress routes. A packet matching a PET entry is forwarded toward the announcing edge router.

---

## SIMULATION INTERNALS

### Entry point: `Init()`, not `Start()`
- `overlay/sim/dv.go:114` calls `sd.router.Init()`, never `dv.Router.Start()`
- `Init()` starts `dv.client` (object fetch) and registers Interest handlers, but does NOT start the nfdc goroutine
- `Start()` contains `_ndndsim.Go(func() { dv.nfdc.Start() })` but is unused in sim

### nfdc async channel is dead in simulation (two independent reasons)
1. `nfdc.Start()` (the channel consumer) is never called — `Init()` is used instead
2. `nfdc.Exec()` → `simExec()` checks `IsSynchronous()==true` and calls `engine.ExecMgmtCmd()` directly, never sending to the channel
- All FIB updates execute synchronously within the calling DES event

### DES synchronous mode
- Every node: `hooks.Synchronous = true` (`node.go:100`, `dv.go:78`)
- `_ndndsim.Go(f)` → `clock.Schedule(0, f)` — converts goroutine to DES event at delay=0
- `_ndndsim.GoLong(f)` → panics in synchronous mode (safety net)
- `_ndndsim.Sleep(d)` → no-op in synchronous mode

### Two ndnd variants
- `onephase`: `ndnd@main` commit `51774b8` — prefixes tracked in `forwarder_fib`. FIB installed via nfdc RIB manager.
- `twophase`: `ndnd@dv2` commit `bbe06d2` — prefixes tracked in `forwarder_pet` and `dv_prefix_egress_state`. PET updated synchronously with DV prefix events.
- Phase auto-detected in `NdndSimGetConvergenceMetric()` by checking if `forwarder_pet` appears in `SimTableMetrics()`

---

## CONVERGENCE CHECKER (`atlas-prefix-scale-scenario.cc`)

All prefix-scale runs are fresh: each prefix count starts from a clean topology without any pre-loaded state.

### Fresh run (`stableWindow > 0`)
- DV routing converges from scratch.
- Once DV is converged: all prefixes are announced simultaneously (or staggered by `--announce-gap`).
- **SVS silence checker**: stops when `(now - ref) >= silenceNs` where `ref = lastSvsDeliveryNs` if any SVS delivery has occurred, otherwise `ref = startNs` (sim time when the checker was installed).
  - p > 0: `ref` advances with each SVS delivery, so the checker stops only after the network has been idle for `stableWindow` seconds following the last delivery.
  - p = 0: no prefixes announced → no SVS deliveries → `ref = startNs` → checker fires exactly `stableWindow` seconds after installation.
- Default `stableWindow` is auto-computed or set by `--conv-window` in queue config. Overridable with `--conv-window`.

### `stableWindow <= 0`
No event-driven stop; simulation runs to hard `--simTime` ceiling.

---

## Key commits
- ndndSIM `7e000e0`: added `NdndSimGetConvergenceMetric()` (phase-aware, sums forwarder_pet or forwarder_fib)
- atlas-scenarios `eee9570`: twophase uses event-driven stop; onephase uses hard ceiling (stableWindow=0)

## Terminology precision
- "fresh run succeeds" is WRONG — fresh p500 runs also have anomalies (14 nodes at 491 with --conv-window 3.0)
- "Success" = 100% correctness (all 172 nodes, all 500 prefixes). Do not say a run "succeeds" unless verified.
- Do not say "LSA" for DV advertisements — that is link-state terminology.
