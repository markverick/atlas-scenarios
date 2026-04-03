#!/usr/bin/env python3
"""
Plot churn scenario results — two-phase (convergence vs churn) comparison.

Generates:
  1. churn_phase_bars.png     — Grouped bar chart: total routing bytes by mode and phase
  2. churn_breakdown.png      — Stacked bar: DvAdvert vs PrefixSync per mode/phase
  3. churn_savings.png        — % savings of one_step over two_step per phase
  4. churn_time_io.png        — Time-series I/O with event markers (one_step vs two_step)
  5. churn_time_io_cdf.png    — Cumulative routing traffic over time
  6. churn_cdf.png            — CDF of routing packet sizes
  7. churn_phase2_io.png      — Time-series I/O (churn phase only)
  8. churn_phase2_io_cdf.png  — Cumulative routing traffic (churn phase only)
  9. churn_phase2_cdf.png     — CDF of routing packet sizes (churn phase only)
 10. churn_summary.md         — Markdown summary table

Usage:
    python3 experiments/churn/plot.py [--sim results/sim_churn] [--emu results/emu_churn] [--out results/plots]
"""

import argparse
import csv
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


CATEGORIES = ["DvAdvert", "PrefixSync", "Mgmt"]

# Event type → (short label, color)
_EVENT_STYLE = {
    "link_down":        ("link dn",  "#e74c3c"),
    "link_up":          ("link up",  "#2ecc71"),
    "prefix_withdraw":  ("pfx rm",   "#e67e22"),
    "prefix_announce":  ("pfx add",  "#3498db"),
}


def load_event_log(rdir):
    """Load churn event markers from event-log CSV files in *rdir*.

    Returns list of (time, short_label, color) tuples, de-duplicated by time+type.
    """
    import glob
    events = []
    seen = set()
    for path in sorted(glob.glob(os.path.join(rdir, "event-log-*.csv"))):
        with open(path) as f:
            for row in csv.DictReader(f):
                etype = row.get("Event", "")
                if etype not in _EVENT_STYLE:
                    continue
                t = float(row["Time"])
                key = (round(t, 2), etype)
                if key in seen:
                    continue
                seen.add(key)
                lbl, clr = _EVENT_STYLE[etype]
                events.append((t, lbl, clr))
    events.sort()
    return events


def load_churn_csv(path):
    """Load churn.csv rows as list of dicts with numeric conversion."""
    rows = []
    if not path or not os.path.isfile(path):
        return rows
    with open(path) as f:
        for row in csv.DictReader(f):
            row["topology"] = row["topology"]
            row["grid_size"] = int(row["grid_size"])
            row["num_nodes"] = int(row["num_nodes"])
            row["num_links"] = int(row["num_links"])
            row["num_prefixes"] = int(row["num_prefixes"])
            row["window_s"] = float(row["window_s"])
            row["phase2_start"] = float(row["phase2_start"])
            row["convergence_s"] = float(row["convergence_s"])
            for k in ("dv_advert_pkts", "dv_advert_bytes",
                       "pfxsync_pkts", "pfxsync_bytes",
                       "mgmt_pkts", "mgmt_bytes",
                       "total_routing_pkts", "total_routing_bytes"):
                row[k] = int(row[k])
            rows.append(row)
    return rows


def load_packet_trace(path):
    """Load per-packet event CSV as list of (time, category, bytes)."""
    events = []
    if not path or not os.path.isfile(path):
        return events
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("Bytes"):
                continue
            events.append((float(row["Time"]), row["Category"], int(row["Bytes"])))
    return events


