#!/usr/bin/env python3

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


TRACE_CATEGORIES = ("DvAdvert", "PrefixSync", "Mgmt")
TRACE_COLORS = {
    "DvAdvert": "#e67e22",
    "PrefixSync": "#16a085",
    "Mgmt": "#34495e",
    "Total": "#111111",
}


def load_churn_csv(path):
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path) as handle:
        for row in csv.DictReader(handle):
            row["grid_size"] = int(row["grid_size"])
            row["num_nodes"] = int(row["num_nodes"])
            row["num_links"] = int(row["num_links"])
            row["num_prefixes"] = int(row["num_prefixes"])
            row["num_churn_links"] = int(row.get("num_churn_links") or 0)
            row["link_mean_time_to_fail_s"] = float(row.get("link_mean_time_to_fail_s") or 0.0)
            row["link_mean_time_to_recover_s"] = float(row.get("link_mean_time_to_recover_s") or 0.0)
            row["window_s"] = float(row["window_s"])
            row["phase2_start"] = float(row["phase2_start"])
            row["convergence_s"] = float(row["convergence_s"])
            for key in (
                "dv_advert_pkts",
                "dv_advert_bytes",
                "pfxsync_pkts",
                "pfxsync_bytes",
                "mgmt_pkts",
                "mgmt_bytes",
                "total_routing_pkts",
                "total_routing_bytes",
            ):
                row[key] = int(row[key])
            rows.append(row)
    return rows


def load_packet_trace(path):
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path) as handle:
        for row in csv.DictReader(handle):
            rows.append({
                "time": float(row["Time"]),
                "category": row["Category"],
                "bytes": int(row["Bytes"]),
            })
    return rows


def load_event_log(path):
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path) as handle:
        for row in csv.DictReader(handle):
            try:
                when = float(row["Time"])
            except ValueError:
                continue
            rows.append({
                "time": when,
                "event": row["Event"],
                "details": row.get("Details", ""),
            })
    return rows


def _trace_tags(trace_dir):
    if not trace_dir or not os.path.isdir(trace_dir):
        return []
    tags = []
    prefix = "packet-trace-"
    suffix = ".csv"
    for name in sorted(os.listdir(trace_dir)):
        if name.startswith(prefix) and name.endswith(suffix):
            tags.append(name[len(prefix):-len(suffix)])
    return tags


def _load_case_trace(trace_dir, tag):
    packet_rows = load_packet_trace(os.path.join(trace_dir, f"packet-trace-{tag}.csv"))
    event_rows = load_event_log(os.path.join(trace_dir, f"event-log-{tag}.csv"))
    return packet_rows, event_rows


def _time_bounds(packet_rows, event_rows):
    values = [row["time"] for row in packet_rows]
    values.extend(row["time"] for row in event_rows)
    if not values:
        return 0.0, 1.0
    start = min(values)
    end = max(values)
    if end <= start:
        end = start + 1.0
    return start, end


def _build_trace_bins(packet_rows, start, end, *, bin_width=0.5):
    if end <= start:
        end = start + bin_width
    edges = np.arange(start, end + bin_width, bin_width)
    if len(edges) < 2:
        edges = np.array([start, start + bin_width])
    centers = edges[:-1] + bin_width / 2.0
    data = {category: np.zeros(len(centers)) for category in TRACE_CATEGORIES}
    for row in packet_rows:
        category = row["category"]
        if category not in data:
            continue
        idx = np.searchsorted(edges, row["time"], side="right") - 1
        idx = max(0, min(idx, len(centers) - 1))
        data[category][idx] += row["bytes"] / 1024.0
    return centers, data


def _plot_event_lines(ax, event_rows):
    seen = set()
    for row in event_rows:
        when = row["time"]
        event = row["event"]
        color = "#c0392b" if "down" in event else "#2980b9"
        style = "--" if "down" in event else ":"
        label = event.replace("_", " ")
        show_label = label not in seen
        ax.axvline(when, color=color, linestyle=style, linewidth=1.0, alpha=0.35,
                   label=label if show_label else None)
        seen.add(label)


def _plot_trace_timeseries(ax, packet_rows, event_rows, *, title):
    start, end = _time_bounds(packet_rows, event_rows)
    centers, data = _build_trace_bins(packet_rows, start, end)
    for category in TRACE_CATEGORIES:
        ax.plot(
            centers,
            data[category],
            color=TRACE_COLORS[category],
            linewidth=1.6,
            label=category,
        )
    _plot_event_lines(ax, event_rows)
    ax.set_title(title)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Traffic per 0.5s bin (KB)")
    ax.grid(True, alpha=0.25)


