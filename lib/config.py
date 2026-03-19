"""
Scenario configuration loader.

Loads experiment parameters from a JSON config file so that paper
scenarios are fully reproducible with a single version-controlled file.

Usage:
    ./run.sh sim scalability --config scenarios/paper.json
    sudo ./run.sh emu scalability --config scenarios/paper.json

Config file format — see scenarios/ for examples.
"""

import json
import os


# All recognised keys with their types and defaults.
# Keys not in this table are silently ignored (forward-compat).
_SCHEMA = {
    # Topology
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
    return dv or None


def add_config_arg(parser):
    """Add --config argument to an argparse parser."""
    parser.add_argument(
        "--config", metavar="FILE",
        help="JSON scenario config file (overrides other CLI flags)",
    )
