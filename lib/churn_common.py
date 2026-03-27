"""
Shared constants and helpers for churn scenario drivers (sim and emu).

All topology-specific knowledge (churn targets, conf file paths) lives here
so that adding a new topology requires only:
  1. An entry in KNOWN_TOPOLOGIES below
  2. A JSON config file in scenarios/
"""

import csv
import os
import sys

# --- Shared constants ---

FIELDNAMES = [
    "topology", "grid_size", "num_nodes", "num_links", "trial", "mode",
    "num_prefixes", "window_s", "convergence_s", "phase",
    "dv_advert_pkts", "dv_advert_bytes",
    "pfxsync_pkts", "pfxsync_bytes",
    "mgmt_pkts", "mgmt_bytes",
    "total_routing_pkts", "total_routing_bytes",
]

CATEGORIES = ["DvAdvert", "PrefixSync", "Mgmt",
              "UserInterest", "UserData", "Other"]

ROUTING_CATS = ("DvAdvert", "PrefixSync", "Mgmt")

# --- Known non-grid topology definitions ---
# To add a topology: add an entry here, then create a JSON config with
# "topology": "<name>".

_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KNOWN_TOPOLOGIES = {
    "sprint": {
        "label": "Sprint PoP",
        "conf_path": os.path.join(
            _REPO_DIR, "deps", "mini-ndn", "topologies", "sprint_pop.conf"),
        "churn_link": ("KansasCity", "Chicago"),
        "churn_node": "KansasCity",
    },
}


# --- Topology helpers ---

def topo_id(cfg):
    """Return a short topology identifier for file tags.

    Grid topologies: "3x3", "4x4", etc.  (per-grid, call with grid_size)
    Named topologies: "sprint", etc.
    """
    topo = cfg.get("topology", "grid")
    if topo == "grid":
        grids = cfg.get("grids", [])
        if len(grids) == 1:
            g = grids[0]
            return f"{g}x{g}"
        return "grid"
    return topo


def default_out_dir(cfg, runner="sim"):
    """Derive a default output directory from the config.

    Examples:
      grid [3]     → results/sim_churn_3x3
      grid [4]     → results/sim_churn_4x4
      grid [3,4]   → results/sim_churn
      sprint       → results/sim_churn_sprint
    """
    topo = cfg.get("topology", "grid")
    if topo != "grid":
        return f"results/{runner}_churn_{topo}"
    grids = cfg.get("grids", [])
    if len(grids) == 1:
        g = grids[0]
        return f"results/{runner}_churn_{g}x{g}"
    return f"results/{runner}_churn"


def grid_churn_targets(grid_size):
    """Return (link_src, link_dst, churn_node) for an NxN grid."""
    if grid_size < 2:
        return None, None, None
    return "n0_0", "n0_1", "n0_0"


# --- Churn event builder ---

def build_churn_events(num_prefixes, phase2_start, *,
                       link_src, link_dst, churn_node):
    """Build deterministic churn events for any topology.

    Events at offsets from phase2_start:
      +0.1s  link_down   link_src -- link_dst
      +2.0s  prefix_withdraw on churn_node  (if num_prefixes > 0)
      +5.1s  link_up     link_src -- link_dst
      +7.0s  prefix_announce on churn_node  (if num_prefixes > 0)
    """
    if link_src is None or link_dst is None:
        return []
    events = [
        {"time": phase2_start + 0.1, "type": "link_down",
         "src": link_src, "dst": link_dst},
        {"time": phase2_start + 5.1, "type": "link_up",
         "src": link_src, "dst": link_dst},
    ]
    if num_prefixes > 0 and churn_node:
        pfx = f"/data/{churn_node}/pfx0"
        events.append({"time": phase2_start + 2.0, "type": "prefix_withdraw",
                       "node": churn_node, "prefix": pfx})
        events.append({"time": phase2_start + 7.0, "type": "prefix_announce",
                       "node": churn_node, "prefix": pfx})
    return events


# --- Packet trace parsers ---

