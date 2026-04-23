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

`./jobs.sh` auto-prompts for sudo on commands that need elevated privileges.

The active scenarios in this module explicitly disable PrefixSync snapshots.
The queue definitions are discovered only from `experiments/<name>/queues/*.json`.