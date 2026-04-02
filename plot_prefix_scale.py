#!/usr/bin/env python3
"""
Plots for the prefix-scalability scenario.

1. Churn overhead comparison: one_step vs two_step total routing bytes
   across prefix counts (bar chart).
2. Churn overhead breakdown: DV vs PfxSync stacked bars per mode/prefix.
3. Per-variant IO time series: one subplot per (mode, prefix_count).
"""

import argparse
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Helpers ─────────────────────────────────────────────────────────

def _human_bytes(v, _pos=None):
    if v >= 1e9:
        return f"{v/1e9:.1f} GB"
    if v >= 1e6:
        return f"{v/1e6:.1f} MB"
    if v >= 1e3:
        return f"{v/1e3:.1f} KB"
    return f"{v:.0f} B"


def load_churn_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_packet_trace(path):
    """Return lists of (time, category, bytes)."""
    times, cats, sizes = [], [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["Time"]))
            cats.append(row["Category"])
            sizes.append(int(row["Bytes"]))
    return times, cats, sizes


def bin_io(times, sizes, bin_width=1.0):
    """Bin packet sizes into time bins, return bin_edges and bytes_per_bin.

    Handles negative timestamps (emu wall-clock offsets) by shifting so
    the minimum time becomes 0.
    """
    if not times:
        return [], []
    t_min = min(times)
    if t_min < 0:
        times = [t - t_min for t in times]
    t_max = max(times)
    n_bins = int(t_max / bin_width) + 1
    bins = [0.0] * n_bins
    for t, s in zip(times, sizes):
        idx = min(int(t / bin_width), n_bins - 1)
        bins[idx] += s
    edges = [i * bin_width for i in range(n_bins)]
    return edges, bins


# ── Plot 1: Churn-phase total overhead comparison ───────────────────

def plot_churn_comparison(rows, out_dir):
    """Bar chart: one_step vs two_step churn-phase total_routing_bytes."""
    churn = [r for r in rows if r["phase"] == "churn" and r["mode"] != "baseline"]

    prefix_counts = sorted(set(int(r["num_prefixes"]) for r in churn))
    modes = ["two_step", "one_step"]
    colors = {"two_step": "#4C72B0", "one_step": "#DD8452"}
    labels = {"two_step": "Two-step (DV + PfxSync)", "one_step": "One-step (DV only)"}

    x = np.arange(len(prefix_counts))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, mode in enumerate(modes):
        vals = []
        for pc in prefix_counts:
            match = [r for r in churn if r["mode"] == mode and int(r["num_prefixes"]) == pc]
            vals.append(int(match[0]["total_routing_bytes"]) if match else 0)
        ax.bar(x + (i - 0.5) * width, vals, width, label=labels[mode], color=colors[mode])

    ax.set_xlabel("Number of Prefixes")
    ax.set_ylabel("Churn-Phase Routing Bytes")
    ax.set_xticks(x)
    ax.set_xticklabels([str(p) for p in prefix_counts])
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(_human_bytes))
    ax.legend()
    ax.set_title("Churn Overhead: One-Step vs Two-Step")
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_comparison.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


# ── Plot 2: Stacked breakdown (DV + PfxSync) ───────────────────────

def plot_churn_breakdown(rows, out_dir):
    """Stacked bar chart showing DV vs PfxSync contribution per mode/prefix."""
    churn = [r for r in rows if r["phase"] == "churn" and r["mode"] != "baseline"]

    prefix_counts = sorted(set(int(r["num_prefixes"]) for r in churn))
    modes = ["two_step", "one_step"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    for ax, mode in zip(axes, modes):
        dv_vals, pfx_vals = [], []
        for pc in prefix_counts:
            match = [r for r in churn if r["mode"] == mode and int(r["num_prefixes"]) == pc]
            if match:
                dv_vals.append(int(match[0]["dv_advert_bytes"]))
                pfx_vals.append(int(match[0]["pfxsync_bytes"]))
            else:
                dv_vals.append(0)
                pfx_vals.append(0)

        x = np.arange(len(prefix_counts))
        ax.bar(x, dv_vals, label="DV Adverts", color="#4C72B0")
        ax.bar(x, pfx_vals, bottom=dv_vals, label="PrefixSync", color="#C44E52")
        ax.set_xlabel("Number of Prefixes")
        ax.set_xticks(x)
        ax.set_xticklabels([str(p) for p in prefix_counts])
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(_human_bytes))
        ax.legend()
        title = "Two-Step" if mode == "two_step" else "One-Step"
        ax.set_title(f"{title} — Churn Traffic Breakdown")

    axes[0].set_ylabel("Churn-Phase Routing Bytes")
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_breakdown.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


# ── Plot 3: Per-variant IO time series ──────────────────────────────

