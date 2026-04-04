import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from .prefix_scale_data import bin_io, human_bytes, load_packet_trace


def plot_churn_comparison(rows, out_dir, source_label):
    churn = [row for row in rows if row["phase"] == "churn" and row["mode"] != "baseline"]
    prefix_counts = sorted(set(int(row["num_prefixes"]) for row in churn))
    x_values = np.arange(len(prefix_counts))
    width = 0.35
    fig, axis = plt.subplots(figsize=(8, 5))
    for index, mode in enumerate(["two_step", "one_step"]):
        values = []
        for prefix_count in prefix_counts:
            match = [row for row in churn if row["mode"] == mode and int(row["num_prefixes"]) == prefix_count]
            values.append(int(match[0]["total_routing_bytes"]) if match else 0)
        axis.bar(
            x_values + (index - 0.5) * width,
            values,
            width,
            label="Two-step (DV + PfxSync)" if mode == "two_step" else "One-step (DV only)",
            color="#4C72B0" if mode == "two_step" else "#DD8452",
        )
    axis.set_xlabel("Number of Prefixes")
    axis.set_ylabel("Churn-Phase Routing Bytes")
    axis.set_xticks(x_values)
    axis.set_xticklabels([str(value) for value in prefix_counts])
    axis.yaxis.set_major_formatter(ticker.FuncFormatter(human_bytes))
    axis.legend()
    axis.set_title(f"{source_label}: Churn Overhead")
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_comparison.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


def plot_churn_breakdown(rows, out_dir, source_label):
    churn = [row for row in rows if row["phase"] == "churn" and row["mode"] != "baseline"]
    prefix_counts = sorted(set(int(row["num_prefixes"]) for row in churn))
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for axis, mode in zip(axes, ["two_step", "one_step"]):
        dv_values, prefix_sync_values = [], []
        for prefix_count in prefix_counts:
            match = [row for row in churn if row["mode"] == mode and int(row["num_prefixes"]) == prefix_count]
            if match:
                dv_values.append(int(match[0]["dv_advert_bytes"]))
                prefix_sync_values.append(int(match[0]["pfxsync_bytes"]))
            else:
                dv_values.append(0)
                prefix_sync_values.append(0)
        x_values = np.arange(len(prefix_counts))
        axis.bar(x_values, dv_values, label="DV Adverts", color="#4C72B0")
        axis.bar(x_values, prefix_sync_values, bottom=dv_values, label="PrefixSync", color="#C44E52")
        axis.set_xlabel("Number of Prefixes")
        axis.set_xticks(x_values)
        axis.set_xticklabels([str(value) for value in prefix_counts])
        axis.yaxis.set_major_formatter(ticker.FuncFormatter(human_bytes))
        axis.legend()
        axis.set_title(f"{source_label} - {'Two-Step' if mode == 'two_step' else 'One-Step'} Traffic Breakdown")
    axes[0].set_ylabel("Churn-Phase Routing Bytes")
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_breakdown.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


def plot_io_per_variant(data_dir, out_dir, source_label, phase2_start=None):
    # Auto-detect phase2_start from churn.csv if not given
    if phase2_start is None:
        csv_path = os.path.join(data_dir, "churn.csv")
        if os.path.exists(csv_path):
            import csv as _csv
            with open(csv_path) as _f:
                for row in _csv.DictReader(_f):
                    phase2_start = float(row["phase2_start"])
                    break
        if phase2_start is None:
            phase2_start = 10.0
    prefix_counts = set()
    for filename in os.listdir(data_dir):
        match = re.match(r"packet-trace-(two_step|one_step)-.*-p(\d+)-t\d+\.csv", filename)
        if match:
            prefix_counts.add(int(match.group(2)))
    prefix_counts = sorted(prefix_counts)
    if not prefix_counts:
        print("  No packet traces found, skipping IO plots")
        return

    fig, axes = plt.subplots(len(prefix_counts), 2, figsize=(10, 3 * len(prefix_counts)), squeeze=False, sharex=True)
    for col, mode in enumerate(["two_step", "one_step"]):
        for row, prefix_count in enumerate(prefix_counts):
            axis = axes[row][col]
            trace_path = os.path.join(data_dir, f"packet-trace-{mode}-sprint-p{prefix_count}-t1.csv")
            if not os.path.exists(trace_path):
                axis.text(0.5, 0.5, "No data", transform=axis.transAxes, ha="center", va="center")
                continue
            times, categories, sizes = load_packet_trace(trace_path)
            dv_times, dv_sizes, ps_times, ps_sizes = [], [], [], []
            for point, category, size in zip(times, categories, sizes):
                if category == "DvAdvert":
                    dv_times.append(point)
                    dv_sizes.append(size)
                elif category == "PrefixSync":
                    ps_times.append(point)
                    ps_sizes.append(size)
            dv_edges, dv_bins = bin_io(dv_times, dv_sizes)
            ps_edges, ps_bins = bin_io(ps_times, ps_sizes)
            if dv_edges:
                axis.fill_between(dv_edges, dv_bins, alpha=0.7, label="DV", color="#4C72B0", step="mid")
            if ps_edges:
                axis.fill_between(ps_edges, ps_bins, alpha=0.7, label="PfxSync", color="#C44E52", step="mid")
            axis.axvline(phase2_start, color="red", ls="--", lw=0.8, alpha=0.6)
            axis.yaxis.set_major_formatter(ticker.FuncFormatter(human_bytes))
            if row == 0:
                axis.set_title("Two-Step" if mode == "two_step" else "One-Step")
            if col == 0:
                axis.set_ylabel(f"p{prefix_count}")
            if row == len(prefix_counts) - 1:
                axis.set_xlabel("Time (s)")
            if row == 0 and col == 1:
                axis.legend(fontsize=7, loc="upper right")
    fig.suptitle(f"{source_label} - Routing I/O per Variant (1s bins)", fontsize=13, y=1.01)
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_io_grid.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {path}")


