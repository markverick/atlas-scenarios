# Prefix Scalability Experiments

This directory contains the active, reusable experiment definitions for
prefix-scalability studies.

Structure:

- `scenarios/` — checked-in scenario inputs for this experiment
- `queues/` — queue definitions that orchestrate sim/emu runs
- `docs/` — notes or follow-up analysis specific to this experiment family

Primary queue:

```bash
sudo ./jobs.sh start --fresh prefix_scale/sprint_bothstep_0to50
```

Testing queue:

```bash
sudo ./jobs.sh start --fresh prefix_scale/3x3_prefix_churn_compare_1prefix_test
sudo ./jobs.sh start --fresh prefix_scale/sprint_bothstep_0to5
sudo ./jobs.sh start --fresh prefix_scale/sprint_bothstep_sim_p50
sudo ./jobs.sh start --fresh prefix_scale/sprint_bothstep_emu_p50
```

Focused single-point scenarios:

- `experiments/prefix_scale/scenarios/sprint_bothstep_emu_p50.json`
- `experiments/prefix_scale/scenarios/sprint_bothstep_sim_p50.json`

Outputs:

- `experiments/prefix_scale/results/sprint_bothstep_0to50/<timestamp>/sim`
- `experiments/prefix_scale/results/sprint_bothstep_0to50/<timestamp>/emu`
- `experiments/prefix_scale/results/sprint_bothstep_0to50/<timestamp>/compare`
- `experiments/prefix_scale/results/3x3_prefix_churn_compare_1prefix_test/<timestamp>/sim`
- `experiments/prefix_scale/results/3x3_prefix_churn_compare_1prefix_test/<timestamp>/emu`
- `experiments/prefix_scale/results/3x3_prefix_churn_compare_1prefix_test/<timestamp>/compare`
- `experiments/prefix_scale/results/sprint_bothstep_0to5/<timestamp>/sim`
- `experiments/prefix_scale/results/sprint_bothstep_0to5/<timestamp>/emu`
- `experiments/prefix_scale/results/sprint_bothstep_0to5/<timestamp>/compare`
- `experiments/prefix_scale/results/sprint_bothstep_sim_p50/<timestamp>/sim`
- `experiments/prefix_scale/results/sprint_bothstep_emu_p50/<timestamp>/emu`
- `experiments/prefix_scale/results/core_edge_bothphase_0to5_tables/<timestamp>/onephase`
- `experiments/prefix_scale/results/core_edge_bothphase_0to5_tables/<timestamp>/twophase`
- `experiments/prefix_scale/results/core_edge_bothphase_0to5_tables/<timestamp>/plots`
- `experiments/prefix_scale/results/core_edge_bothphase_0to5_tables/<timestamp>/summary.md`
- `experiments/prefix_scale/results/rocketfuel_2914_bothphase_0to500_tables/<timestamp>/onephase`
- `experiments/prefix_scale/results/rocketfuel_2914_bothphase_0to500_tables/<timestamp>/twophase`
- `experiments/prefix_scale/results/rocketfuel_2914_bothphase_0to500_tables/<timestamp>/plots`
- `experiments/prefix_scale/results/rocketfuel_2914_bothphase_0to500_tables/<timestamp>/summary.md`
- `experiments/prefix_scale/results/rocketfuel_4755_bothphase_0to500_tables/<timestamp>/onephase`
- `experiments/prefix_scale/results/rocketfuel_4755_bothphase_0to500_tables/<timestamp>/twophase`
- `experiments/prefix_scale/results/rocketfuel_4755_bothphase_0to500_tables/<timestamp>/plots`
- `experiments/prefix_scale/results/rocketfuel_4755_bothphase_0to500_tables/<timestamp>/summary.md`

Useful CLI shortcuts:

```bash
./jobs.sh list
./jobs.sh                        # numbered interactive menu
./jobs.sh start                  # interactive queue picker
./jobs.sh status prefix_scale/sprint_bothstep_0to50
./jobs.sh status prefix_scale/sprint_bothstep_0to50 --watch
./jobs.sh running
```

Core/edge table-study queue:

```bash
sudo ./jobs.sh start --fresh prefix_scale/core_edge_bothphase_0to5_tables
```

That queue now renders the plot set and `summary.md` automatically after both sim phases finish.
Its twophase run now sets `--core-disable-prefix-egress-replication`, so
transit/core routers keep remote prefix-egress state out of PET while edge
routers retain the default behavior.

Wider-step core/edge table-study queue:

```bash
sudo ./jobs.sh start --fresh prefix_scale/core_edge_bothphase_0to50_by10_tables
```

This variant runs the same core/edge twophase-versus-onephase table study, but
at prefix counts `0 10 20 30 40 50`.

Large Rocketfuel queue:

```bash
sudo ./jobs.sh start --fresh prefix_scale/rocketfuel_2914_bothphase_0to500_tables
```

This queue uses the public Rocketfuel AS 2914 `cch` map fetched into
`experiments/prefix_scale/topologies/rocketfuel_2914.cch`. The simulation uses
the largest connected `r0` component, which yields 960 routers total with a
near-even core/edge split (`bb` as core, non-`bb` as edge). The queue renders
the topology figure, the role-based comparison plots, and `summary.md`
automatically after both phases finish.

Rocketfuel sample queue:

```bash
sudo ./jobs.sh start --fresh prefix_scale/rocketfuel_4755_bothphase_0to500_tables
```

This queue uses the checked-in ns-3 Rocketfuel `cch` sample for AS 4755. The
role split is derived from the original file's `bb` flag, so core means
backbone (`bb`) and edge means non-backbone among connected radius-0 nodes.
In the workspace sample that yields one edge router after dropping one
isolated radius-0 node with no internal links. The queue renders the topology
figure, the role-based comparison plots, and `summary.md` automatically after
both phases finish.

Role-aware DV config is available on `sim prefix_scale` through
`--core-dv-config-json` and `--edge-dv-config-json`. The built-in queue
definitions use `--core-disable-prefix-egress-replication` on twophase runs,
which maps to `prefix_egre_state_replicate=false` only on core nodes.

`./jobs.sh` auto-prompts for sudo on commands that need elevated privileges.

The active scenarios in this module explicitly disable PrefixSync snapshots.
The queue definitions are discovered only from `experiments/<name>/queues/*.json`.