def plot_io_per_variant(data_dir, out_dir, phase2_start=10.0):
    """One IO subplot per (mode, prefix_count). Rows=prefix_count, cols=mode."""
    modes = ["two_step", "one_step"]
    mode_labels = {"two_step": "Two-Step", "one_step": "One-Step"}

    # Discover prefix counts from filenames
    import re
    prefix_counts = set()
    for fname in os.listdir(data_dir):
        m = re.match(r"packet-trace-(two_step|one_step)-.*-p(\d+)-t\d+\.csv", fname)
        if m:
            prefix_counts.add(int(m.group(2)))
    prefix_counts = sorted(prefix_counts)

    if not prefix_counts:
        print("  No packet traces found, skipping IO plots")
        return

    nrows = len(prefix_counts)
    ncols = len(modes)
    fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 3 * nrows),
                             squeeze=False, sharex=True)

    bin_w = 1.0

    for col, mode in enumerate(modes):
        for row, pc in enumerate(prefix_counts):
            ax = axes[row][col]
            pattern = f"packet-trace-{mode}-sprint-p{pc}-t1.csv"
            trace_path = os.path.join(data_dir, pattern)

            if not os.path.exists(trace_path):
                ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                        ha="center", va="center")
                continue

            times, cats, sizes = load_packet_trace(trace_path)

            # Split by category
            dv_t, dv_s, pfx_t, pfx_s = [], [], [], []
            for t, c, s in zip(times, cats, sizes):
                if c == "DvAdvert":
                    dv_t.append(t); dv_s.append(s)
                elif c == "PrefixSync":
                    pfx_t.append(t); pfx_s.append(s)

            dv_edges, dv_bins = bin_io(dv_t, dv_s, bin_w)
            pfx_edges, pfx_bins = bin_io(pfx_t, pfx_s, bin_w)

            if dv_edges:
                ax.fill_between(dv_edges, dv_bins, alpha=0.7, label="DV", color="#4C72B0", step="mid")
            if pfx_edges:
                ax.fill_between(pfx_edges, pfx_bins, alpha=0.7, label="PfxSync", color="#C44E52", step="mid")

            ax.axvline(phase2_start, color="red", ls="--", lw=0.8, alpha=0.6)
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(_human_bytes))

            if row == 0:
                ax.set_title(mode_labels[mode])
            if col == 0:
                ax.set_ylabel(f"p{pc}")
            if row == nrows - 1:
                ax.set_xlabel("Time (s)")
            if row == 0 and col == ncols - 1:
                ax.legend(fontsize=7, loc="upper right")

    fig.suptitle("Routing I/O per Variant (1s bins)", fontsize=13, y=1.01)
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_io_grid.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {path}")


# ── Plot 4: Baseline-subtracted overhead (net prefix cost) ─────────

def plot_net_overhead(rows, out_dir):
    """Line plot: churn bytes minus baseline, per mode across prefix counts."""
    baseline_row = [r for r in rows if r["mode"] == "baseline" and r["phase"] == "churn"]
    if not baseline_row:
        return
    baseline_bytes = int(baseline_row[0]["total_routing_bytes"])

    churn = [r for r in rows if r["phase"] == "churn" and r["mode"] != "baseline"]
    prefix_counts = sorted(set(int(r["num_prefixes"]) for r in churn))
    modes = ["two_step", "one_step"]
    colors = {"two_step": "#4C72B0", "one_step": "#DD8452"}
    labels = {"two_step": "Two-step", "one_step": "One-step"}

    fig, ax = plt.subplots(figsize=(8, 5))
    for mode in modes:
        vals = []
        for pc in prefix_counts:
            match = [r for r in churn if r["mode"] == mode and int(r["num_prefixes"]) == pc]
            v = int(match[0]["total_routing_bytes"]) - baseline_bytes if match else 0
            vals.append(max(v, 0))
        ax.plot(prefix_counts, vals, "o-", label=labels[mode], color=colors[mode], linewidth=2)

    ax.set_xlabel("Number of Prefixes")
    ax.set_ylabel("Net Churn Overhead (total − baseline)")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(_human_bytes))
    ax.legend()
    ax.set_title("Prefix-Scaling Overhead (Baseline Subtracted)")
    ax.set_xticks(prefix_counts)
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_net_overhead.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


# ── Plot 5: Raw overhead line plot (no baseline subtraction) ────────

