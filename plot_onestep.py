#!/usr/bin/env python3
"""
Plot one-step vs two-step routing comparison results.

Reads the comparison.csv produced by sim/onestep_comparison.py (or emu) and generates:
  1. Total routing overhead (bytes) vs nodes — all three modes
  2. DV advert bytes vs nodes — one_step vs two_step
  3. PrefixSync bytes vs nodes — two_step only (one_step has zero)
  4. Convergence time vs nodes — all three modes
  5. Stacked bar: per-category routing traffic breakdown
  6. I/O time-series (cumulative + per-category breakdown)
  7. CDF plots (total bytes, convergence, packet sizes, DV advert bytes)

Overlaid emu vs sim mode:
  python3 plot_onestep.py --sim-csv results/sim_onestep/comparison.csv \\
                          --emu-csv results/emu_onestep/comparison.csv

Single-source mode:
  python3 plot_onestep.py --csv results/sim_onestep/comparison.csv
"""

import argparse
import csv
import glob
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


MODE_LABELS = {
    "baseline":  "Baseline (no prefixes)",
    "two_step":  "Two-step (DV + PrefixSync)",
    "one_step":  "One-step (flat DV)",
}

MODE_MARKERS = {"baseline": "^", "two_step": "s", "one_step": "o"}
MODE_COLORS = {"baseline": "gray", "two_step": "#1f77b4", "one_step": "#d62728"}

# Source styling for combined plots
SRC_LINESTYLE = {"sim": "-", "emu": "--"}
SRC_FILL = {"sim": True, "emu": False}  # for markers


def load_comparison_csv(path):
    """Load comparison CSV, returning rows grouped by (mode, grid_size)."""
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        return None
    groups = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = (row["mode"], int(row["grid_size"]))
            groups.setdefault(key, []).append(row)
    return groups


def aggregate(groups, mode, field, cast=float):
    """Return (nodes, means, stds) for a mode and field."""
    sizes = sorted(set(gs for (m, gs) in groups if m == mode))
    means, stds = [], []
    for gs in sizes:
        rows = groups.get((mode, gs), [])
        vals = [cast(r[field]) for r in rows if cast(r[field]) >= 0]
        if vals:
            means.append(np.mean(vals))
            stds.append(np.std(vals))
        else:
            means.append(np.nan)
            stds.append(0)
    nodes = [gs * gs for gs in sizes]
    return nodes, means, stds


