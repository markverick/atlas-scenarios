"""
Shared constants and helpers for churn scenario drivers (sim and emu).

All topology-specific knowledge (churn targets, conf file paths) lives here
so that adding a new topology requires only:
  1. An entry in KNOWN_TOPOLOGIES below
  2. A JSON config file in scenarios/
"""

import csv
import os
import random
import sys

# --- Shared constants ---

FIELDNAMES = [
    "topology", "grid_size", "num_nodes", "num_links", "trial", "mode",
    "num_prefixes", "window_s", "phase2_start", "convergence_s", "phase",
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
      grid [3]     -> results/sim_churn_3x3
      grid [4]     -> results/sim_churn_4x4
      grid [3,4]   -> results/sim_churn
      sprint       -> results/sim_churn_sprint
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


def build_random_churn_events(num_prefixes, phase2_start, *,
                              link_src, link_dst, churn_node,
                              window_end, seed=42, num_cycles=3,
                              interval=5.0, recovery_delay=3.0,
                              all_links=None, all_nodes=None,
                              prefix_churn_rate=0.0):
    """Build stochastic churn events drawn from exponential distributions.

    Two independent event streams are generated:

    1. **Link failures**: ``num_cycles`` fail/recover pairs.  Each cycle
       picks a random link from *all_links* (or falls back to the single
       *link_src*/*link_dst*).  Inter-cycle gaps and recovery times are
       drawn from Exp(1/interval) and Exp(1/recovery_delay) respectively.

    2. **Prefix churn** (if *prefix_churn_rate* > 0): an independent
       Poisson stream of withdraw/re-announce pairs on randomly chosen
       nodes from *all_nodes*.  Each withdrawal is re-announced after a
       random Exp(1/recovery_delay) pause.  If *prefix_churn_rate* is 0,
       prefix events are coupled to link events as before (one
       withdraw/announce per link cycle on the affected link's source).

    Parameters
    ----------
    all_links : list[(str, str)] | None
        Full list of links to sample from.  ``None`` -> single link.
    all_nodes : list[str] | None
        Full list of node names to sample from.  ``None`` -> *churn_node*.
    prefix_churn_rate : float
        Mean prefix-churn events per second (independent stream).
        0 means prefix events are coupled to link failures (legacy behaviour).
    """
    if not all_links and (link_src is None or link_dst is None):
        return []

    rng = random.Random(seed)
    events = []
    links_pool = all_links if all_links else [(link_src, link_dst)]
    nodes_pool = all_nodes if all_nodes else ([churn_node] if churn_node else [])

    # --- Stream 1: link failures ---
    t = phase2_start
    for _ in range(num_cycles):
        gap = rng.expovariate(1.0 / interval)
        t_down = t + gap
        if t_down >= window_end - 1.0:
            break

        recovery = max(rng.expovariate(1.0 / recovery_delay), 1.0)
        t_up = t_down + recovery
        if t_up >= window_end - 0.5:
            t_up = window_end - 0.5

        src, dst = rng.choice(links_pool)
        events.append({"time": round(t_down, 3), "type": "link_down",
                       "src": src, "dst": dst})
        events.append({"time": round(t_up, 3), "type": "link_up",
                       "src": src, "dst": dst})

        # Coupled prefix churn (legacy)
        if prefix_churn_rate == 0 and num_prefixes > 0 and nodes_pool:
            node = src if src in nodes_pool else rng.choice(nodes_pool)
            pfx = f"/data/{node}/pfx0"
            t_withdraw = min(t_down + 0.5, t_up - 0.1)
            t_announce = min(t_up + 0.5, window_end - 0.1)
            events.append({"time": round(t_withdraw, 3), "type": "prefix_withdraw",
                           "node": node, "prefix": pfx})
            events.append({"time": round(t_announce, 3), "type": "prefix_announce",
                           "node": node, "prefix": pfx})

        t = t_up + 1.0

    # --- Stream 2: independent prefix churn (Poisson) ---
    if prefix_churn_rate > 0 and num_prefixes > 0 and nodes_pool:
        t = phase2_start
        while True:
            gap = rng.expovariate(prefix_churn_rate)
            t_withdraw = t + gap
            if t_withdraw >= window_end - 2.0:
                break
            node = rng.choice(nodes_pool)
            pfx_idx = rng.randint(0, num_prefixes - 1)
            pfx = f"/data/{node}/pfx{pfx_idx}"
            pause = max(rng.expovariate(1.0 / recovery_delay), 1.0)
            t_announce = min(t_withdraw + pause, window_end - 0.1)
            events.append({"time": round(t_withdraw, 3), "type": "prefix_withdraw",
                           "node": node, "prefix": pfx})
            events.append({"time": round(t_announce, 3), "type": "prefix_announce",
                           "node": node, "prefix": pfx})
            t = t_withdraw

    events.sort(key=lambda e: e["time"])
    return events


def build_prefix_scaling_events(num_prefixes, phase2_start, *,
                                per_prefix_rate, churn_node,
                                window_end, seed=42,
                                recovery_delay=3.0,
                                all_nodes=None):
    """Build independent per-prefix Poisson churn streams (no link events).

    Each prefix gets its own independent Poisson stream of withdraw/announce
    pairs at *per_prefix_rate* events/s.  More prefixes -> proportionally more
    total churn events in the network.

    Parameters
    ----------
    per_prefix_rate : float
        Mean withdraw events per second **per prefix**.
    all_nodes : list[str] | None
        Node pool for distributing prefixes.  Each prefix is assigned to a
        random node at creation time and stays there throughout.
    """
    if num_prefixes <= 0 or per_prefix_rate <= 0:
        return []

    rng = random.Random(seed)
    nodes_pool = all_nodes if all_nodes else ([churn_node] if churn_node else [])
    if not nodes_pool:
        return []

    events = []

    # Assign each prefix to a random node (stable across events)
    prefix_assignments = []
    for i in range(num_prefixes):
        node = rng.choice(nodes_pool)
        pfx = f"/data/{node}/pfx{i}"
        prefix_assignments.append((node, pfx))

    # Generate independent Poisson stream per prefix
    for node, pfx in prefix_assignments:
        t = phase2_start
        while True:
            gap = rng.expovariate(per_prefix_rate)
            t_withdraw = t + gap
            if t_withdraw >= window_end - 2.0:
                break
            pause = max(rng.expovariate(1.0 / recovery_delay), 1.0)
            t_announce = min(t_withdraw + pause, window_end - 0.1)
            events.append({"time": round(t_withdraw, 3),
                           "type": "prefix_withdraw",
                           "node": node, "prefix": pfx})
            events.append({"time": round(t_announce, 3),
                           "type": "prefix_announce",
                           "node": node, "prefix": pfx})
            # Advance past announce to prevent overlapping cycles on the
            # same prefix (avoids double-withdraw without intervening announce).
            t = t_announce

    events.sort(key=lambda e: e["time"])
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
                      trial, mode, num_prefixes, window_s, phase2_start,
                      convergence_s):
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
            "phase2_start": phase2_start,
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

    Auto-detects the sibling runner directory so that plots always
    include both sim and emu data when available.  For example, if
    out_dir is ``results/sim_churn_random``, we look for
    ``results/emu_churn_random`` and vice-versa.

    Derives plot output directory from out_dir:
      results/sim_churn_3x3    -> results/plots_3x3
      results/sim_churn_sprint -> results/plots_sprint
      results/sim_churn        -> results/plots
    """
    import subprocess
    script = os.path.join(_REPO_DIR, "plot_churn.py")
    if not os.path.isfile(script):
        return
    base = os.path.basename(os.path.normpath(out_dir))
    parent = os.path.dirname(out_dir) or "results"

    # Auto-detect sibling runner directory
    if not sim_dir and base.startswith("emu_churn"):
        candidate = os.path.join(parent, base.replace("emu_churn", "sim_churn", 1))
        if os.path.isdir(candidate):
            sim_dir = candidate
    if not emu_dir and base.startswith("sim_churn"):
        candidate = os.path.join(parent, base.replace("sim_churn", "emu_churn", 1))
        if os.path.isdir(candidate):
            emu_dir = candidate

    suffix = base
    for prefix in ("sim_churn", "emu_churn"):
        if suffix.startswith(prefix):
            suffix = suffix[len(prefix):].lstrip("_")
            break
    plot_out = os.path.join(parent, f"plots_{suffix}" if suffix else "plots")
    subprocess.run([sys.executable, script,
                    "--sim", sim_dir or "",
                    "--emu", emu_dir or "",
                    "--out", plot_out])
