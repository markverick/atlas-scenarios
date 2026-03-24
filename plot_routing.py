#!/usr/bin/env python3
"""
Plot routing-only traffic results — DV packet counts, traffic volume,
and convergence time across grid sizes (emu vs sim).

Reads results/emu_routing/scalability.csv and/or
results/sim_routing/scalability.csv and produces three plots:
  - routing_convergence.png  — DV convergence time vs nodes
  - routing_packets.png      — DV packet count vs nodes
  - routing_bytes.png        — DV traffic volume (KB) vs nodes

Usage:
  python3 plot_routing.py
  python3 plot_routing.py --emu results/emu_routing/scalability.csv \
                          --sim results/sim_routing/scalability.csv
"""

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from plot import load_csv, aggregate


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
        return

    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("DV Convergence Time (s)")
    ax.set_title("Routing-Only: DV Convergence Time")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "routing_convergence.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_packets(emu_data, sim_data, out_dir):
    fig, ax = plt.subplots(figsize=(8, 5))
    has_data = False

    if emu_data:
        nodes, means, stds = aggregate(emu_data, "dv_packets", cast=int)
        if not all(np.isnan(m) for m in means):
            ax.errorbar(nodes, means, yerr=stds, marker="o", capsize=4,
                        label="Emulation (Mini-NDN)")
            has_data = True

    if sim_data:
        nodes, means, stds = aggregate(sim_data, "dv_packets", cast=int)
        if not all(np.isnan(m) for m in means):
            ax.errorbar(nodes, means, yerr=stds, marker="s", capsize=4,
                        label="Simulation (ndndSIM)")
            has_data = True

    if not has_data:
        return

    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("DV Routing Packets")
    ax.set_title("Routing-Only: DV Packet Count")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "routing_packets.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_bytes(emu_data, sim_data, out_dir):
    fig, ax = plt.subplots(figsize=(8, 5))
    has_data = False

    if emu_data:
        nodes, means, stds = aggregate(emu_data, "dv_bytes", cast=int)
        if not all(np.isnan(m) for m in means):
            ax.errorbar(nodes, [m / 1024 for m in means],
                        yerr=[s / 1024 for s in stds],
                        marker="o", capsize=4,
                        label="Emulation (Mini-NDN)")
            has_data = True

    if sim_data:
        nodes, means, stds = aggregate(sim_data, "dv_bytes", cast=int)
        if not all(np.isnan(m) for m in means):
            ax.errorbar(nodes, [m / 1024 for m in means],
                        yerr=[s / 1024 for s in stds],
                        marker="s", capsize=4,
                        label="Simulation (ndndSIM)")
            has_data = True

    if not has_data:
        return

    ax.set_xlabel("Number of Nodes")
    ax.set_ylabel("DV Routing Traffic (KB)")
    ax.set_title("Routing-Only: DV Traffic Volume")
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(out_dir, "routing_bytes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def main():
    parser = argparse.ArgumentParser(description="Plot routing-only traffic results")
    parser.add_argument("--emu", default="results/emu_routing/scalability.csv")
    parser.add_argument("--sim", default="results/sim_routing/scalability.csv")
    parser.add_argument("--out", default="results/plots")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    emu_data = load_csv(args.emu)
    sim_data = load_csv(args.sim)

    if not emu_data and not sim_data:
        print("No routing result CSVs found. Run the routing scenario first.",
              file=sys.stderr)
        sys.exit(1)

    plot_convergence(emu_data, sim_data, args.out)
    plot_packets(emu_data, sim_data, args.out)
    plot_bytes(emu_data, sim_data, args.out)

    print(f"\nAll routing plots saved to {args.out}/")


if __name__ == "__main__":
    main()
