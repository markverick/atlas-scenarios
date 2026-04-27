# Codex Changelog

This document summarizes the code changes currently present in the
`atlas-scenarios` working tree as of 2026-04-27, with the specific reasoning
behind each change.

## 1. Emulation prefix-scale now exports real table metrics

Files:
- `emu/prefix_scale.py`
- `lib/table_metrics.py`
- `tests/test_table_metrics.py`
- `README.md`

Change:
- The emulation path now samples live forwarder state from each Mini-NDN node
  using `ndnd fw fib-list` and, in twophase mode, `ndnd fw pet-list`.
- It writes `node_table_metrics.csv` and `role_table_summary.csv` in the same
  schema used by the simulation plot pipeline.
- `sim/prefix_scale.py` now imports shared table-metric helpers instead of
  carrying its own copy of the parsing and role-summary logic.

Reasoning:
- Before this change, `emu/prefix_scale.py` only emitted a header-only
  `role_table_summary.csv`. The plotter expected that file to contain actual
  per-role table counts, so the forwarding-table figure could be generated from
  simulation results but not from emulation results.
- The intent of the figure is to compare role-aware forwarding state. Writing
  a placeholder CSV on the emulation side hid the fact that the necessary data
  was never collected.
- Moving parsing and aggregation into `lib/table_metrics.py` prevents schema
  drift between emulation and simulation. If both pipelines produce the same
  columns and summarize with the same code, the plots become directly
  comparable.
- The tests in `tests/test_table_metrics.py` were added to lock down the
  parsing contract for `fib-list` / `pet-list` output and to ensure failures
  are reported clearly instead of silently producing wrong counts.
- `announce_prefixes()` in `emu/prefix_scale.py` now redirects background
  `ndnd put --expose` output to `/dev/null` because stray stdout from those
  background processes could contaminate later command output and break the
  table-status parsers.

## 2. Simulation prefix-scale was refactored to share the table-metric code

Files:
- `sim/prefix_scale.py`
- `lib/table_metrics.py`

Change:
- Removed the simulation-local copies of `NODE_FIELDNAMES`,
  `ROLE_FIELDNAMES`, `parse_table_trace()`, and
  `summarize_role_table_metrics()`.
- Replaced them with imports from `lib/table_metrics.py`.

Reasoning:
- The simulation path already knew how to parse table traces and summarize them
  by role. The emulation work needed the exact same output format.
- Duplicating that logic in two places would make the repo fragile: a small
  schema edit in one file could silently break cross-mode plotting.
- Centralizing the logic ensures that any future plot or metric change is
  applied to both modes together.

## 3. ndndSIM patching is now persistent across fresh setups and rebuilds

Files:
- `sim/apply_ndndsim_patches.sh`
- `sim/patches/ndndsim-register-route-phase.patch`
- `setup.sh`
- `run.sh`

Change:
- Added an idempotent patch-application script for the local ndndSIM checkout.
- `setup.sh` applies the patch after cloning `deps/ns-3/contrib/ndndSIM`.
- `run.sh` reapplies the patch before simulation builds.

Reasoning:
- The actual simulation behavior fix lives in ndndSIM overlay sources under
  `deps/ns-3/contrib/ndndSIM/go/overlay/...`, which are not tracked by the
  atlas repo itself.
- A fresh `setup.sh` run reclones ndndSIM, and each ndndSIM Go build rewrites
  `.transformed-ndnd-{twophase,onephase}` from the overlay sources. That means
  a local edit inside `deps/` is ephemeral unless the atlas repo replays it.
- The new script makes the workflow reproducible. Without it, the repo would
  appear fixed only in one workspace but would regress on the next clean setup.
- The script intentionally fails loudly if the patch no longer applies. That is
  better than silently continuing with stale behavior and producing misleading
  results.

## 4. Twophase simulation producer registration now matches production semantics

Files:
- `sim/patches/ndndsim-register-route-phase.patch`
- Patched ndndSIM overlay files under `deps/ns-3/contrib/ndndSIM/go/overlay/...`

Key patched ndndSIM files:
- `go/overlay/sim/engine.go`
- `go/overlay/sim/cgo_export.go`
- `go/overlay/sim/engine_test.go`
- `go/overlay/sim/consumer_test.go`
- `go/overlay/sim/dv_integration_test.go`
- `go/overlay/sim/forwarder.go`
- `model/ndndsim-stack.h`

Change:
- In twophase simulation, `SimEngine.RegisterRoute()` now uses PET management
  commands (`pet add-nexthop` / `pet remove-nexthop`) instead of routing local
  producer registration through `AddDirectRoute()`.
- In onephase simulation, `RegisterRoute()` still falls back to direct FIB
  route injection because onephase does not expose the same PET management path.
- Added regression coverage that checks twophase `RegisterRoute()` does not add
  a direct FIB nexthop and does add a PET nexthop.
- Updated producer-oriented tests to use `RegisterRoute()` /
  `UnregisterRoute()` instead of hand-wired `AddRoute(appFace)` shortcuts.
- Clarified comments around `AddRoute()` / `AddDirectRoute()` to explain that
  they remain simulation convenience APIs for manual forwarding injection.

Reasoning:
- The root bug was a semantic mismatch between production twophase ndnd and the
  ndndSIM harness. Production twophase `BasicEngine.RegisterRoute()` registers
  a local producer prefix in PET, not in FIB.
- The original simulation path reused `AddDirectRoute()`, which mirrors a
  manual route into FIB and PET. That made twophase simulation over-count FIB
  growth for local producer prefixes.
- The visible symptom was that twophase simulation showed edge-node FIB growth
  with announced prefix count even when emulation and production semantics
  indicated those app prefixes should live in PET.
- The fix was intentionally scoped to `RegisterRoute()` rather than globally
  changing `AddDirectRoute()`. During validation, making `AddDirectRoute()`
  FIB-only broke older hand-wired sim tests and examples that rely on it as a
  manual shortcut to “make this prefix reachable”.
- The repo now preserves that convenience API but makes producer registration
  phase-correct. In other words:
  `RegisterRoute()` models producer semantics, while `AddRoute()` /
  `AddDirectRoute()` remain explicit simulation shortcuts.

## 5. README was updated to document the new emulation outputs

Files:
- `README.md`

Change:
- Added a note explaining that `emu/prefix_scale.py` now emits
  `node_table_metrics.csv` and `role_table_summary.csv`.

Reasoning:
- The repo previously documented traffic metrics for emulation but not the new
  table-metric outputs needed for the prefix-scale plots.
- Since the emulation path now produces plot-ready role summaries, the README
  should make that behavior discoverable instead of leaving it as an implicit
  implementation detail.

## Verification notes

Files / workflows exercised while validating the changes:
- `python3 -m py_compile` on the Python changes
- Twophase ndndSIM Go overlay rebuild and sim tests
- Onephase ndndSIM Go overlay rebuild and sim tests
- Emulation prefix-scale smoke run with live table collection
- Simulation prefix-scale rerun and figure regeneration after the
  `RegisterRoute()` fix

Why this matters:
- The table-metric work changes output shape and plot inputs, so parser checks
  and real runs were needed.
- The ndndSIM route-registration fix changes forwarding semantics, so both
  twophase and onephase transformed builds were rebuilt and tested to ensure the
  change did not remain only in source comments or a stale transformed tree.
