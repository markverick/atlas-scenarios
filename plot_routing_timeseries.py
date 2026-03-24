#!/usr/bin/env python3
"""
Wireshark-style per-packet time-series plot for routing-only traffic.

Reads per-packet data from:
  - SIM: packet-trace-routing-NxN-t1.csv (from NdndLinkTracer per-packet mode)
  - EMU: pcap-manifest-routing-NxN-t1.json → pcap files (raw per-packet data)

Produces scatter + cumulative-bytes plots with true per-packet timestamps.

Usage:
  python3 plot_routing_timeseries.py
  python3 plot_routing_timeseries.py --sim-dir results/sim_routing \
                                     --emu-dir results/emu_routing \
                                     --grid 3
"""

import argparse
import csv
import glob
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from lib.pcap import parse_pcap_packets


def load_sim_packets(sim_dir, grid_size, trial=1):
    """Load per-packet events from sim packet-trace CSV.

    Returns list of (time_s, category, bytes).
    """
    tag = f"routing-{grid_size}x{grid_size}-t{trial}"
    path = os.path.join(sim_dir, f"packet-trace-{tag}.csv")
    if not os.path.isfile(path):
        return None
    events = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            events.append((
                float(row["Time"]),
                row["Category"],
                int(row["Bytes"]),
            ))
    return events


def load_emu_packets(emu_dir, grid_size, trial=1):
    """Load per-packet events from emu pcap files via manifest.

    Returns list of (time_s, category, bytes) with time relative to origin.
    """
    tag = f"routing-{grid_size}x{grid_size}-t{trial}"
    manifest_path = os.path.join(emu_dir, f"pcap-manifest-{tag}.json")
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path) as f:
        manifest = json.load(f)
    pcap_paths = manifest["pcap_paths"]
    dv_start = manifest.get("dv_start")
    events = parse_pcap_packets(pcap_paths, time_origin=dv_start)
    return events


