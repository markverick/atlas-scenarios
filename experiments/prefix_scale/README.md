# Prefix Scalability Experiments

This directory contains the active, reusable experiment definitions for
prefix-scalability studies.

Structure:

- `scenarios/` — checked-in scenario inputs for this experiment
- `queues/` — queue definitions that orchestrate sim/emu runs
- `docs/` — notes or follow-up analysis specific to this experiment family

Primary queue:

```bash
sudo ./jobs.sh start --fresh prefix_scale/sprint_twostep_0to50
```

Testing queue:

```bash
sudo ./jobs.sh start --fresh prefix_scale/sprint_twostep_1prefix_test
```

Outputs:

- `experiments/prefix_scale/results/sprint_twostep_0to50/<timestamp>/sim`
- `experiments/prefix_scale/results/sprint_twostep_0to50/<timestamp>/emu`
- `experiments/prefix_scale/results/sprint_twostep_0to50/<timestamp>/compare`
- `experiments/prefix_scale/results/sprint_twostep_1prefix_test/<timestamp>/sim`
- `experiments/prefix_scale/results/sprint_twostep_1prefix_test/<timestamp>/emu`
- `experiments/prefix_scale/results/sprint_twostep_1prefix_test/<timestamp>/compare`

Useful CLI shortcuts:

```bash
./jobs.sh list
./jobs.sh                        # numbered interactive menu
./jobs.sh start                  # interactive queue picker
./jobs.sh status prefix_scale/sprint_twostep_0to50
./jobs.sh status prefix_scale/sprint_twostep_0to50 --watch
./jobs.sh running
```

`./jobs.sh` auto-prompts for sudo on commands that need elevated privileges.

The active scenarios in this module explicitly disable PrefixSync snapshots.
The queue definitions are discovered only from `experiments/<name>/queues/*.json`.