def plot_total_routing_bytes(sources, out_dir):
    """sources: list of (src_name, groups) e.g. [('sim', groups), ('emu', groups)]"""
    combined = len(sources) > 1
    fig, ax = plt.subplots(figsize=(8, 5))
    for src_name, groups in sources:
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("baseline", "two_step", "one_step"):
            nodes, means, stds = aggregate(groups, mode, "total_routing_bytes", int)
            if any(not np.isnan(m) for m in means):
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.errorbar(nodes, [m / 1024 for m in means],
                            yerr=[s / 1024 for s in stds],
                            marker=MODE_MARKERS[mode], capsize=4,
                            color=MODE_COLORS[mode], linestyle=ls,
                            fillstyle="full" if SRC_FILL.get(src_name, True) else "none",
                            label=lbl)
    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("Total Routing Traffic (KB)")
    title = "Routing Overhead: Sim vs Emu" if combined else "Routing Overhead: One-step vs Two-step"
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_total_routing_bytes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_dv_advert_bytes(sources, out_dir):
    combined = len(sources) > 1
    fig, ax = plt.subplots(figsize=(8, 5))
    for src_name, groups in sources:
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("two_step", "one_step"):
            nodes, means, stds = aggregate(groups, mode, "dv_advert_bytes", int)
            if any(not np.isnan(m) for m in means):
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.errorbar(nodes, [m / 1024 for m in means],
                            yerr=[s / 1024 for s in stds],
                            marker=MODE_MARKERS[mode], capsize=4,
                            color=MODE_COLORS[mode], linestyle=ls,
                            fillstyle="full" if SRC_FILL.get(src_name, True) else "none",
                            label=lbl)
    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("DV Advertisement Traffic (KB)")
    title = "DV Advertisement: Sim vs Emu" if combined else "DV Advertisement Overhead"
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_dv_advert_bytes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_pfxsync_bytes(sources, out_dir):
    combined = len(sources) > 1
    fig, ax = plt.subplots(figsize=(8, 5))
    for src_name, groups in sources:
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("two_step", "one_step"):
            nodes, means, stds = aggregate(groups, mode, "pfxsync_bytes", int)
            if any(not np.isnan(m) for m in means):
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.errorbar(nodes, [m / 1024 for m in means],
                            yerr=[s / 1024 for s in stds],
                            marker=MODE_MARKERS[mode], capsize=4,
                            color=MODE_COLORS[mode], linestyle=ls,
                            fillstyle="full" if SRC_FILL.get(src_name, True) else "none",
                            label=lbl)
    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("PrefixSync Traffic (KB)")
    title = "PrefixSync: Sim vs Emu" if combined else "PrefixSync Overhead (zero for one-step)"
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_pfxsync_bytes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_convergence(sources, out_dir):
    combined = len(sources) > 1
    fig, ax = plt.subplots(figsize=(8, 5))
    for src_name, groups in sources:
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("baseline", "two_step", "one_step"):
            nodes, means, stds = aggregate(groups, mode, "convergence_s")
            if any(not np.isnan(m) for m in means):
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.errorbar(nodes, means, yerr=stds,
                            marker=MODE_MARKERS[mode], capsize=4,
                            color=MODE_COLORS[mode], linestyle=ls,
                            fillstyle="full" if SRC_FILL.get(src_name, True) else "none",
                            label=lbl)
    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("Convergence Time (s)")
    title = "Convergence: Sim vs Emu" if combined else "Routing Convergence: One-step vs Two-step"
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_convergence.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_stacked_breakdown(sources, out_dir):
    """Stacked bar chart: per-category traffic for each mode at each grid size.
    When two sources, plot side-by-side subplots."""
    modes = ["baseline", "two_step", "one_step"]
    cats = [("dv_advert_bytes", "DV Adverts"),
            ("pfxsync_bytes", "PrefixSync"),
            ("mgmt_bytes", "Mgmt")]

    combined = len(sources) > 1
    ncols = len(sources)
    fig, axes = plt.subplots(1, ncols, figsize=(10 * ncols, 6), sharey=True,
                             squeeze=False)

    for si, (src_name, groups) in enumerate(sources):
        ax = axes[0][si]
        sizes = sorted(set(gs for (_, gs) in groups))
        x = np.arange(len(sizes))
        width = 0.25

        for mi, mode in enumerate(modes):
            bottoms = np.zeros(len(sizes))
            for ci, (field, cat_label) in enumerate(cats):
                vals = []
                for gs in sizes:
                    rows = groups.get((mode, gs), [])
                    v = [int(r[field]) for r in rows if int(r[field]) >= 0]
                    vals.append(np.mean(v) / 1024 if v else 0)
                vals = np.array(vals)
                color_base = MODE_COLORS[mode]
                alpha = 1.0 - ci * 0.25
                label = f"{MODE_LABELS[mode]} — {cat_label}"
                ax.bar(x + mi * width, vals, width, bottom=bottoms,
                       color=color_base, alpha=alpha, label=label)
                bottoms += vals

        ax.set_xlabel("Grid size (NxN)")
        if si == 0:
            ax.set_ylabel("Traffic (KB)")
        ax.set_title(f"{src_name.upper()}: Traffic Breakdown" if combined else "Routing Traffic Breakdown by Category")
        ax.set_xticks(x + width)
        ax.set_xticklabels([f"{gs}x{gs}" for gs in sizes])
        ax.legend(fontsize=7, ncol=3, loc="upper left")
        ax.grid(True, alpha=0.3, axis="y")

    path = os.path.join(out_dir, "onestep_breakdown.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── I/O time-series (per-packet traces) ─────────────────────────────

def _load_packet_trace(path):
    """Load per-packet CSV → list of (time, category, bytes)."""
    events = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append((float(row["Time"]), row["Category"], int(row["Bytes"])))
    return events


def _find_packet_traces(data_dir):
    """Scan data_dir for packet-trace-*.csv, return dict keyed by (mode, grid_size, trial)."""
    pattern = re.compile(
        r"packet-trace-(baseline|two_step|one_step)-(\d+)x\d+-p\d+-t(\d+)\.csv$")
    traces = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "packet-trace-*.csv"))):
        m = pattern.search(os.path.basename(path))
        if m:
            mode, gs, trial = m.group(1), int(m.group(2)), int(m.group(3))
            traces[(mode, gs, trial)] = path
    return traces