def plot_packet_scatter(sim_events, emu_events, grid_size, out_dir):
    """Scatter plot: each dot is one packet, x=time, y=packet size."""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    for ax, events, label, color in [
        (axes[0], sim_events, "Simulation (ndndSIM)", "tab:orange"),
        (axes[1], emu_events, "Emulation (Mini-NDN)", "tab:blue"),
    ]:
        if events is None:
            ax.text(0.5, 0.5, "No data", ha="center", va="center",
                    transform=ax.transAxes, fontsize=14, color="gray")
            ax.set_ylabel("Packet Size (bytes)")
            ax.set_title(label)
            continue
        times = [e[0] for e in events]
        sizes = [e[2] for e in events]
        ax.scatter(times, sizes, s=4, alpha=0.5, color=color, edgecolors="none")
        ax.set_ylabel("Packet Size (bytes)")
        ax.set_title(f"{label}  ({len(events)} packets)")
        ax.grid(True, alpha=0.3)

    axes[1].set_xlabel("Time (s)")
    fig.suptitle(f"Routing-Only Traffic: Per-Packet View ({grid_size}x{grid_size} grid)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    path = os.path.join(out_dir, f"routing_timeseries_scatter_{grid_size}x{grid_size}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_cumulative_bytes(sim_events, emu_events, grid_size, out_dir):
    """Cumulative bytes over time — like Wireshark IO graph in cumulative mode."""
    fig, ax = plt.subplots(figsize=(12, 6))

    for events, label, color, ls in [
        (sim_events, "Simulation (ndndSIM)", "tab:orange", "-"),
        (emu_events, "Emulation (Mini-NDN)", "tab:blue", "-"),
    ]:
        if events is None:
            continue
        times = np.array([e[0] for e in events])
        sizes = np.array([e[2] for e in events])
        cum = np.cumsum(sizes)
        ax.step(times, cum / 1024, where="post", label=label, color=color,
                linestyle=ls, linewidth=1.5)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Cumulative DV Traffic (KB)")
    ax.set_title(f"Routing-Only: Cumulative Traffic ({grid_size}x{grid_size} grid)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path = os.path.join(out_dir, f"routing_timeseries_cumulative_{grid_size}x{grid_size}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_packet_rate(sim_events, emu_events, grid_size, out_dir, bin_ms=10):
    """Packet rate over time — like Wireshark IO graph (packets/interval)."""
    fig, ax = plt.subplots(figsize=(12, 6))
    bin_s = bin_ms / 1000.0

    for events, label, color in [
        (sim_events, "Simulation (ndndSIM)", "tab:orange"),
        (emu_events, "Emulation (Mini-NDN)", "tab:blue"),
    ]:
        if events is None:
            continue
        times = np.array([e[0] for e in events])
        if len(times) == 0:
            continue
        t_max = max(times.max(), 1.0)
        # Focus on first 2 seconds or convergence window
        t_max = min(t_max, max(2.0, np.percentile(times, 99.5) * 1.2))
        bins = np.arange(0, t_max + bin_s, bin_s)
        counts, edges = np.histogram(times, bins=bins)
        centers = (edges[:-1] + edges[1:]) / 2
        ax.step(centers, counts, where="mid", label=label, color=color,
                linewidth=1.2, alpha=0.85)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel(f"Packets / {bin_ms}ms")
    ax.set_title(f"Routing-Only: Packet Rate ({grid_size}x{grid_size} grid)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path = os.path.join(out_dir, f"routing_timeseries_rate_{grid_size}x{grid_size}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def plot_bytes_rate(sim_events, emu_events, grid_size, out_dir, bin_ms=10):
    """Bytes/interval over time — like Wireshark IO graph (bytes mode)."""
    fig, ax = plt.subplots(figsize=(12, 6))
    bin_s = bin_ms / 1000.0

    for events, label, color in [
        (sim_events, "Simulation (ndndSIM)", "tab:orange"),
        (emu_events, "Emulation (Mini-NDN)", "tab:blue"),
    ]:
        if events is None:
            continue
        times = np.array([e[0] for e in events])
        sizes = np.array([e[2] for e in events])
        if len(times) == 0:
            continue
        t_max = max(times.max(), 1.0)
        t_max = min(t_max, max(2.0, np.percentile(times, 99.5) * 1.2))
        bins = np.arange(0, t_max + bin_s, bin_s)
        byte_sums, edges = np.histogram(times, bins=bins, weights=sizes)
        centers = (edges[:-1] + edges[1:]) / 2
        ax.step(centers, byte_sums / 1024, where="mid", label=label,
                color=color, linewidth=1.2, alpha=0.85)

    ax.set_xlabel("Time (s)")
    ax.set_ylabel(f"Traffic (KB / {bin_ms}ms)")
    ax.set_title(f"Routing-Only: Traffic Rate ({grid_size}x{grid_size} grid)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path = os.path.join(out_dir, f"routing_timeseries_byterate_{grid_size}x{grid_size}.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Wireshark-style per-packet time-series routing traffic plots")
    parser.add_argument("--sim-dir", default="results/sim_routing")
    parser.add_argument("--emu-dir", default="results/emu_routing")
    parser.add_argument("--out", default="results/plots")
    parser.add_argument("--grids", nargs="+", type=int, default=None,
                        help="Grid sizes to plot (default: auto-detect)")
    parser.add_argument("--trial", type=int, default=1)
    parser.add_argument("--bin-ms", type=int, default=10,
                        help="Bin width for rate plots in ms (default: 10)")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    # Auto-detect grid sizes from available files
    if args.grids is None:
        grids = set()
        for d in [args.sim_dir, args.emu_dir]:
            for f in glob.glob(os.path.join(d, "packet-trace-routing-*x*-t*.csv")):
                m = os.path.basename(f).split("-")
                for part in m:
                    if "x" in part and part[0].isdigit():
                        grids.add(int(part.split("x")[0]))
            for f in glob.glob(os.path.join(d, "pcap-manifest-routing-*x*-t*.json")):
                m = os.path.basename(f).split("-")
                for part in m:
                    if "x" in part and part[0].isdigit():
                        grids.add(int(part.split("x")[0]))
        grids = sorted(grids) if grids else [2, 3]
        print(f"Auto-detected grid sizes: {grids}")

    for grid_size in args.grids or grids:
        print(f"\n--- Grid {grid_size}x{grid_size} ---")
        sim = load_sim_packets(args.sim_dir, grid_size, args.trial)
        emu = load_emu_packets(args.emu_dir, grid_size, args.trial)

        if sim is None and emu is None:
            print(f"  No data for grid {grid_size}x{grid_size}, skipping")
            continue

        if sim is not None:
            print(f"  SIM: {len(sim)} packets, "
                  f"span {sim[-1][0]:.4f}s" if sim else "  SIM: 0 packets")
        if emu is not None:
            print(f"  EMU: {len(emu)} packets, "
                  f"span {emu[-1][0]:.4f}s" if emu else "  EMU: 0 packets")

        plot_packet_scatter(sim, emu, grid_size, args.out)
        plot_cumulative_bytes(sim, emu, grid_size, args.out)
        plot_packet_rate(sim, emu, grid_size, args.out, bin_ms=args.bin_ms)
        plot_bytes_rate(sim, emu, grid_size, args.out, bin_ms=args.bin_ms)

    print(f"\nAll time-series plots saved to {args.out}/")


if __name__ == "__main__":
    main()
