#!/usr/bin/env python3
"""
Plot one-step vs two-step scaling across grid sizes.

Usage:
    python3 experiments/onestep/plot_scaling.py
    python3 experiments/onestep/plot_scaling.py --sim-csv results/onestep_medium/sim/comparison.csv \
                                                                                            --emu-csv results/onestep_medium/emu/comparison.csv \
                                                                                            --out results/onestep_medium/plots
"""

import argparse
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

MODES = ["baseline", "two_step", "one_step"]
MODE_LABELS = {"baseline": "Baseline", "two_step": "Two-step", "one_step": "One-step"}
MODE_COLORS = {"baseline": "#7f7f7f", "two_step": "#1f77b4", "one_step": "#d62728"}
MODE_MARKERS = {"baseline": "^", "two_step": "s", "one_step": "o"}


def load_csv(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def group_by_grid_mode(rows):
    """Return dict: (grid_size, mode) -> list of row dicts."""
    groups = {}
    for r in rows:
        key = (int(r["grid_size"]), r["mode"])
        groups.setdefault(key, []).append(r)
    return groups


def plot_total_bytes_scaling(sim_rows, emu_rows, out_dir):
    """Total routing bytes vs number of nodes, for each mode, sim & emu."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)

    for ax, rows, plat_label in [
        (axes[0], sim_rows, "Simulation"),
        (axes[1], emu_rows, "Emulation"),
    ]:
        groups = group_by_grid_mode(rows)
        grids = sorted(set(int(r["grid_size"]) for r in rows))
        nodes = [g * g for g in grids]

        for mode in MODES:
            vals = []
            for g in grids:
                mode_rows = groups.get((g, mode), [])
                if mode_rows:
                    avg = np.mean([int(r["total_routing_bytes"]) for r in mode_rows])
                    vals.append(avg / 1024)
                else:
                    vals.append(np.nan)
            ax.plot(nodes, vals, color=MODE_COLORS[mode],
                    marker=MODE_MARKERS[mode], linewidth=2, markersize=8,
                    label=MODE_LABELS[mode])

        ax.set_xlabel("Number of Nodes", fontsize=12)
        ax.set_title(plat_label, fontsize=13, fontweight="bold")
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_xticks(nodes)

    axes[0].set_ylabel("Total Routing Traffic (KB)", fontsize=12)
    fig.suptitle("One-step vs Two-step: Routing Traffic Scaling",
                 fontsize=14, fontweight="bold")
    path = os.path.join(out_dir, "scaling_total_bytes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_overhead_scaling(sim_rows, emu_rows, out_dir):
    """Overhead above baseline (bytes) vs nodes, showing how prefix cost grows."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)

    for ax, rows, plat_label in [
        (axes[0], sim_rows, "Simulation"),
        (axes[1], emu_rows, "Emulation"),
    ]:
        groups = group_by_grid_mode(rows)
        grids = sorted(set(int(r["grid_size"]) for r in rows))
        nodes = [g * g for g in grids]

        baseline_vals = []
        for g in grids:
            bl = groups.get((g, "baseline"), [])
            baseline_vals.append(
                np.mean([int(r["total_routing_bytes"]) for r in bl]) if bl else 0)

        for mode in ["two_step", "one_step"]:
            overhead = []
            for i, g in enumerate(grids):
                mode_rows = groups.get((g, mode), [])
                if mode_rows:
                    avg = np.mean([int(r["total_routing_bytes"]) for r in mode_rows])
                    overhead.append((avg - baseline_vals[i]) / 1024)
                else:
                    overhead.append(np.nan)
            ax.plot(nodes, overhead, color=MODE_COLORS[mode],
                    marker=MODE_MARKERS[mode], linewidth=2, markersize=8,
                    label=MODE_LABELS[mode])

        ax.set_xlabel("Number of Nodes", fontsize=12)
        ax.set_title(plat_label, fontsize=13, fontweight="bold")
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_xticks(nodes)

    axes[0].set_ylabel("Prefix Overhead Above Baseline (KB)", fontsize=12)
    fig.suptitle("Prefix Distribution Overhead Scaling",
                 fontsize=14, fontweight="bold")
    path = os.path.join(out_dir, "scaling_overhead.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_savings_pct(sim_rows, emu_rows, out_dir):
    """Percentage savings of one-step over two-step vs nodes."""
    fig, ax = plt.subplots(figsize=(8, 5))

    for rows, plat_label, ls, color in [
        (sim_rows, "Simulation", "-", "#1f77b4"),
        (emu_rows, "Emulation", "--", "#ff7f0e"),
    ]:
        groups = group_by_grid_mode(rows)
        grids = sorted(set(int(r["grid_size"]) for r in rows))
        nodes = [g * g for g in grids]

        pcts = []
        for g in grids:
            ts = groups.get((g, "two_step"), [])
            os_ = groups.get((g, "one_step"), [])
            if ts and os_:
                ts_avg = np.mean([int(r["total_routing_bytes"]) for r in ts])
                os_avg = np.mean([int(r["total_routing_bytes"]) for r in os_])
                pcts.append((1 - os_avg / ts_avg) * 100)
            else:
                pcts.append(np.nan)

        ax.plot(nodes, pcts, ls, color=color, marker="o",
                linewidth=2, markersize=8, label=plat_label)

    ax.set_xlabel("Number of Nodes", fontsize=12)
    ax.set_ylabel("Traffic Reduction (%)", fontsize=12)
    ax.set_title("One-step Traffic Savings vs Two-step", fontsize=13, fontweight="bold")
    ax.axhline(0, color="gray", linewidth=0.8, linestyle=":")
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(nodes)

    path = os.path.join(out_dir, "scaling_savings_pct.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_breakdown_scaling(sim_rows, emu_rows, out_dir):
    """Stacked area: DV vs PrefixSync bytes, by mode, across grid sizes."""
    fig, axes = plt.subplots(2, 3, figsize=(18, 10))

    for pi, (rows, plat_label) in enumerate([
        (sim_rows, "Simulation"), (emu_rows, "Emulation"),
    ]):
        groups = group_by_grid_mode(rows)
        grids = sorted(set(int(r["grid_size"]) for r in rows))
        nodes = [g * g for g in grids]

        for mi, mode in enumerate(MODES):
            ax = axes[pi][mi]
            dv_vals, pfx_vals = [], []
            for g in grids:
                mode_rows = groups.get((g, mode), [])
                if mode_rows:
                    dv_vals.append(np.mean([int(r["dv_advert_bytes"]) for r in mode_rows]) / 1024)
                    pfx_vals.append(np.mean([int(r["pfxsync_bytes"]) for r in mode_rows]) / 1024)
                else:
                    dv_vals.append(0)
                    pfx_vals.append(0)

            ax.bar(nodes, dv_vals, width=[n * 0.15 for n in nodes],
                   color="#1f77b4", label="DV Advert")
            ax.bar(nodes, pfx_vals, width=[n * 0.15 for n in nodes],
                   bottom=dv_vals, color="#ff7f0e", label="PrefixSync")

            ax.set_xlabel("Nodes")
            if mi == 0:
                ax.set_ylabel(f"{plat_label}\nTraffic (KB)")
            ax.set_title(f"{plat_label}: {MODE_LABELS[mode]}")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3, axis="y")
            ax.set_xticks(nodes)

    fig.suptitle("DV vs PrefixSync Traffic Breakdown by Grid Size",
                 fontsize=14, fontweight="bold", y=1.01)
    path = os.path.join(out_dir, "scaling_breakdown.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_convergence_scaling(sim_rows, emu_rows, out_dir):
    """Convergence time vs nodes."""
    fig, ax = plt.subplots(figsize=(8, 5))

    for rows, plat_label, ls in [
        (sim_rows, "Simulation", "-"),
        (emu_rows, "Emulation", "--"),
    ]:
        groups = group_by_grid_mode(rows)
        grids = sorted(set(int(r["grid_size"]) for r in rows))
        nodes = [g * g for g in grids]

        for mode in MODES:
            vals = []
            for g in grids:
                mode_rows = groups.get((g, mode), [])
                if mode_rows:
                    vals.append(np.mean([float(r["convergence_s"]) for r in mode_rows]))
                else:
                    vals.append(np.nan)
            ax.plot(nodes, vals, ls, color=MODE_COLORS[mode],
                    marker=MODE_MARKERS[mode], linewidth=2, markersize=8,
                    label=f"{plat_label} {MODE_LABELS[mode]}")

    ax.set_xlabel("Number of Nodes", fontsize=12)
    ax.set_ylabel("Convergence Time (s)", fontsize=12)
    ax.set_title("DV Convergence Time Scaling", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9, ncol=2)
    ax.grid(True, alpha=0.3)
    ax.set_xticks(nodes)

    path = os.path.join(out_dir, "scaling_convergence.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def main():
    parser = argparse.ArgumentParser(description="Plot one-step vs two-step scaling")
    parser.add_argument("--sim-csv", default="results/onestep_medium/sim/comparison.csv")
    parser.add_argument("--emu-csv", default="results/onestep_medium/emu/comparison.csv")
    parser.add_argument("--out", default="results/onestep_medium/plots")
    args = parser.parse_args()

    sim_rows = load_csv(args.sim_csv)
    emu_rows = load_csv(args.emu_csv)
    os.makedirs(args.out, exist_ok=True)

    plot_total_bytes_scaling(sim_rows, emu_rows, args.out)
    plot_overhead_scaling(sim_rows, emu_rows, args.out)
    plot_savings_pct(sim_rows, emu_rows, args.out)
    plot_breakdown_scaling(sim_rows, emu_rows, args.out)
    plot_convergence_scaling(sim_rows, emu_rows, args.out)

    print(f"\nAll scaling plots saved to {args.out}/")


if __name__ == "__main__":
    main()
