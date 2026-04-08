import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from .prefix_scale_data import bin_io, human_bytes, load_event_log, load_packet_trace, load_svs_suppression_dir


TRACE_CATEGORY_STYLES = {
    "DvAdvert": ("#4C72B0", "DV"),
    "PrefixSync": ("#C44E52", "PfxSync"),
}


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
    trace_index = _discover_trace_index(data_dir)
    prefix_counts = sorted({prefix_count for _, prefix_count in trace_index})
    if not prefix_counts:
        print("  No packet traces found, skipping IO plots")
        return

    fig, axes = plt.subplots(len(prefix_counts), 2, figsize=(10, 3 * len(prefix_counts)), squeeze=False, sharex=True)
    for col, mode in enumerate(["two_step", "one_step"]):
        for row, prefix_count in enumerate(prefix_counts):
            axis = axes[row][col]
            tag = trace_index.get((mode, prefix_count))
            if not tag:
                axis.text(0.5, 0.5, "No data", transform=axis.transAxes, ha="center", va="center")
                continue
            trace_path = os.path.join(data_dir, f"packet-trace-{tag}.csv")
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


def _discover_trace_index(data_dir, *, modes=("two_step", "one_step")):
    trace_index = {}
    pattern = re.compile(r"packet-trace-([a-z_]+)-.+-p(\d+)-.*\.csv$")
    for filename in os.listdir(data_dir):
        match = pattern.match(filename)
        if not match:
            continue
        mode = match.group(1)
        if mode not in modes:
            continue
        prefix_count = int(match.group(2))
        tag = filename[len("packet-trace-"):-len(".csv")]
        trace_index[(mode, prefix_count)] = tag
    return trace_index


def _plot_event_lines(axis, event_rows):
    seen = set()
    for row in event_rows:
        event = row["event"]
        label = event.replace("_", " ")
        color = "#c0392b" if "down" in event else "#2980b9"
        style = "--" if "down" in event else ":"
        show_label = label not in seen
        axis.axvline(
            row["time"],
            color=color,
            linestyle=style,
            linewidth=1.0,
            alpha=0.3,
            label=label if show_label else None,
        )
        seen.add(label)


def _plot_trace_io(axis, times, categories, sizes, event_rows, *, title, phase2_start=None):
    category_points = {category: ([], []) for category in TRACE_CATEGORY_STYLES}
    for point, category, size in zip(times, categories, sizes):
        if category not in category_points:
            continue
        category_points[category][0].append(point)
        category_points[category][1].append(size)

    for category, (color, label) in TRACE_CATEGORY_STYLES.items():
        edges, bins = bin_io(category_points[category][0], category_points[category][1])
        if edges:
            axis.step(edges, bins, where="mid", color=color, linewidth=1.6, label=label)

    if phase2_start is not None:
        axis.axvline(phase2_start, color="red", ls="--", lw=0.8, alpha=0.6, label="phase2")
    _plot_event_lines(axis, event_rows)
    axis.set_title(title)
    axis.set_xlabel("Time (s)")
    axis.set_ylabel("Traffic per 1s bin (bytes)")
    axis.yaxis.set_major_formatter(ticker.FuncFormatter(human_bytes))
    axis.grid(True, alpha=0.25)


def _plot_packet_cdf(axis, categories, sizes, *, title):
    total_sizes = []
    for category, (color, label) in TRACE_CATEGORY_STYLES.items():
        values = sorted(size for item_category, size in zip(categories, sizes) if item_category == category)
        if not values:
            continue
        total_sizes.extend(values)
        cdf_y = np.arange(1, len(values) + 1) / len(values)
        axis.plot(values, cdf_y, color=color, linewidth=1.5, label=label)

    if total_sizes:
        total_sizes = sorted(total_sizes)
        cdf_y = np.arange(1, len(total_sizes) + 1) / len(total_sizes)
        axis.plot(total_sizes, cdf_y, color="#222222", linewidth=2.0, label="Total")

    axis.set_title(title)
    axis.set_xlabel("Packet size (bytes)")
    axis.set_ylabel("CDF")
    axis.grid(True, alpha=0.25)