def _plot_trace_cdf(ax, packet_rows, event_rows, *, title):
    rows = [row for row in packet_rows if row["category"] in TRACE_CATEGORIES]
    rows.sort(key=lambda row: row["time"])
    cumulative = {category: 0.0 for category in TRACE_CATEGORIES}
    xs = []
    ys = {category: [] for category in TRACE_CATEGORIES}
    total = []
    total_bytes = 0.0
    for row in rows:
        xs.append(row["time"])
        kb = row["bytes"] / 1024.0
        cumulative[row["category"]] += kb
        total_bytes += kb
        total.append(total_bytes)
        for category in TRACE_CATEGORIES:
            ys[category].append(cumulative[category])

    if xs:
        for category in TRACE_CATEGORIES:
            ax.plot(xs, ys[category], color=TRACE_COLORS[category], linewidth=1.5, label=category)
        ax.plot(xs, total, color=TRACE_COLORS["Total"], linewidth=2.0, label="Total")
    _plot_event_lines(ax, event_rows)
    ax.set_title(title)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Cumulative routing bytes (KB)")
    ax.grid(True, alpha=0.25)


def plot_trace_details(sim_dir, emu_dir, out_dir):
    detail_dir = os.path.join(out_dir, "trace_details")
    os.makedirs(detail_dir, exist_ok=True)

    tags = sorted(set(_trace_tags(sim_dir)) | set(_trace_tags(emu_dir)))
    for tag in tags:
        sim_packets, sim_events = _load_case_trace(sim_dir, tag)
        emu_packets, emu_events = _load_case_trace(emu_dir, tag)
        if not sim_packets and not emu_packets:
            continue

        fig, axes = plt.subplots(2, 2, figsize=(16, 9), sharex="col")
        _plot_trace_timeseries(axes[0, 0], sim_packets, sim_events, title="Simulation traffic over time")
        _plot_trace_cdf(axes[1, 0], sim_packets, sim_events, title="Simulation cumulative traffic")
        _plot_trace_timeseries(axes[0, 1], emu_packets, emu_events, title="Emulation traffic over time")
        _plot_trace_cdf(axes[1, 1], emu_packets, emu_events, title="Emulation cumulative traffic")

        for ax in axes.flat:
            handles, labels = ax.get_legend_handles_labels()
            if handles:
                unique = {}
                for handle, label in zip(handles, labels):
                    unique.setdefault(label, handle)
                ax.legend(unique.values(), unique.keys(), fontsize=8, loc="upper left")

        fig.suptitle(f"Routing trace detail: {tag}", fontsize=14)
        fig.tight_layout()
        out = os.path.join(detail_dir, f"trace-detail-{tag}.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
        print(f"  Saved {out}")


def is_link_scale_sweep(rows):
    if not rows:
        return False
    counts = {row["num_churn_links"] for row in rows}
    rate_pairs = {
        (row["link_mean_time_to_fail_s"], row["link_mean_time_to_recover_s"])
        for row in rows
    }
    return len(counts) > 1 or len(rate_pairs) > 1


def _link_scale_axis(rows):
    counts = sorted({row["num_churn_links"] for row in rows if row["phase"] == "churn"})
    if len(counts) > 1:
        return "count", counts

    rate_pairs = sorted({
        (row["link_mean_time_to_fail_s"], row["link_mean_time_to_recover_s"])
        for row in rows if row["phase"] == "churn"
    })
    if len(rate_pairs) > 1:
        return "rate", rate_pairs

    return "count", counts or [0]


def _prefix_axis(rows):
    values = sorted({row["num_prefixes"] for row in rows if row["phase"] == "churn" and row["mode"] != "baseline"})
    if values:
        return values
    baseline_values = sorted({row["num_prefixes"] for row in rows if row["phase"] == "churn"})
    return baseline_values or [0]


def _rows_for_prefix(rows, prefix_count):
    return [
        row for row in rows
        if row["phase"] == "churn"
        and (row["mode"] == "baseline" or row["num_prefixes"] == prefix_count)
    ]


def plot_link_scale_compare(sim_rows, emu_rows, out_dir):
    mode_styles = {
        "baseline": ("#999999", "o-"),
        "two_step": ("#e74c3c", "s-"),
        "one_step": ("#2ecc71", "^-"),
    }

    prefix_counts = _prefix_axis(sim_rows or emu_rows)
    for prefix_count in prefix_counts:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
        for ax, rows, title in ((axes[0], sim_rows, "Simulation"), (axes[1], emu_rows, "Emulation")):
            prefix_rows = _rows_for_prefix(rows, prefix_count)
            if not prefix_rows:
                ax.set_title(f"{title} (no data)")
                continue

            axis_kind, axis_values = _link_scale_axis(prefix_rows)
            for mode, (color, style) in mode_styles.items():
                points = []
                if axis_kind == "count":
                    for link_count in axis_values:
                        match = [
                            row for row in prefix_rows
                            if row["mode"] == mode
                            and row["num_churn_links"] == link_count
                        ]
                        if match:
                            points.append((link_count, match[0]["total_routing_bytes"] / 1024.0))
                else:
                    for index, (mttf, mttr) in enumerate(axis_values):
                        match = [
                            row for row in prefix_rows
                            if row["mode"] == mode
                            and row["link_mean_time_to_fail_s"] == mttf
                            and row["link_mean_time_to_recover_s"] == mttr
                        ]
                        if match:
                            points.append((index, match[0]["total_routing_bytes"] / 1024.0))
                if points:
                    ax.plot(
                        [x for x, _ in points],
                        [y for _, y in points],
                        style,
                        color=color,
                        linewidth=2,
                        label=mode.replace("_", " "),
                    )

            if axis_kind == "count":
                ax.set_xlabel("Churned Links")
                ax.set_xticks(axis_values)
            else:
                ax.set_xlabel("Per-Link Churn Rate")
                ax.set_xticks(list(range(len(axis_values))))
                ax.set_xticklabels(
                    [f"F={mttf:g}\nR={mttr:g}" for mttf, mttr in axis_values],
                    fontsize=8,
                )
            ax.set_title(f"{title} (p={prefix_count})")
            ax.grid(True, alpha=0.3)
            ax.legend()

        axes[0].set_ylabel("Churn-Phase Routing Traffic (KB)")
        fig.suptitle(
            f"Independent Link Churn Sweep at p={prefix_count}: Baseline vs Two-Step vs One-Step",
            fontsize=13,
        )
        fig.tight_layout()
        if len(prefix_counts) == 1:
            out = os.path.join(out_dir, "link_scale_churn_compare.png")
        else:
            out = os.path.join(out_dir, f"link_scale_churn_compare_p{prefix_count}.png")
        fig.savefig(out, dpi=150)
        plt.close(fig)
        print(f"  Saved {out}")


def plot_phase_bars(sim_rows, emu_rows, out_dir):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    colors = {"baseline": "#999999", "two_step": "#e74c3c", "one_step": "#2ecc71"}
    phases = ["convergence", "churn"]
    modes = ["baseline", "two_step", "one_step"]

    for ax, rows, title in ((axes[0], sim_rows, "Simulation"), (axes[1], emu_rows, "Emulation")):
        if not rows:
            ax.set_title(f"{title} (no data)")
            continue
        x = np.arange(len(phases))
        width = 0.22
        for index, mode in enumerate(modes):
            vals = []
            for phase in phases:
                match = [row for row in rows if row["mode"] == mode and row["phase"] == phase]
                vals.append((match[0]["total_routing_bytes"] / 1024.0) if match else 0.0)
            ax.bar(x + (index - 1) * width, vals, width, color=colors[mode], label=mode.replace("_", " "))
        ax.set_xticks(x)
        ax.set_xticklabels([phase.capitalize() for phase in phases])
        ax.set_title(title)
        ax.legend()

    axes[0].set_ylabel("Total Routing Traffic (KB)")
    fig.suptitle("Two-Phase Routing Traffic: Convergence vs Churn", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_phase_bars.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def write_summary(sim_rows, emu_rows, out_dir, sim_dir="", emu_dir=""):
    out = os.path.join(out_dir, "churn_summary.md")
    with open(out, "w") as handle:
        handle.write("# Churn Scenario Summary\n\n")

        timestamps = []
        for label, rdir in (("Simulation", sim_dir), ("Emulation", emu_dir)):
            csv_path = os.path.join(rdir, "churn.csv") if rdir else ""
            if csv_path and os.path.isfile(csv_path):
                ts = datetime.fromtimestamp(os.path.getmtime(csv_path)).strftime("%Y-%m-%d %H:%M:%S")
                timestamps.append(f"**{label}**: {ts}")
        if timestamps:
            handle.write("**Last run**: " + " | ".join(timestamps) + "\n\n")

        if is_link_scale_sweep(sim_rows or emu_rows):
            axis_kind, _ = _link_scale_axis(sim_rows or emu_rows)
            if axis_kind == "count":
                handle.write("## Simultaneous Link Churn Scaling\n\n")
                handle.write(
                    "This run sweeps how many links churn simultaneously at the start of the churn phase. "
                    "Use it to compare scaling under concurrent link churn against the baseline heartbeat floor.\n\n"
                )
            else:
                handle.write("## Independent Link Churn Rate Sweep\n\n")
                handle.write(
                    "This run keeps the full link set eligible for churn and sweeps the per-link mean time to fail/recover. "
                    "Use it to compare routing overhead as the independent link process becomes more or less aggressive.\n\n"
                )
            for rows, label in ((sim_rows, "Simulation"), (emu_rows, "Emulation")):
                if not rows:
                    continue
                handle.write(f"### {label}\n\n")
                for prefix_count in _prefix_axis(rows):
                    prefix_rows = _rows_for_prefix(rows, prefix_count)
                    axis_kind, axis_values = _link_scale_axis(prefix_rows)
                    handle.write(f"#### Prefix count {prefix_count}\n\n")
                    if axis_kind == "count":
                        handle.write("| Churned links | Mode | Churn total (KB) | DvAdvert (KB) | PfxSync (KB) |\n")
                        handle.write("|---------------|------|------------------|---------------|--------------|\n")
                        for link_count in axis_values:
                            for mode in ("baseline", "two_step", "one_step"):
                                match = [
                                    row for row in prefix_rows
                                    if row["mode"] == mode
                                    and row["num_churn_links"] == link_count
                                ]
                                if not match:
                                    continue
                                row = match[0]
                                handle.write(
                                    f"| {link_count} | {mode} | {row['total_routing_bytes']/1024:.1f} | "
                                    f"{row['dv_advert_bytes']/1024:.1f} | {row['pfxsync_bytes']/1024:.1f} |\n"
                                )
                    else:
                        handle.write("| Mean fail (s) | Mean recover (s) | Mode | Churn total (KB) | DvAdvert (KB) | PfxSync (KB) |\n")
                        handle.write("|---------------|------------------|------|------------------|---------------|--------------|\n")
                        for mttf, mttr in axis_values:
                            for mode in ("baseline", "two_step", "one_step"):
                                match = [
                                    row for row in prefix_rows
                                    if row["mode"] == mode
                                    and row["link_mean_time_to_fail_s"] == mttf
                                    and row["link_mean_time_to_recover_s"] == mttr
                                ]
                                if not match:
                                    continue
                                row = match[0]
                                handle.write(
                                    f"| {mttf:g} | {mttr:g} | {mode} | {row['total_routing_bytes']/1024:.1f} | "
                                    f"{row['dv_advert_bytes']/1024:.1f} | {row['pfxsync_bytes']/1024:.1f} |\n"
                                )
                    handle.write("\n")
        else:
            handle.write("## Results\n\n")
            for rows, label in ((sim_rows, "Simulation"), (emu_rows, "Emulation")):
                if not rows:
                    continue
                handle.write(f"### {label}\n\n")
                handle.write("| Phase | Mode | Total (KB) | DvAdvert (KB) | PfxSync (KB) |\n")
                handle.write("|-------|------|------------|---------------|--------------|\n")
                for phase in ("convergence", "churn"):
                    for mode in ("baseline", "two_step", "one_step"):
                        match = [row for row in rows if row["phase"] == phase and row["mode"] == mode]
                        if not match:
                            continue
                        row = match[0]
                        handle.write(
                            f"| {phase} | {mode} | {row['total_routing_bytes']/1024:.1f} | "
                            f"{row['dv_advert_bytes']/1024:.1f} | {row['pfxsync_bytes']/1024:.1f} |\n"
                        )
                handle.write("\n")

    print(f"  Saved {out}")


def main():
    parser = argparse.ArgumentParser(description="Plot churn and link-churn-scaling results")
    parser.add_argument("--sim", default="results/sim_churn", help="Simulation results directory")
    parser.add_argument("--emu", default="results/emu_churn", help="Emulation results directory")
    parser.add_argument("--out", default="results/plots", help="Output directory for plots")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    sim_rows = load_churn_csv(os.path.join(args.sim, "churn.csv"))
    emu_rows = load_churn_csv(os.path.join(args.emu, "churn.csv"))

    if not sim_rows and not emu_rows:
        print("No churn data found.", file=sys.stderr)
        sys.exit(1)

    print("Generating churn plots...")
    if is_link_scale_sweep(sim_rows or emu_rows):
        plot_link_scale_compare(sim_rows, emu_rows, args.out)
    else:
        plot_phase_bars(sim_rows, emu_rows, args.out)
    plot_trace_details(args.sim, args.emu, args.out)
    write_summary(sim_rows, emu_rows, args.out, args.sim, args.emu)
    print("Done.")


if __name__ == "__main__":
    main()