def parse_packet_trace_by_phase(path, phase_boundary):
    """Split per-packet CSV (sim) into convergence/churn totals."""
    result = {}
    for phase in ("convergence", "churn"):
        result[phase] = {cat: {"pkts": 0, "bytes": 0} for cat in CATEGORIES}
    if not path or not os.path.isfile(path):
        return result
    with open(path) as f:
        for row in csv.DictReader(f):
            t = float(row["Time"])
            cat = row["Category"]
            b = int(row["Bytes"])
            if cat not in result["convergence"]:
                continue
            phase = "convergence" if t < phase_boundary else "churn"
            result[phase][cat]["pkts"] += 1
            result[phase][cat]["bytes"] += b
    return result


def parse_packet_events_by_phase(events, phase_boundary):
    """Split in-memory (time, cat, bytes) events (emu) into phase totals."""
    result = {}
    for phase in ("convergence", "churn"):
        result[phase] = {cat: {"pkts": 0, "bytes": 0} for cat in CATEGORIES}
    for t_s, cat, b in events:
        if cat not in result["convergence"]:
            continue
        phase = "convergence" if t_s < phase_boundary else "churn"
        result[phase][cat]["pkts"] += 1
        result[phase][cat]["bytes"] += b
    return result


# --- Result row builder ---

def build_result_rows(phases, *, topology, grid_size, num_nodes, num_links,
                      trial, mode, num_prefixes, window_s, convergence_s):
    """Build CSV result dicts from parsed phase traffic."""
    rows = []
    for phase_name, traffic in phases.items():
        routing_pkts = sum(traffic[c]["pkts"] for c in ROUTING_CATS)
        routing_bytes = sum(traffic[c]["bytes"] for c in ROUTING_CATS)
        rows.append({
            "topology": topology,
            "grid_size": grid_size,
            "num_nodes": num_nodes,
            "num_links": num_links,
            "trial": trial,
            "mode": mode,
            "num_prefixes": num_prefixes,
            "window_s": window_s,
            "convergence_s": convergence_s,
            "phase": phase_name,
            "dv_advert_pkts": traffic["DvAdvert"]["pkts"],
            "dv_advert_bytes": traffic["DvAdvert"]["bytes"],
            "pfxsync_pkts": traffic["PrefixSync"]["pkts"],
            "pfxsync_bytes": traffic["PrefixSync"]["bytes"],
            "mgmt_pkts": traffic["Mgmt"]["pkts"],
            "mgmt_bytes": traffic["Mgmt"]["bytes"],
            "total_routing_pkts": routing_pkts,
            "total_routing_bytes": routing_bytes,
        })
    return rows


# --- File tag builder ---

def make_tag(mode, topo_id_str, num_prefixes, trial):
    """Build a filename tag for trace files.

    topo_id_str: e.g. "3x3", "4x4", "sprint".
    """
    return f"{mode}-{topo_id_str}-p{num_prefixes}-t{trial}"


# --- Auto-plot helper ---

def auto_plot(out_dir, *, sim_dir="", emu_dir=""):
    """Run plot_churn.py after a churn run.

    Derives plot output directory from out_dir:
      results/sim_churn_3x3    → results/plots_3x3
      results/sim_churn_sprint → results/plots_sprint
      results/sim_churn        → results/plots
    """
    import subprocess
    script = os.path.join(_REPO_DIR, "plot_churn.py")
    if not os.path.isfile(script):
        return
    base = os.path.basename(os.path.normpath(out_dir))
    suffix = base
    for prefix in ("sim_churn", "emu_churn"):
        if suffix.startswith(prefix):
            suffix = suffix[len(prefix):].lstrip("_")
            break
    parent = os.path.dirname(out_dir) or "results"
    plot_out = os.path.join(parent, f"plots_{suffix}" if suffix else "plots")
    subprocess.run([sys.executable, script,
                    "--sim", sim_dir or "",
                    "--emu", emu_dir or "",
                    "--out", plot_out])
