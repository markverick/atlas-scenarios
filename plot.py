#!/usr/bin/env python3
"""
Plot scalability results from emulation and/or simulation CSV files.

Reads results/emu/scalability.csv and results/sim/scalability.csv
(if present) and produces comparison plots.

Usage:
  python3 plot.py
  python3 plot.py --emu results/emu/scalability.csv --sim results/sim/scalability.csv
  python3 plot.py --out results/plots
"""

import argparse
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_csv(path):
    """Load scalability CSV, returning rows grouped by grid_size."""
    if not os.path.isfile(path):
        return None
    groups = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            gs = int(row["grid_size"])
            groups.setdefault(gs, []).append(row)
    return groups


def aggregate(groups, field, cast=float):
    """Return (grid_sizes, means, stds) for a field."""
    sizes = sorted(groups.keys())
    means, stds = [], []
    for gs in sizes:
        vals = [cast(r[field]) for r in groups[gs] if cast(r[field]) >= 0]
        if vals:
            means.append(np.mean(vals))
            stds.append(np.std(vals))
        else:
            means.append(np.nan)
            stds.append(0)
    nodes = [gs * gs for gs in sizes]
    return nodes, means, stds


def plot_convergence(emu_data, sim_data, out_dir):
    fig, ax = plt.subplots(figsize=(8, 5))
    has_data = False

    if emu_data:
        nodes, means, stds = aggregate(emu_data, "convergence_s")
        ax.errorbar(nodes, means, yerr=stds, marker="o", capsize=4,
                    label="Emulation (Mini-NDN)")
        has_data = True

    if sim_data:
        nodes, means, stds = aggregate(sim_data, "convergence_s")
        ax.errorbar(nodes, means, yerr=stds, marker="s", capsize=4,
                    label="Simulation (ndndSIM)")
        has_data = True

    if not has_data:
        print("No data to plot for convergence.")
        return

    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("DV Convergence Time (s)")
    ax.set_title("NDNd DV Routing Convergence — Emulation vs Simulation")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "convergence.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_memory(emu_data, out_dir):
    if not emu_data:
        return
    nodes, means, stds = aggregate(emu_data, "avg_mem_kb")
    if all(np.isnan(m) for m in means):
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.errorbar(nodes, means, yerr=stds, marker="o", capsize=4, color="tab:green")
    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("Average NDNd RSS per Node (KB)")
    ax.set_title("NDNd Forwarder Memory Usage")
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "memory.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def main():
    parser = argparse.ArgumentParser(description="Plot scalability results")
    parser.add_argument("--emu", default="results/emu/scalability.csv",
                        help="Emulation CSV path")
    parser.add_argument("--sim", default="results/sim/scalability.csv",
                        help="Simulation CSV path")
    parser.add_argument("--out", default="results/plots",
                        help="Output directory for plots")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    emu_data = load_csv(args.emu)
    sim_data = load_csv(args.sim)

    if not emu_data and not sim_data:
        print("No result CSVs found. Run the scalability tests first.", file=sys.stderr)
        sys.exit(1)

    plot_convergence(emu_data, sim_data, args.out)
    plot_memory(emu_data, args.out)

    print(f"\nAll plots saved to {args.out}/")


if __name__ == "__main__":
    main()