def plot_net_overhead(rows, out_dir, source_label):
    baseline = [row for row in rows if row["mode"] == "baseline" and row["phase"] == "churn"]
    if not baseline:
        return
    baseline_bytes = int(baseline[0]["total_routing_bytes"])
    churn = [row for row in rows if row["phase"] == "churn" and row["mode"] != "baseline"]
    prefix_counts = sorted(set(int(row["num_prefixes"]) for row in churn))
    fig, axis = plt.subplots(figsize=(8, 5))
    for mode, color in [("two_step", "#4C72B0"), ("one_step", "#DD8452")]:
        values = []
        for prefix_count in prefix_counts:
            match = [row for row in churn if row["mode"] == mode and int(row["num_prefixes"]) == prefix_count]
            value = int(match[0]["total_routing_bytes"]) - baseline_bytes if match else 0
            values.append(max(value, 0))
        axis.plot(prefix_counts, values, "o-", label="Two-step" if mode == "two_step" else "One-step", color=color, linewidth=2)
    axis.set_xlabel("Number of Prefixes")
    axis.set_ylabel("Net Churn Overhead (total - baseline)")
    axis.yaxis.set_major_formatter(ticker.FuncFormatter(human_bytes))
    axis.legend()
    axis.set_title(f"{source_label}: Prefix-Scaling Overhead (Baseline Subtracted)")
    axis.set_xticks(prefix_counts)
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_net_overhead.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


def plot_raw_overhead(rows, out_dir, source_label):
    churn = [row for row in rows if row["phase"] == "churn" and row["mode"] != "baseline"]
    prefix_counts = sorted(set(int(row["num_prefixes"]) for row in churn))
    baseline = [row for row in rows if row["mode"] == "baseline" and row["phase"] == "churn"]
    fig, axis = plt.subplots(figsize=(8, 5))
    for mode, color in [("two_step", "#4C72B0"), ("one_step", "#DD8452")]:
        values = []
        for prefix_count in prefix_counts:
            match = [row for row in churn if row["mode"] == mode and int(row["num_prefixes"]) == prefix_count]
            values.append(int(match[0]["total_routing_bytes"]) if match else 0)
        axis.plot(prefix_counts, values, "o-", label="Two-step" if mode == "two_step" else "One-step", color=color, linewidth=2)
    if baseline:
        value = int(baseline[0]["total_routing_bytes"])
        axis.axhline(value, color="gray", ls="--", lw=1, alpha=0.7, label=f"Baseline ({human_bytes(value)})")
    axis.set_xlabel("Number of Prefixes")
    axis.set_ylabel("Churn-Phase Routing Bytes")
    axis.yaxis.set_major_formatter(ticker.FuncFormatter(human_bytes))
    axis.legend()
    axis.set_title(f"{source_label}: Total Routing Overhead")
    axis.set_xticks(prefix_counts)
    fig.tight_layout()
    path = os.path.join(out_dir, "prefix_scale_raw_overhead.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")


def plot_sim_vs_emu(sim_rows, emu_rows, out_dir):
    for mode, title in [("two_step", "Two-Step"), ("one_step", "One-Step")]:
        sim_churn = [row for row in sim_rows if row["phase"] == "churn" and row["mode"] == mode]
        emu_churn = [row for row in emu_rows if row["phase"] == "churn" and row["mode"] == mode]
        prefix_counts = sorted(set([int(row["num_prefixes"]) for row in sim_churn] + [int(row["num_prefixes"]) for row in emu_churn]))
        if not prefix_counts:
            continue
        fig, axis = plt.subplots(figsize=(8, 5))
        for label, rows, color, marker in [("Simulation", sim_churn, "#4C72B0", "o"), ("Emulation", emu_churn, "#DD8452", "s")]:
            x_values, y_values = [], []
            for prefix_count in prefix_counts:
                match = [row for row in rows if int(row["num_prefixes"]) == prefix_count]
                if match:
                    x_values.append(prefix_count)
                    y_values.append(int(match[0]["total_routing_bytes"]))
            if y_values:
                axis.plot(x_values, y_values, f"{marker}-", label=label, color=color, linewidth=2)
        axis.set_xlabel("Number of Prefixes")
        axis.set_ylabel("Churn-Phase Routing Bytes")
        axis.yaxis.set_major_formatter(ticker.FuncFormatter(human_bytes))
        axis.legend()
        axis.set_title(f"{title}: Simulation vs Emulation")
        axis.set_xticks(prefix_counts)
        fig.tight_layout()
        path = os.path.join(out_dir, f"sim_vs_emu_{mode}.png")
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"  Saved {path}")