def plot_phase_bars(sim_rows, emu_rows, out_dir):
    """Grouped bar chart: total routing bytes by mode and phase."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for ax, rows, title in [(axes[0], sim_rows, "Simulation"),
                             (axes[1], emu_rows, "Emulation")]:
        if not rows:
            ax.set_title(f"{title} (no data)")
            continue

        modes = ["baseline", "two_step", "one_step"]
        phases = ["convergence", "churn"]
        x = np.arange(len(phases))
        width = 0.22
        colors = {"baseline": "#999999", "two_step": "#e74c3c", "one_step": "#2ecc71"}

        for i, mode in enumerate(modes):
            vals = []
            for phase in phases:
                match = [r for r in rows if r["mode"] == mode and r["phase"] == phase]
                val = match[0]["total_routing_bytes"] / 1024 if match else 0
                vals.append(val)
            ax.bar(x + (i - 1) * width, vals, width, label=mode.replace("_", " "),
                   color=colors[mode])

        ax.set_xticks(x)
        ax.set_xticklabels([p.capitalize() for p in phases])
        ax.set_title(title)
        ax.legend()

    axes[0].set_ylabel("Total Routing Traffic (KB)")
    fig.suptitle("Two-Phase Routing Traffic: Convergence vs Churn", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_phase_bars.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def plot_breakdown(sim_rows, emu_rows, out_dir):
    """Stacked bar: DvAdvert vs PrefixSync per mode/phase."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for ax, rows, title in [(axes[0], sim_rows, "Simulation"),
                             (axes[1], emu_rows, "Emulation")]:
        if not rows:
            ax.set_title(f"{title} (no data)")
            continue

        modes = ["baseline", "two_step", "one_step"]
        phases = ["convergence", "churn"]
        labels = [f"{m.replace('_',' ')}\n{p[:4]}" for m in modes for p in phases]
        x = np.arange(len(labels))

        dv_vals = []
        pfx_vals = []
        for mode in modes:
            for phase in phases:
                match = [r for r in rows if r["mode"] == mode and r["phase"] == phase]
                if match:
                    dv_vals.append(match[0]["dv_advert_bytes"] / 1024)
                    pfx_vals.append(match[0]["pfxsync_bytes"] / 1024)
                else:
                    dv_vals.append(0)
                    pfx_vals.append(0)

        ax.bar(x, dv_vals, label="DvAdvert", color="#3498db")
        ax.bar(x, pfx_vals, bottom=dv_vals, label="PrefixSync", color="#e67e22")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_title(title)
        ax.legend()

    axes[0].set_ylabel("Traffic (KB)")
    fig.suptitle("Traffic Breakdown by Category: DvAdvert + PrefixSync", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_breakdown.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def plot_savings(sim_rows, emu_rows, out_dir):
    """% savings of one_step over two_step per phase."""
    fig, ax = plt.subplots(figsize=(8, 5))

    phases = ["convergence", "churn"]
    x = np.arange(len(phases))
    width = 0.3

    for i, (rows, label) in enumerate([(sim_rows, "Sim"), (emu_rows, "Emu")]):
        if not rows:
            continue
        savings = []
        for phase in phases:
            ts = [r for r in rows if r["mode"] == "two_step" and r["phase"] == phase]
            os_ = [r for r in rows if r["mode"] == "one_step" and r["phase"] == phase]
            if ts and os_ and ts[0]["total_routing_bytes"] > 0:
                pct = 100 * (1 - os_[0]["total_routing_bytes"] / ts[0]["total_routing_bytes"])
                savings.append(pct)
            else:
                savings.append(0)
        color = "#3498db" if label == "Sim" else "#e74c3c"
        bars = ax.bar(x + (i - 0.5) * width, savings, width, label=label, color=color)
        for bar, val in zip(bars, savings):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"{val:.0f}%", ha='center', va='bottom', fontsize=10)

    ax.set_xticks(x)
    ax.set_xticklabels([p.capitalize() for p in phases])
    ax.set_ylabel("Savings (%)")
    ax.set_title("One-Step Savings over Two-Step by Phase")
    ax.legend()
    ax.set_ylim(0, 100)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_savings.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def plot_time_io(sim_dir, emu_dir, out_dir, phase2_start=30.0):
    """Time-series I/O from per-packet traces: one_step vs two_step, with event markers."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for ax, rdir, title in [(axes[0], sim_dir, "Simulation"),
                             (axes[1], emu_dir, "Emulation")]:
        if not rdir:
            ax.set_title(f"{title} (no data)")
            continue

        # Find packet traces for two_step and one_step
        for mode, color, ls in [("two_step", "#e74c3c", "-"),
                                 ("one_step", "#2ecc71", "-"),
                                 ("baseline", "#999999", "--")]:
            # Find first matching packet trace
            import glob
            pattern = os.path.join(rdir, f"packet-trace-{mode}-*.csv")
            files = sorted(glob.glob(pattern))
            if not files:
                continue
            events = load_packet_trace(files[0])
            if not events:
                continue

            # Bin into 0.5s intervals
            max_t = max(t for t, _, _ in events)
            bin_width = 0.5
            n_bins = int(max_t / bin_width) + 1
            bins = np.zeros(n_bins)
            for t, cat, b in events:
                if cat in ("DvAdvert", "PrefixSync", "Mgmt"):
                    idx = min(int(t / bin_width), n_bins - 1)
                    bins[idx] += b / 1024  # KB
            times = np.arange(n_bins) * bin_width
            ax.plot(times, bins, color=color, linestyle=ls, linewidth=1.2,
                    label=mode.replace("_", " "), alpha=0.8)

        # Phase boundary
        ax.axvline(x=phase2_start, color='gray', linestyle=':', alpha=0.5)

        # Dynamic event markers from event-log CSVs
        churn_events = load_event_log(rdir) if rdir else []
        ymax = ax.get_ylim()[1]
        for i, (t, lbl, clr) in enumerate(churn_events):
            yfrac = 0.95 if i % 2 == 0 else 0.82
            ax.axvline(x=t, color=clr, linestyle='--', linewidth=0.8, alpha=0.6)
            ax.text(t, ymax * yfrac, lbl, ha='center', va='top',
                    fontsize=6, color=clr, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', alpha=0.7, ec=clr, lw=0.5))

        ax.set_xlabel("Time (s)")
        ax.set_title(title)
        ax.legend(loc='upper left')

    axes[0].set_ylabel("Routing Traffic (KB / 0.5s)")
    fig.suptitle("Time-Series Routing Traffic Under Churn", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_time_io.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def plot_time_io_cdf(sim_dir, emu_dir, out_dir, phase2_start=30.0):
    """Cumulative routing traffic over time, split by traffic type per mode."""
    import glob
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    # mode → base color; category → linestyle
    mode_colors = {"two_step": "#e74c3c", "one_step": "#2ecc71", "baseline": "#999999"}
    cat_styles = {"DvAdvert": "-", "PrefixSync": "--", "Mgmt": ":"}
    cat_order = ["DvAdvert", "PrefixSync", "Mgmt"]

    for ax, rdir, title in [(axes[0], sim_dir, "Simulation"),
                             (axes[1], emu_dir, "Emulation")]:
        if not rdir:
            ax.set_title(f"{title} (no data)")
            continue

        for mode in ("two_step", "one_step", "baseline"):
            pattern = os.path.join(rdir, f"packet-trace-{mode}-*.csv")
            files = sorted(glob.glob(pattern))
            if not files:
                continue
            events = load_packet_trace(files[0])
            if not events:
                continue

            color = mode_colors[mode]
            mode_label = mode.replace("_", " ")

            for cat in cat_order:
                cat_events = sorted((t, b) for t, c, b in events if c == cat)
                if not cat_events:
                    continue
                times = [t for t, _ in cat_events]
                cum_kb = np.cumsum([b / 1024 for _, b in cat_events])
                ls = cat_styles[cat]
                lw = 1.8 if cat == "DvAdvert" else 1.3
                ax.plot(times, cum_kb, color=color, linestyle=ls, linewidth=lw,
                        label=f"{mode_label} · {cat} ({cum_kb[-1]:.0f} KB)",
                        alpha=0.85)

        # Phase boundary
        ax.axvline(x=phase2_start, color='gray', linestyle=':', alpha=0.5)

        # Dynamic event markers from event-log CSVs
        churn_events = load_event_log(rdir) if rdir else []
        ymin, ymax = ax.get_ylim()
        for i, (t, lbl, clr) in enumerate(churn_events):
            bfrac = 0.05 if i % 2 == 0 else 0.18
            ax.axvline(x=t, color=clr, linestyle='--', linewidth=0.8, alpha=0.6)
            ax.text(t, ymin + (ymax - ymin) * bfrac, lbl, ha='center', va='bottom',
                    fontsize=6, color=clr, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', alpha=0.7, ec=clr, lw=0.5))

        ax.set_xlabel("Time (s)")
        ax.set_title(title)
        ax.legend(loc='upper left', fontsize=7, ncol=2)

    axes[0].set_ylabel("Cumulative Routing Traffic (KB)")
    fig.suptitle("Cumulative Routing Traffic Over Time (by type)", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_time_io_cdf.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def plot_cdf(sim_dir, emu_dir, out_dir):
    """CDF of per-packet routing traffic sizes (one_step vs two_step)."""
    import glob
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for ax, rdir, title in [(axes[0], sim_dir, "Simulation"),
                             (axes[1], emu_dir, "Emulation")]:
        if not rdir:
            ax.set_title(f"{title} (no data)")
            continue

        for mode, color, ls in [("two_step", "#e74c3c", "-"),
                                 ("one_step", "#2ecc71", "-"),
                                 ("baseline", "#999999", "--")]:
            pattern = os.path.join(rdir, f"packet-trace-{mode}-*.csv")
            files = sorted(glob.glob(pattern))
            if not files:
                continue
            events = load_packet_trace(files[0])
            if not events:
                continue

            # Collect routing packet sizes
            sizes = sorted(b for _, cat, b in events
                           if cat in ("DvAdvert", "PrefixSync", "Mgmt"))
            if not sizes:
                continue
            cdf_y = np.arange(1, len(sizes) + 1) / len(sizes)
            ax.plot(sizes, cdf_y, color=color, linestyle=ls, linewidth=1.5,
                    label=f"{mode.replace('_', ' ')} ({len(sizes)} pkts)", alpha=0.85)

        ax.set_xlabel("Packet Size (bytes)")
        ax.set_title(title)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("CDF")
    fig.suptitle("CDF of Routing Packet Sizes Under Churn", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_cdf.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


# ---- Churn-phase-only plots ----

def plot_phase2_io(sim_dir, emu_dir, out_dir, phase2_start=30.0):
    """Time-series I/O from per-packet traces, churn phase only."""
    import glob
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for ax, rdir, title in [(axes[0], sim_dir, "Simulation"),
                             (axes[1], emu_dir, "Emulation")]:
        if not rdir:
            ax.set_title(f"{title} (no data)")
            continue

        for mode, color, ls in [("two_step", "#e74c3c", "-"),
                                 ("one_step", "#2ecc71", "-"),
                                 ("baseline", "#999999", "--")]:
            pattern = os.path.join(rdir, f"packet-trace-{mode}-*.csv")
            files = sorted(glob.glob(pattern))
            if not files:
                continue
            events = [(t, cat, b) for t, cat, b in load_packet_trace(files[0])
                      if t >= phase2_start]
            if not events:
                continue

            max_t = max(t for t, _, _ in events)
            bin_width = 0.5
            n_bins = int((max_t - phase2_start) / bin_width) + 1
            bins = np.zeros(n_bins)
            for t, cat, b in events:
                if cat in ("DvAdvert", "PrefixSync", "Mgmt"):
                    idx = min(int((t - phase2_start) / bin_width), n_bins - 1)
                    bins[idx] += b / 1024
            times = phase2_start + np.arange(n_bins) * bin_width
            ax.plot(times, bins, color=color, linestyle=ls, linewidth=1.2,
                    label=mode.replace("_", " "), alpha=0.8)

        churn_events = load_event_log(rdir) if rdir else []
        ymax = ax.get_ylim()[1]
        for i, (t, lbl, clr) in enumerate(churn_events):
            yfrac = 0.95 if i % 2 == 0 else 0.82
            ax.axvline(x=t, color=clr, linestyle='--', linewidth=0.8, alpha=0.6)
            ax.text(t, ymax * yfrac, lbl, ha='center', va='top',
                    fontsize=6, color=clr, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', alpha=0.7, ec=clr, lw=0.5))

        ax.set_xlabel("Time (s)")
        ax.set_title(title)
        ax.legend(loc='upper left')

    axes[0].set_ylabel("Routing Traffic (KB / 0.5s)")
    fig.suptitle("Churn Phase — Time-Series Routing Traffic", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_phase2_io.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def plot_phase2_io_cdf(sim_dir, emu_dir, out_dir, phase2_start=30.0):
    """Cumulative routing traffic over time, churn phase only."""
    import glob
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    mode_colors = {"two_step": "#e74c3c", "one_step": "#2ecc71", "baseline": "#999999"}
    cat_styles = {"DvAdvert": "-", "PrefixSync": "--", "Mgmt": ":"}
    cat_order = ["DvAdvert", "PrefixSync", "Mgmt"]

    for ax, rdir, title in [(axes[0], sim_dir, "Simulation"),
                             (axes[1], emu_dir, "Emulation")]:
        if not rdir:
            ax.set_title(f"{title} (no data)")
            continue

        for mode in ("two_step", "one_step", "baseline"):
            pattern = os.path.join(rdir, f"packet-trace-{mode}-*.csv")
            files = sorted(glob.glob(pattern))
            if not files:
                continue
            events = [(t, cat, b) for t, cat, b in load_packet_trace(files[0])
                      if t >= phase2_start]
            if not events:
                continue

            color = mode_colors[mode]
            mode_label = mode.replace("_", " ")

            for cat in cat_order:
                cat_events = sorted((t, b) for t, c, b in events if c == cat)
                if not cat_events:
                    continue
                times = [t for t, _ in cat_events]
                cum_kb = np.cumsum([b / 1024 for _, b in cat_events])
                ls = cat_styles[cat]
                lw = 1.8 if cat == "DvAdvert" else 1.3
                ax.plot(times, cum_kb, color=color, linestyle=ls, linewidth=lw,
                        label=f"{mode_label} · {cat} ({cum_kb[-1]:.0f} KB)",
                        alpha=0.85)

        churn_events = load_event_log(rdir) if rdir else []
        ymin, ymax = ax.get_ylim()
        for i, (t, lbl, clr) in enumerate(churn_events):
            bfrac = 0.05 if i % 2 == 0 else 0.18
            ax.axvline(x=t, color=clr, linestyle='--', linewidth=0.8, alpha=0.6)
            ax.text(t, ymin + (ymax - ymin) * bfrac, lbl, ha='center', va='bottom',
                    fontsize=6, color=clr, fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.15', fc='white', alpha=0.7, ec=clr, lw=0.5))

        ax.set_xlabel("Time (s)")
        ax.set_title(title)
        ax.legend(loc='upper left', fontsize=7, ncol=2)

    axes[0].set_ylabel("Cumulative Routing Traffic (KB)")
    fig.suptitle("Churn Phase — Cumulative Routing Traffic (by type)", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_phase2_io_cdf.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def plot_phase2_cdf(sim_dir, emu_dir, out_dir, phase2_start=30.0):
    """CDF of per-packet routing traffic sizes, churn phase only."""
    import glob
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)

    for ax, rdir, title in [(axes[0], sim_dir, "Simulation"),
                             (axes[1], emu_dir, "Emulation")]:
        if not rdir:
            ax.set_title(f"{title} (no data)")
            continue

        for mode, color, ls in [("two_step", "#e74c3c", "-"),
                                 ("one_step", "#2ecc71", "-"),
                                 ("baseline", "#999999", "--")]:
            pattern = os.path.join(rdir, f"packet-trace-{mode}-*.csv")
            files = sorted(glob.glob(pattern))
            if not files:
                continue
            events = [(t, cat, b) for t, cat, b in load_packet_trace(files[0])
                      if t >= phase2_start]
            if not events:
                continue

            sizes = sorted(b for _, cat, b in events
                           if cat in ("DvAdvert", "PrefixSync", "Mgmt"))
            if not sizes:
                continue
            cdf_y = np.arange(1, len(sizes) + 1) / len(sizes)
            ax.plot(sizes, cdf_y, color=color, linestyle=ls, linewidth=1.5,
                    label=f"{mode.replace('_', ' ')} ({len(sizes)} pkts)", alpha=0.85)

        ax.set_xlabel("Packet Size (bytes)")
        ax.set_title(title)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    axes[0].set_ylabel("CDF")
    fig.suptitle("Churn Phase — CDF of Routing Packet Sizes", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "churn_phase2_cdf.png")
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"  Saved {out}")


def write_summary(sim_rows, emu_rows, out_dir, sim_dir="", emu_dir=""):
    """Write a markdown summary with scenario design, results tables, and interpretation."""
    out = os.path.join(out_dir, "churn_summary.md")
    with open(out, "w") as f:
        f.write("# Churn Scenario Summary\n\n")

        # --- Last run timestamps ---
        timestamps = []
        for label, rdir in [("Simulation", sim_dir), ("Emulation", emu_dir)]:
            csv_path = os.path.join(rdir, "churn.csv") if rdir else ""
            if csv_path and os.path.isfile(csv_path):
                mtime = os.path.getmtime(csv_path)
                ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                timestamps.append(f"**{label}**: {ts}")
        if timestamps:
            f.write("**Last run**: " + " | ".join(timestamps) + "\n\n")

        # --- Scenario Design ---
        f.write("## Scenario Design\n\n")
        f.write("The churn scenario measures routing overhead under dynamic network events, "
                "comparing **one-step** (prefixes embedded in DV adverts) against "
                "**two-step** (DV + PrefixSync) routing.\n\n")

        f.write("### Topology & Parameters\n\n")
        f.write("| Parameter | Value |\n|-----------|-------|\n")
        ref = (sim_rows or emu_rows)[0]
        topo = ref["topology"]
        is_grid = (topo == "grid")
        if is_grid:
            f.write(f"| Topology | {ref['grid_size']}×{ref['grid_size']} grid "
                    f"({ref['num_nodes']} nodes, {ref['num_links']} links) |\n")
        else:
            from lib.churn_common import KNOWN_TOPOLOGIES
            label = KNOWN_TOPOLOGIES.get(topo, {}).get("label", topo.title())
            f.write(f"| Topology | {label} "
                    f"({ref['num_nodes']} nodes, {ref['num_links']} links) |\n")
        n_pfx = max(r["num_prefixes"] for r in (sim_rows or emu_rows))
        f.write(f"| Prefixes per node | {n_pfx} |\n")
        window_s = ref["window_s"]
        p2s = ref["phase2_start"]
        churn_len = window_s - p2s
        f.write("| Link delay | 10 ms |\n"
                "| Link bandwidth | 10 Mbps |\n"
                "| DV advertise interval | 5,000 ms |\n"
                "| Router dead interval | 30,000 ms |\n")
        f.write(f"| Observation window | {window_s:.0f} s "
                f"({p2s:.0f} s convergence + {churn_len:.0f} s churn) |\n\n")
        if is_grid:
            edge = "n0\\_0–n0\\_1"
            churn_node = "n0\\_0"
            pfx = "/data/node0/pfx0"
        else:
            from lib.churn_common import KNOWN_TOPOLOGIES
            topo_info = KNOWN_TOPOLOGIES.get(topo, {})
            link = topo_info.get("churn_link", ("?", "?"))
            node = topo_info.get("churn_node", "?")
            edge = f"{link[0]}–{link[1]}"
            churn_node = node
            pfx = f"/data/{node}/pfx0"

        f.write("### Two Phases\n\n"
                f"1. **Convergence phase** (0–{p2s:.0f} s): All routers boot, run DV until "
                "converged, then announce synthetic prefixes. Measures initial routing overhead.\n"
                f"2. **Churn phase** ({p2s:.0f}–{window_s:.0f} s): Dynamic events are injected "
                f"on a single edge ({edge}).\n\n")

        # Read actual events from event-log CSVs
        ref_dir = sim_dir if os.path.isdir(sim_dir or "") else (emu_dir if os.path.isdir(emu_dir or "") else "")
        evt_list = load_event_log(ref_dir) if ref_dir else []
        if evt_list:
            f.write("| Time (s) | Event |\n|----------|-------|\n")
            for t, lbl, _ in evt_list:
                f.write(f"| {t:.1f} | {lbl} |\n")
            f.write("\n")
        else:
            f.write("*(No event log found.)*\n\n")

        f.write("### Three Modes\n\n"
                "- **baseline**: one\\_step enabled, 0 prefixes → pure DV overhead\n"
                "- **two\\_step**: DV carries router reachability; "
                "PrefixSync SVS distributes prefix→router mappings\n"
                "- **one\\_step**: Prefixes go directly into the RIB and appear in "
                "DV adverts; no PrefixSync\n\n")

        # --- Results tables ---
        f.write("## Results\n\n")
        savings_data = {}
        for rows, label in [(sim_rows, "Simulation"), (emu_rows, "Emulation")]:
            if not rows:
                continue
            n_pfx = max(r["num_prefixes"] for r in rows)
            topo_key = rows[0]["topology"]
            if topo_key == "grid":
                grid = rows[0]["grid_size"]
                topo_label = f"{grid}×{grid} grid"
            else:
                from lib.churn_common import KNOWN_TOPOLOGIES
                topo_disp = KNOWN_TOPOLOGIES.get(topo_key, {}).get("label", topo_key.title())
                topo_label = f"{topo_disp} ({rows[0]['num_nodes']} nodes)"
            f.write(f"### {label} — {topo_label}, {n_pfx} prefixes/node\n\n")
            f.write("| Phase | Mode | DvAdvert (KB) | PfxSync (KB) | Total (KB) |\n")
            f.write("|-------|------|--------------|-------------|------------|\n")
            for phase in ("convergence", "churn"):
                for mode in ("baseline", "two_step", "one_step"):
                    match = [r for r in rows if r["mode"] == mode and r["phase"] == phase]
                    if not match:
                        continue
                    r = match[0]
                    f.write(f"| {phase} | {mode} | "
                            f"{r['dv_advert_bytes']/1024:.1f} | "
                            f"{r['pfxsync_bytes']/1024:.1f} | "
                            f"{r['total_routing_bytes']/1024:.1f} |\n")
            f.write("\n")

            for phase in ("convergence", "churn"):
                ts = [r for r in rows if r["mode"] == "two_step" and r["phase"] == phase]
                os_ = [r for r in rows if r["mode"] == "one_step" and r["phase"] == phase]
                if ts and os_ and ts[0]["total_routing_bytes"] > 0:
                    pct = 100 * (1 - os_[0]["total_routing_bytes"] / ts[0]["total_routing_bytes"])
                    f.write(f"**{phase.capitalize()} savings**: {pct:.0f}%\n\n")
                    savings_data[(label, phase)] = pct

        # --- Interpretation ---
        f.write("## Interpretation\n\n")

        f.write("### Convergence phase: one-step wins\n\n")
        conv_sim = savings_data.get(("Simulation", "convergence"), 0)
        conv_emu = savings_data.get(("Emulation", "convergence"), 0)
        f.write(f"One-step saves {conv_sim:.0f}% (sim) / {conv_emu:.0f}% (emu) over two-step "
                "during initial convergence because it eliminates the entire PrefixSync "
                "subsystem. Two-step needs hundreds of KB of PrefixSync traffic on top of "
                "DV. One-step carries prefixes inside DV adverts — packets are larger "
                "(~430 B vs ~300 B) but the total is still much less than DV + PrefixSync "
                "combined.\n\n")

        f.write("### Churn phase: two-step wins\n\n")
        churn_sim = savings_data.get(("Simulation", "churn"), 0)
        churn_emu = savings_data.get(("Emulation", "churn"), 0)
        f.write(f"Under churn, one-step uses {-churn_sim:.0f}% more (sim) / "
                f"{-churn_emu:.0f}% more (emu) traffic than two-step. When a link fails or "
                "a prefix changes, one-step must re-advertise the *entire* RIB contents "
                "(all prefixes) in every triggered DV update. Two-step only sends a small "
                "PrefixSync delta for the single changed prefix, while its DV traffic stays "
                "at baseline levels.\n\n")

        f.write("### Sim vs emu gap\n\n"
                "Simulation shows larger one-step churn traffic than emulation. "
                "ns-3's deterministic scheduler processes all DV updates in lock-step — "
                "when a link event triggers re-convergence, every router reacts within the "
                "same simulated time window, causing a burst of updates. In emulation, "
                "real-time scheduling spreads updates across slightly different wall-clock "
                "moments, so some intermediate updates are suppressed by the next heartbeat "
                "before they propagate fully.\n")

    print(f"  Saved {out}")


def main():
    parser = argparse.ArgumentParser(description="Plot churn scenario results")
    parser.add_argument("--sim", default="results/sim_churn",
                        help="Sim results directory")
    parser.add_argument("--emu", default="results/emu_churn",
                        help="Emu results directory")
    parser.add_argument("--out", default="results/plots",
                        help="Output directory for plots")
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    sim_csv = os.path.join(args.sim, "churn.csv")
    emu_csv = os.path.join(args.emu, "churn.csv")
    sim_rows = load_churn_csv(sim_csv)
    emu_rows = load_churn_csv(emu_csv)

    if not sim_rows and not emu_rows:
        print("No churn data found. Run sim/churn.py and/or emu/churn.py first.")
        sys.exit(1)

    # Detect phase boundary from data
    ref = (sim_rows or emu_rows)[0]
    phase2_start = ref["phase2_start"]

    print("Generating churn plots...")
    plot_phase_bars(sim_rows, emu_rows, args.out)
    plot_breakdown(sim_rows, emu_rows, args.out)
    plot_savings(sim_rows, emu_rows, args.out)
    plot_time_io(args.sim, args.emu, args.out, phase2_start)
    plot_time_io_cdf(args.sim, args.emu, args.out, phase2_start)
    plot_cdf(args.sim, args.emu, args.out)
    plot_phase2_io(args.sim, args.emu, args.out, phase2_start)
    plot_phase2_io_cdf(args.sim, args.emu, args.out, phase2_start)
    plot_phase2_cdf(args.sim, args.emu, args.out, phase2_start)
    write_summary(sim_rows, emu_rows, args.out, args.sim, args.emu)
    print("Done.")


if __name__ == "__main__":
    main()