def plot_io_cdf_compare(sim_dir, emu_dir, out_dir, phase2_start=None):
    sim_index = _discover_trace_index(sim_dir)
    emu_index = _discover_trace_index(emu_dir)
    cases = []
    for key, sim_tag in sim_index.items():
        emu_tag = emu_index.get(key)
        if emu_tag:
            mode, prefix_count = key
            cases.append((mode, prefix_count, sim_tag, emu_tag))
    if not cases:
        print("  No shared packet traces found, skipping IO/CDF comparison plots")
        return

    detail_dir = os.path.join(out_dir, "trace_details")
    os.makedirs(detail_dir, exist_ok=True)

    for mode, prefix_count, sim_tag, emu_tag in sorted(cases, key=lambda item: (item[1], item[0])):
        sim_trace = os.path.join(sim_dir, f"packet-trace-{sim_tag}.csv")
        emu_trace = os.path.join(emu_dir, f"packet-trace-{emu_tag}.csv")
        sim_event = os.path.join(sim_dir, f"event-log-{sim_tag}.csv")
        emu_event = os.path.join(emu_dir, f"event-log-{emu_tag}.csv")

        sim_times, sim_categories, sim_sizes = load_packet_trace(sim_trace)
        emu_times, emu_categories, emu_sizes = load_packet_trace(emu_trace)
        sim_events = load_event_log(sim_event) if os.path.exists(sim_event) else []
        emu_events = load_event_log(emu_event) if os.path.exists(emu_event) else []

        fig, axes = plt.subplots(2, 2, figsize=(14, 8))
        mode_label = "Two-Step" if mode == "two_step" else "One-Step"
        prefix_label = f"p{prefix_count}"

        _plot_trace_io(axes[0, 0], sim_times, sim_categories, sim_sizes, sim_events,
                       title=f"Simulation {mode_label} {prefix_label} I/O", phase2_start=phase2_start)
        _plot_trace_io(axes[0, 1], emu_times, emu_categories, emu_sizes, emu_events,
                       title=f"Emulation {mode_label} {prefix_label} I/O", phase2_start=phase2_start)
        _plot_packet_cdf(axes[1, 0], sim_categories, sim_sizes,
                         title=f"Simulation {mode_label} {prefix_label} Packet CDF")
        _plot_packet_cdf(axes[1, 1], emu_categories, emu_sizes,
                         title=f"Emulation {mode_label} {prefix_label} Packet CDF")

        for axis in axes.flat:
            handles, labels = axis.get_legend_handles_labels()
            if handles:
                unique = {}
                for handle, label in zip(handles, labels):
                    unique.setdefault(label, handle)
                axis.legend(unique.values(), unique.keys(), fontsize=8, loc="best")

        fig.tight_layout()
        path = os.path.join(detail_dir, f"io-cdf-{mode}-p{prefix_count}.png")
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


def plot_svs_suppression_compare(sim_data_dir, emu_data_dir, out_dir):
    sim_data = load_svs_suppression_dir(sim_data_dir)
    emu_data = load_svs_suppression_dir(emu_data_dir)
    prefix_counts = sorted(set(sim_data) | set(emu_data))
    if not prefix_counts:
        return

    metrics = [
        ("enter", "Suppress Enter"),
        ("ok", "Suppress OK"),
        ("fail", "Suppress Fail"),
        ("unresolved", "Unresolved"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
    axes = axes.flatten()

    for axis, (metric, title) in zip(axes, metrics):
        sim_values = [sim_data.get(prefix_count, {}).get("aggregate", {}).get(metric, 0) for prefix_count in prefix_counts]
        emu_values = [emu_data.get(prefix_count, {}).get("aggregate", {}).get(metric, 0) for prefix_count in prefix_counts]

        axis.plot(prefix_counts, sim_values, "o-", label="Simulation", color="#4C72B0", linewidth=2)
        axis.plot(prefix_counts, emu_values, "s-", label="Emulation", color="#DD8452", linewidth=2)
        axis.set_title(title)
        axis.set_ylabel("Count")
        axis.grid(True, alpha=0.25)
        axis.set_xticks(prefix_counts)

    for axis in axes[-2:]:
        axis.set_xlabel("Number of Prefixes")
    axes[0].legend()
    fig.suptitle("SVS Suppression During Churn", fontsize=13, y=0.98)
    fig.tight_layout()
    path = os.path.join(out_dir, "svs_suppression_compare.png")
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"  Saved {path}")