def plot_io_timeseries(trace_sources, out_dir, grid_size=None):
    """Per-mode cumulative byte I/O graph.

    trace_sources: list of (src_name, data_dir)
    Overlays sim (solid) and emu (dashed) if both present.
    """
    combined = len(trace_sources) > 1

    # Determine grid size from first source that has traces
    gs = grid_size
    all_traces = {}  # (src_name) -> {(mode, gs, trial): path}
    for src_name, data_dir in trace_sources:
        t = _find_packet_traces(data_dir)
        all_traces[src_name] = t
        if not gs and t:
            available_gs = sorted(set(g for (_, g, _) in t))
            gs = available_gs[-1] if available_gs else None

    if gs is None:
        print("No per-packet traces found — skipping I/O graph.")
        return

    # ── Cumulative total routing graph ──
    fig, ax = plt.subplots(figsize=(10, 5))
    routing_cats = {"DvAdvert", "PrefixSync", "Mgmt"}

    for src_name, data_dir in trace_sources:
        traces = all_traces[src_name]
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("baseline", "two_step", "one_step"):
            trial_keys = [(mode, gs, t) for (m, g, t) in traces if m == mode and g == gs]
            if not trial_keys:
                continue
            events = _load_packet_trace(traces[trial_keys[0]])
            if not events:
                continue
            times = []
            cum = 0
            for t, cat, b in sorted(events):
                if cat in routing_cats:
                    cum += b
                    times.append((t, cum))
            if times:
                ts, cs = zip(*times)
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.plot(ts, [c / 1024 for c in cs],
                        color=MODE_COLORS[mode], linestyle=ls, label=lbl)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Cumulative Routing Traffic (KB)")
    title = f"I/O Graph: Sim vs Emu ({gs}x{gs} grid)" if combined else f"I/O Graph: Cumulative Routing Traffic ({gs}x{gs} grid)"
    ax.set_title(title)
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_io_cumulative.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")

    # ── Per-category breakdown: one row per source ──
    nrows = len(trace_sources)
    fig, axes = plt.subplots(nrows, 3, figsize=(16, 5 * nrows), sharey=False,
                              squeeze=False)
    cat_styles = {"DvAdvert": "-", "PrefixSync": "--", "Mgmt": ":"}

    for si, (src_name, data_dir) in enumerate(trace_sources):
        traces = all_traces[src_name]
        for mi, mode in enumerate(("baseline", "two_step", "one_step")):
            ax = axes[si][mi]
            trial_keys = [(mode, gs, t) for (m, g, t) in traces if m == mode and g == gs]
            if not trial_keys:
                ax.set_title(f"{src_name}: {MODE_LABELS[mode]}")
                continue

            events = _load_packet_trace(traces[trial_keys[0]])
            per_cat = {}
            for t, cat, b in sorted(events):
                if cat in routing_cats:
                    per_cat.setdefault(cat, []).append((t, b))

            for cat in ("DvAdvert", "PrefixSync", "Mgmt"):
                items = per_cat.get(cat, [])
                if not items:
                    continue
                cum = 0
                ts, cs = [], []
                for t, b in items:
                    cum += b
                    ts.append(t)
                    cs.append(cum / 1024)
                ax.plot(ts, cs, cat_styles.get(cat, "-"), label=cat)

            ax.set_xlabel("Time (s)")
            if mi == 0:
                ax.set_ylabel("Cumulative Traffic (KB)")
            ax.set_title(f"{src_name.upper()}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode])
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)

    fig.suptitle(f"I/O Breakdown ({gs}x{gs} grid)", y=1.02)
    path = os.path.join(out_dir, "onestep_io_breakdown.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── CDF plots ───────────────────────────────────────────────────────

def _ecdf(data):
    """Return sorted values and their ECDF probabilities."""
    xs = np.sort(data)
    ys = np.arange(1, len(xs) + 1) / len(xs)
    return xs, ys


def plot_cdf_total_routing_bytes(sources, out_dir):
    """CDF of total routing bytes across all (grid_size, trial) pairs per mode."""
    combined = len(sources) > 1
    fig, ax = plt.subplots(figsize=(8, 5))
    for src_name, groups in sources:
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("baseline", "two_step", "one_step"):
            vals = []
            for (m, gs), rows in groups.items():
                if m == mode:
                    vals.extend(int(r["total_routing_bytes"]) for r in rows)
            if vals:
                xs, ys = _ecdf(np.array(vals) / 1024)
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.step(xs, ys, where="post",
                        color=MODE_COLORS[mode], linestyle=ls, label=lbl)
    ax.set_xlabel("Total Routing Traffic (KB)")
    ax.set_ylabel("CDF")
    ax.set_title("CDF: Total Routing Traffic")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_cdf_total_bytes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_cdf_convergence(sources, out_dir):
    """CDF of convergence times across all (grid_size, trial) pairs per mode."""
    combined = len(sources) > 1
    fig, ax = plt.subplots(figsize=(8, 5))
    for src_name, groups in sources:
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("baseline", "two_step", "one_step"):
            vals = []
            for (m, gs), rows in groups.items():
                if m == mode:
                    vals.extend(float(r["convergence_s"]) for r in rows
                                if float(r["convergence_s"]) >= 0)
            if vals:
                xs, ys = _ecdf(np.array(vals))
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.step(xs, ys, where="post",
                        color=MODE_COLORS[mode], linestyle=ls, label=lbl)
    ax.set_xlabel("Convergence Time (s)")
    ax.set_ylabel("CDF")
    ax.set_title("CDF: Routing Convergence Time")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_cdf_convergence.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_cdf_packet_sizes(trace_sources, out_dir, grid_size=None):
    """CDF of individual packet sizes (routing only) by mode.
    trace_sources: list of (src_name, data_dir)"""
    combined = len(trace_sources) > 1
    routing_cats = {"DvAdvert", "PrefixSync", "Mgmt"}

    # Determine grid size
    gs = grid_size
    all_traces = {}
    for src_name, data_dir in trace_sources:
        t = _find_packet_traces(data_dir)
        all_traces[src_name] = t
        if not gs and t:
            available_gs = sorted(set(g for (_, g, _) in t))
            gs = available_gs[-1] if available_gs else None

    if gs is None:
        print("No per-packet traces found — skipping packet-size CDF.")
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    for src_name, data_dir in trace_sources:
        traces = all_traces[src_name]
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("baseline", "two_step", "one_step"):
            sizes = []
            for (m, g, t), path in traces.items():
                if m == mode and g == gs:
                    for _, cat, b in _load_packet_trace(path):
                        if cat in routing_cats:
                            sizes.append(b)
            if sizes:
                xs, ys = _ecdf(np.array(sizes))
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.step(xs, ys, where="post",
                        color=MODE_COLORS[mode], linestyle=ls, label=lbl)

    ax.set_xlabel("Packet Size (bytes)")
    ax.set_ylabel("CDF")
    ax.set_title(f"CDF: Routing Packet Sizes ({gs}x{gs} grid)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_cdf_packet_sizes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_cdf_dv_advert_bytes(sources, out_dir):
    """CDF of DV advertisement bytes across all (grid_size, trial) pairs per mode."""
    combined = len(sources) > 1
    fig, ax = plt.subplots(figsize=(8, 5))
    for src_name, groups in sources:
        ls = SRC_LINESTYLE.get(src_name, "-")
        for mode in ("two_step", "one_step"):
            vals = []
            for (m, gs), rows in groups.items():
                if m == mode:
                    vals.extend(int(r["dv_advert_bytes"]) for r in rows)
            if vals:
                xs, ys = _ecdf(np.array(vals) / 1024)
                lbl = f"{src_name}: {MODE_LABELS[mode]}" if combined else MODE_LABELS[mode]
                ax.step(xs, ys, where="post",
                        color=MODE_COLORS[mode], linestyle=ls, label=lbl)
    ax.set_xlabel("DV Advertisement Traffic (KB)")
    ax.set_ylabel("CDF")
    ax.set_title("CDF: DV Advertisement Traffic")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "onestep_cdf_dv_advert_bytes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot one-step vs two-step routing comparison")
    parser.add_argument("--csv", default=None,
                        help="Path to comparison.csv (single-source mode)")
    parser.add_argument("--sim-csv", default=None,
                        help="Path to sim comparison.csv (combined mode)")
    parser.add_argument("--emu-csv", default=None,
                        help="Path to emu comparison.csv (combined mode)")
    parser.add_argument("--data-dir", default=None,
                        help="Directory with per-packet trace CSVs "
                             "(single-source, default: same dir as --csv)")
    parser.add_argument("--sim-data-dir", default=None,
                        help="Sim packet-trace directory (default: same dir as --sim-csv)")
    parser.add_argument("--emu-data-dir", default=None,
                        help="Emu packet-trace directory (default: same dir as --emu-csv)")
    parser.add_argument("--out", default="results/plots",
                        help="Output directory for plots")
    args = parser.parse_args()

    # Build source lists: [(name, groups)] and [(name, data_dir)]
    csv_sources = []
    trace_sources = []

    if args.sim_csv or args.emu_csv:
        # Combined mode
        if args.sim_csv:
            g = load_comparison_csv(args.sim_csv)
            if g:
                csv_sources.append(("sim", g))
                d = args.sim_data_dir or os.path.dirname(os.path.abspath(args.sim_csv))
                trace_sources.append(("sim", d))
        if args.emu_csv:
            g = load_comparison_csv(args.emu_csv)
            if g:
                csv_sources.append(("emu", g))
                d = args.emu_data_dir or os.path.dirname(os.path.abspath(args.emu_csv))
                trace_sources.append(("emu", d))
    else:
        # Single-source mode (backward compat)
        csv_path = args.csv or "results/sim_onestep/comparison.csv"
        g = load_comparison_csv(csv_path)
        if g:
            csv_sources.append(("sim", g))
            d = args.data_dir or os.path.dirname(os.path.abspath(csv_path))
            trace_sources.append(("sim", d))

    if not csv_sources:
        print("No data to plot.")
        return

    os.makedirs(args.out, exist_ok=True)

    # Standard line plots
    plot_total_routing_bytes(csv_sources, args.out)
    plot_dv_advert_bytes(csv_sources, args.out)
    plot_pfxsync_bytes(csv_sources, args.out)
    plot_convergence(csv_sources, args.out)
    plot_stacked_breakdown(csv_sources, args.out)

    # I/O time-series
    plot_io_timeseries(trace_sources, args.out)

    # CDF alternate versions
    plot_cdf_total_routing_bytes(csv_sources, args.out)
    plot_cdf_convergence(csv_sources, args.out)
    plot_cdf_dv_advert_bytes(csv_sources, args.out)
    plot_cdf_packet_sizes(trace_sources, args.out)

    print(f"\nAll plots saved to {args.out}/")


if __name__ == "__main__":
    main()