def plot_raw_overhead(rows, out_dir):
    """Line plot: raw churn-phase total_routing_bytes per mode across prefix counts."""
    churn = [r for r in rows if r["phase"] == "churn" and r["mode"] != "baseline"]

    prefix_counts = sorted(set(int(r["num_prefixes"]) for r in churn))
    modes = ["two_step", "one_step"]
    colors = {"two_step": "#4C72B0", "one_step": "#DD8452"}
    labels = {"two_step": "Two-step", "one_step": "One-step"}

    # Baseline as horizontal reference
    baseline_row = [r for r in rows if r["mode"] == "baseline" and r["phase"] == "churn"]

    fig, ax = plt.subplots(figsize=(8, 5))
    for mode in modes:
        vals = []
        for pc in prefix_counts:
            match = [r for r in churn if r["mode"] == mode and int(r["num_prefixes"]) == pc]
            vals.append(int(match[0]["total_routing_bytes"]) if match else 0)
        ax.plot(prefix_counts, vals, "o-", label=labels[mode], color=colors[mode], linewidth=2)

    if baseline_row:
        bl = int(baseline_row[0]["total_routing_bytes"])
        ax.axhline(bl, color="gray", ls="--", lw=1, alpha=0.7, label=f"Baseline ({_human_bytes(bl)})")

    ax.set_xlabel("Number of Prefixes")
    ax.set_ylabel("Churn-Phase Routing Bytes")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(_human_bytes))
    ax.legend()
    ax.set_title("Prefix-Scaling: Total Routing Overhead")
    ax.set_xticks(prefix_counts)
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_raw_overhead.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


# ── Plot 6: Sim vs Emu comparison (one graph per mode) ──────────────

def plot_sim_vs_emu(sim_rows, emu_rows, out_dir):
    """Two figures: one for two_step, one for one_step.
    Each has sim and emu lines across prefix counts."""
    modes = ["two_step", "one_step"]
    titles = {"two_step": "Two-Step", "one_step": "One-Step"}

    for mode in modes:
        sim_churn = [r for r in sim_rows if r["phase"] == "churn" and r["mode"] == mode]
        emu_churn = [r for r in emu_rows if r["phase"] == "churn" and r["mode"] == mode]

        all_pcs = sorted(set(
            [int(r["num_prefixes"]) for r in sim_churn] +
            [int(r["num_prefixes"]) for r in emu_churn]
        ))
        if not all_pcs:
            continue

        fig, ax = plt.subplots(figsize=(8, 5))

        for label, churn, color, marker in [
            ("Simulation", sim_churn, "#4C72B0", "o"),
            ("Emulation", emu_churn, "#DD8452", "s"),
        ]:
            vals = []
            pcs = []
            for pc in all_pcs:
                match = [r for r in churn if int(r["num_prefixes"]) == pc]
                if match:
                    vals.append(int(match[0]["total_routing_bytes"]))
                    pcs.append(pc)
            if vals:
                ax.plot(pcs, vals, f"{marker}-", label=label, color=color, linewidth=2)

        ax.set_xlabel("Number of Prefixes")
        ax.set_ylabel("Churn-Phase Routing Bytes")
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(_human_bytes))
        ax.legend()
        ax.set_title(f"{titles[mode]}: Simulation vs Emulation")
        ax.set_xticks(all_pcs)
        fig.tight_layout()
        path = os.path.join(out_dir, f"sim_vs_emu_{mode}.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"  Saved {path}")


# ── Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Prefix-scaling plots")
    parser.add_argument("--data", required=True,
                        help="Directory with churn.csv and packet traces")
    parser.add_argument("--data2", default=None,
                        help="Second data dir for sim-vs-emu comparison")
    parser.add_argument("--out", default=None,
                        help="Output directory for plots (default: sibling plots dir)")
    args = parser.parse_args()

    data_dir = args.data
    csv_path = os.path.join(data_dir, "churn.csv")
    if not os.path.exists(csv_path):
        print(f"ERROR: {csv_path} not found")
        sys.exit(1)

    rows = load_churn_csv(csv_path)

    if args.out is None:
        parent = os.path.dirname(os.path.abspath(data_dir))
        base = os.path.basename(os.path.abspath(data_dir))
        # Derive plots subdir: sim_churn_X → plots_X/sim, emu_churn_X → plots_X/emu
        if base.startswith("sim_churn_"):
            plots_base = base.replace("sim_churn_", "plots_")
            args.out = os.path.join(parent, plots_base, "sim")
        elif base.startswith("emu_churn_"):
            plots_base = base.replace("emu_churn_", "plots_")
            args.out = os.path.join(parent, plots_base, "emu")
        else:
            args.out = os.path.join(parent, base + "_plots")
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    print(f"Generating prefix-scaling plots from {csv_path}")
    plot_churn_comparison(rows, out_dir)
    plot_churn_breakdown(rows, out_dir)
    plot_net_overhead(rows, out_dir)
    plot_raw_overhead(rows, out_dir)
    plot_io_per_variant(data_dir, out_dir)

    if args.data2:
        csv2 = os.path.join(args.data2, "churn.csv")
        if not os.path.exists(csv2):
            print(f"WARNING: {csv2} not found, skipping sim-vs-emu comparison")
        else:
            rows2 = load_churn_csv(csv2)
            # Determine which is sim, which is emu
            base1 = os.path.basename(os.path.abspath(data_dir))
            if "sim" in base1:
                sim_rows, emu_rows = rows, rows2
            else:
                sim_rows, emu_rows = rows2, rows
            plot_sim_vs_emu(sim_rows, emu_rows, out_dir)

    print("Done.")


if __name__ == "__main__":
    main()
