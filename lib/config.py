"""
Scenario configuration loader.

Loads experiment parameters from a JSON config file so that paper
scenarios are fully reproducible with a single version-controlled file.

Usage:
    ./run.sh sim scalability --config scenarios/paper.json
    sudo ./run.sh emu scalability --config scenarios/paper.json

Config file format -- see scenarios/ for examples.
"""

import json
import os


# All recognised keys with their types and defaults.
# Keys not in this table are silently ignored (forward-compat).
_SCHEMA = {
    # Topology
    "topology":       (str,   "grid"),   # "grid" or a KNOWN_TOPOLOGIES key
    "grids":          (list,  [2, 3, 4, 5]),
    "delay_ms":       (int,   10),
    "bandwidth_mbps": (int,   10),

    # Experiment
    "trials":    (int,   1),
    # window_s: total observation time for both sim and emu.
    # Sim runs for this many seconds; emu waits this long from DV start.
    "window_s":  (float, 60.0),

    # DV protocol tuning
    "advertise_interval":    (int, 0),   # 0 = use Go default
    "router_dead_interval":  (int, 0),   # 0 = use Go default

    # One-step vs two-step routing
    "one_step":       (bool,  False),     # True = prefixes in DV adverts (no PrefixSync)
    "num_prefixes":   (int,   0),         # synthetic prefixes per node (routing-only)
    "prefix_sync_delay": (int, 0),        # ms to delay PrefixSync SVS start (0 = immediate)
    "prefix_snap_threshold": (int, 0),    # 0 = use Go default; positive overrides PrefixSync snapshot threshold
    "disable_prefix_snap": (bool, True),  # True = disable PrefixSync snapshots entirely (default)

    # Churn mode
    "churn_mode":            (str,   "fixed"),   # "fixed" or "random"
    "churn_seed":            (int,   42),        # RNG seed for random churn
    "churn_num_cycles":      (int,   3),         # fail/recover cycles in random mode
    "churn_interval":        (float, 5.0),       # mean inter-cycle gap (s), exponential
    "churn_recovery_delay":  (float, 3.0),       # mean recovery time (s), exponential
    "churn_prefix_rate":     (float, 0.0),       # independent prefix churn rate (events/s); 0 = coupled to link events
    "per_prefix_rate":       (float, 0.0),       # per-prefix churn rate (events/s/prefix) for prefix_scaling mode
    "prefix_counts":         (list,  []),         # list of num_prefixes to sweep (prefix_scaling mode); empty = use num_prefixes
    "modes":                 (list,  []),         # routing modes to run; empty = ["baseline","two_step","one_step"]

    # Churn-after-convergence mode
    "churn_after_convergence": (bool, False),    # True = churn starts right after DV convergence + margin
    "convergence_margin_s":    (float, 10.0),    # seconds to wait after convergence before churn
    "churn_duration_s":        (float, 0.0),     # churn phase length (s); 0 = window_s/2 (legacy)
    "phase2_start_s":          (float, 0.0),     # fixed churn start time (s); 0 = window_s/2 (legacy)

    # Runtime
    "cores":          (int,   0),        # 0 = all available
}


def load_config(path):
    """Load and validate a JSON scenario config.

    Returns a dict with all keys from _SCHEMA, filled with defaults
    for any keys not present in the file.
    """
    with open(path) as f:
        raw = json.load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config must be a JSON object, got {type(raw).__name__}")

    cfg = {}
    for key, (typ, default) in _SCHEMA.items():
        val = raw.get(key, default)
        if not isinstance(val, typ) and not (typ is float and isinstance(val, int)):
            raise ValueError(
                f"Config key '{key}': expected {typ.__name__}, got {type(val).__name__}"
            )
        cfg[key] = typ(val) if not isinstance(val, typ) else val
    return cfg


def dv_config_from(cfg):
    """Extract the dv_config dict (for passing to run_scenario / dv_util).

    Returns None if no DV overrides are set (both intervals == 0).
    """
    dv = {}
    if cfg.get("advertise_interval"):
        dv["advertise_interval"] = cfg["advertise_interval"]
    if cfg.get("router_dead_interval"):
        dv["router_dead_interval"] = cfg["router_dead_interval"]
    if cfg.get("one_step"):
        dv["one_step"] = True
    if cfg.get("prefix_sync_delay"):
        dv["prefix_sync_delay"] = cfg["prefix_sync_delay"]
    if cfg.get("prefix_snap_threshold"):
        dv["prefix_snap_threshold"] = cfg["prefix_snap_threshold"]
    if cfg.get("disable_prefix_snap"):
        dv["disable_prefix_snap"] = True
    return dv or None


def add_config_arg(parser):
    """Add --config argument to an argparse parser."""
    parser.add_argument("--config", default=None,
                        help="JSON config file (overrides other CLI flags)")


def add_grid_scenario_args(parser, default_out, default_window=60.0):
    """Add the standard CLI arguments shared by all grid-scenario runners.

    Covers topology, experiment, DV tuning, and config-file override.
    Individual runners may add extra args (e.g. --ns3-dir) after calling this.
    """
    parser.add_argument("--grids", nargs="+", type=int, default=[2, 3, 4, 5],
                        help="Grid sizes to test (default: 2 3 4 5)")
    parser.add_argument("--delay", type=int, default=10,
                        help="Per-link delay in ms (default: 10)")
    parser.add_argument("--bw", type=int, default=10,
                        help="Per-link bandwidth in Mbps (default: 10)")
    parser.add_argument("--window", type=float, default=default_window,
                        help=f"Observation window in seconds (default: {default_window})")
    parser.add_argument("--out", default=default_out,
                        help=f"Output directory (default: {default_out})")
    parser.add_argument("--cores", type=int, default=0,
                        help="Parallel build / CPU cores (0 = all)")
    parser.add_argument("--trials", type=int, default=1,
                        help="Repetitions per grid size (default: 1)")
    parser.add_argument("--adv-interval", type=int, default=0,
                        help="DV advertisement interval in ms (0 = default)")
    parser.add_argument("--dead-interval", type=int, default=0,
                        help="DV router dead interval in ms (0 = default)")
    add_config_arg(parser)


def apply_config_overrides(args):
    """Apply --config file overrides to parsed args.

    Normalises delay and bandwidth to raw integers (ms, Mbps).
    Returns (delay_ms, bw_mbps, dv_config) where dv_config is dict | None.
    """
    if args.config:
        cfg = load_config(args.config)
        args.grids = cfg["grids"]
        args.trials = cfg["trials"]
        args.cores = cfg["cores"]
        args.window = cfg["window_s"]
        return cfg["delay_ms"], cfg["bandwidth_mbps"], dv_config_from(cfg)
    dv = {}
    if args.adv_interval:
        dv["advertise_interval"] = args.adv_interval
    if args.dead_interval:
        dv["router_dead_interval"] = args.dead_interval
    return args.delay, args.bw, dv or None
