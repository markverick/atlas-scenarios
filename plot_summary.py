#!/usr/bin/env python3
"""
Generate comprehensive summary numbers and graphs for:
  1. sim vs emu
  2. Packet types (DvAdvert, PrefixSync, Mgmt)
  3. Baseline vs one-step vs two-step

Reads from results/onestep/{sim,emu}/comparison.csv and packet-trace-*.csv.
Outputs to results/onestep/plots/.
"""

import argparse
import csv
import glob
import os
import re
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Constants ────────────────────────────────────────────────────────

MODES = ["baseline", "two_step", "one_step"]
MODE_LABELS = {
    "baseline": "Baseline",
    "two_step": "Two-step",
    "one_step": "One-step",
}
PLATFORMS = ["sim", "emu"]
PLATFORM_LABELS = {"sim": "Simulation", "emu": "Emulation"}

# Packet-type columns in comparison.csv
PKT_TYPES = [
    ("dv", "DV Advert"),
    ("pfs", "PrefixSync"),
    ("mgmt", "Mgmt"),
]

MODE_COLORS = {"baseline": "#7f7f7f", "two_step": "#1f77b4", "one_step": "#d62728"}
PLAT_HATCH = {"sim": "", "emu": "//"}
PKT_COLORS = {"DvAdvert": "#1f77b4", "PrefixSync": "#ff7f0e", "Mgmt": "#2ca02c"}

ROUTING_CATS = {"DvAdvert", "PrefixSync", "Mgmt"}


# ── Data loading ─────────────────────────────────────────────────────

def load_csv(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def load_packet_trace(path):
    events = []
    with open(path) as f:
        for r in csv.DictReader(f):
            events.append((float(r["Time"]), r["Category"], int(r["Bytes"])))
    return events


def find_packet_traces(data_dir):
    pat = re.compile(
        r"packet-trace-(baseline|two_step|one_step)-(\d+)x\d+-p\d+-t(\d+)\.csv$")
    traces = {}
    for p in sorted(glob.glob(os.path.join(data_dir, "packet-trace-*.csv"))):
        m = pat.search(os.path.basename(p))
        if m:
            traces[(m.group(1), int(m.group(2)), int(m.group(3)))] = p
    return traces


# ── Summary table ────────────────────────────────────────────────────

def build_summary(sim_rows, emu_rows):
    """Build a combined summary dict keyed by (platform, mode)."""
    summary = {}
    for plat, rows in [("sim", sim_rows), ("emu", emu_rows)]:
        for r in rows:
            mode = r["mode"]
            key = (plat, mode)
            summary[key] = {
                "grid": r["grid_size"],
                "nodes": int(r["num_nodes"]),
                "prefixes": int(r["num_prefixes"]),
                "convergence_s": float(r["convergence_s"]),
                "dv_pkts": int(r["dv_advert_pkts"]),
                "dv_bytes": int(r["dv_advert_bytes"]),
                "pfs_pkts": int(r["pfxsync_pkts"]),
                "pfs_bytes": int(r["pfxsync_bytes"]),
                "mgmt_pkts": int(r["mgmt_pkts"]),
                "mgmt_bytes": int(r["mgmt_bytes"]),
                "total_pkts": int(r["total_routing_pkts"]),
                "total_bytes": int(r["total_routing_bytes"]),
            }
    return summary


def print_summary_table(summary):
    """Print a clean multi-dimensional summary to stdout."""
    header = (
        f"{'':>12} │ {'':>12} │ "
        f"{'DV Advert':>20} │ {'PrefixSync':>20} │ "
        f"{'Mgmt':>20} │ {'Total Routing':>20} │ {'Conv.':>7}"
    )
    sub = (
        f"{'Platform':>12} │ {'Mode':>12} │ "
        f"{'Pkts':>9} {'Bytes':>10} │ {'Pkts':>9} {'Bytes':>10} │ "
        f"{'Pkts':>9} {'Bytes':>10} │ {'Pkts':>9} {'Bytes':>10} │ {'(s)':>7}"
    )
    sep = "─" * len(sub)

    print("\n" + sep)
    print("  ONE-STEP vs TWO-STEP ROUTING: SIM vs EMU COMPARISON  (2×2 grid, 3 prefixes)")
    print(sep)
    print(sub)
    print(sep)

    for plat in PLATFORMS:
        for mode in MODES:
            key = (plat, mode)
            if key not in summary:
                continue
            s = summary[key]

            def fmt_b(b):
                return f"{b/1024:.1f}KB"

            row = (
                f"{PLATFORM_LABELS[plat]:>12} │ {MODE_LABELS[mode]:>12} │ "
                f"{s['dv_pkts']:>9,} {fmt_b(s['dv_bytes']):>10} │ "
                f"{s['pfs_pkts']:>9,} {fmt_b(s['pfs_bytes']):>10} │ "
                f"{s['mgmt_pkts']:>9,} {fmt_b(s['mgmt_bytes']):>10} │ "
                f"{s['total_pkts']:>9,} {fmt_b(s['total_bytes']):>10} │ "
                f"{s['convergence_s']:>7.3f}"
            )
            print(row)
        if plat == "sim":
            print("─" * len(sub))

    print(sep)


def write_summary_md(summary, out_path):
    """Write a markdown summary table."""
    lines = [
        "# One-step vs Two-step Routing Comparison",
        "",
        "**Grid:** 2×2 (4 nodes, 4 links) | **Prefixes:** 3 | **Trial:** 1",
        "",
        "## Summary Table",
        "",
        "| Platform   | Mode      | DV Advert Pkts | DV Advert KB | PrefixSync Pkts | PrefixSync KB | Mgmt Pkts | Mgmt KB | Total Pkts | Total KB | Conv. (s) |",
        "|------------|-----------|---------------:|-------------:|----------------:|--------------:|----------:|--------:|-----------:|---------:|----------:|",
    ]

    for plat in PLATFORMS:
        for mode in MODES:
            key = (plat, mode)
            if key not in summary:
                continue
            s = summary[key]
            lines.append(
                f"| {PLATFORM_LABELS[plat]:<10} | {MODE_LABELS[mode]:<9} | "
                f"{s['dv_pkts']:>14,} | {s['dv_bytes']/1024:>12.1f} | "
                f"{s['pfs_pkts']:>15,} | {s['pfs_bytes']/1024:>13.1f} | "
                f"{s['mgmt_pkts']:>9,} | {s['mgmt_bytes']/1024:>7.1f} | "
                f"{s['total_pkts']:>10,} | {s['total_bytes']/1024:>8.1f} | "
                f"{s['convergence_s']:>9.3f} |"
            )

    # Delta analysis
    lines.extend(["", "## Key Comparisons", ""])

    for plat in PLATFORMS:
        bl = summary.get((plat, "baseline"))
        ts = summary.get((plat, "two_step"))
        os_ = summary.get((plat, "one_step"))
        if not all([bl, ts, os_]):
            continue
        label = PLATFORM_LABELS[plat]

        ts_overhead = ts["total_bytes"] - bl["total_bytes"]
        os_overhead = os_["total_bytes"] - bl["total_bytes"]
        saving = ts_overhead - os_overhead
        pct = saving / ts_overhead * 100 if ts_overhead > 0 else 0

        lines.append(f"### {label}")
        lines.append(f"- Two-step overhead vs baseline: **{ts_overhead/1024:.1f} KB** ({ts['total_bytes']/1024:.1f} - {bl['total_bytes']/1024:.1f})")
        lines.append(f"- One-step overhead vs baseline: **{os_overhead/1024:.1f} KB** ({os_['total_bytes']/1024:.1f} - {bl['total_bytes']/1024:.1f})")
        if saving > 0:
            lines.append(f"- One-step saves **{saving/1024:.1f} KB** ({pct:.0f}%) vs two-step")
        else:
            lines.append(f"- One-step costs **{-saving/1024:.1f} KB** ({-pct:.0f}%) more than two-step")
        lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Saved {out_path}")


# ── Plot 1: Grouped bar — Total bytes by mode, sim vs emu side-by-side ──

def plot_total_by_mode(summary, out_dir):
    """Grouped bar: total routing bytes for each mode, sim vs emu side by side."""
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(MODES))
    width = 0.35

    for pi, plat in enumerate(PLATFORMS):
        vals = []
        for mode in MODES:
            s = summary.get((plat, mode))
            vals.append(s["total_bytes"] / 1024 if s else 0)
        bars = ax.bar(x + pi * width, vals, width,
                      label=PLATFORM_LABELS[plat],
                      color=MODE_COLORS[MODES[0]] if pi == 0 else None,
                      hatch=PLAT_HATCH[plat], edgecolor="black", linewidth=0.5)
        # Color-code each bar by mode
        for bar, mode in zip(bars, MODES):
            bar.set_facecolor(MODE_COLORS[mode])
            bar.set_alpha(0.6 if pi == 1 else 0.9)

    ax.set_xlabel("Routing Mode")
    ax.set_ylabel("Total Routing Traffic (KB)")
    ax.set_title("Total Routing Overhead: Sim vs Emu")
    ax.set_xticks(x + width / 2)
    ax.set_xticklabels([MODE_LABELS[m] for m in MODES])
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")

    # Value labels on bars
    for pi, plat in enumerate(PLATFORMS):
        for mi, mode in enumerate(MODES):
            s = summary.get((plat, mode))
            if s:
                v = s["total_bytes"] / 1024
                ax.text(mi + pi * width, v + 1, f"{v:.1f}",
                        ha="center", va="bottom", fontsize=8)

    path = os.path.join(out_dir, "total_by_mode.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 2: Stacked bar — Packet type breakdown per mode, sim vs emu ──

def plot_pkttype_breakdown(summary, out_dir):
    """Stacked bar: traffic split by packet type for each mode, sim vs emu panels."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)

    for pi, plat in enumerate(PLATFORMS):
        ax = axes[pi]
        x = np.arange(len(MODES))
        width = 0.5

        bottoms = np.zeros(len(MODES))
        for field_prefix, pkt_label in PKT_TYPES:
            vals = []
            for mode in MODES:
                s = summary.get((plat, mode))
                vals.append(s[f"{field_prefix}_bytes"] / 1024 if s else 0)
            vals = np.array(vals)
            ax.bar(x, vals, width, bottom=bottoms,
                   label=pkt_label, color=PKT_COLORS.get(pkt_label.replace(" ", ""), None),
                   edgecolor="white", linewidth=0.5)
            # Annotate non-zero segments
            for i, v in enumerate(vals):
                if v > 0.5:
                    ax.text(i, bottoms[i] + v / 2, f"{v:.1f}",
                            ha="center", va="center", fontsize=8, fontweight="bold")
            bottoms += vals

        ax.set_xlabel("Routing Mode")
        if pi == 0:
            ax.set_ylabel("Traffic (KB)")
        ax.set_title(f"{PLATFORM_LABELS[plat]}")
        ax.set_xticks(x)
        ax.set_xticklabels([MODE_LABELS[m] for m in MODES])
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3, axis="y")

    fig.suptitle("Routing Traffic by Packet Type", fontsize=14, fontweight="bold")
    path = os.path.join(out_dir, "pkttype_breakdown.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 3: Grouped bar — Sim vs Emu for each packet type ──

def plot_sim_vs_emu_by_pkttype(summary, out_dir):
    """For each packet type, compare sim vs emu across modes."""
    pkt_fields = [
        ("dv", "DV Advert"),
        ("pfs", "PrefixSync"),
    ]

    fig, axes = plt.subplots(1, len(pkt_fields), figsize=(6 * len(pkt_fields), 5),
                              sharey=False)
    if len(pkt_fields) == 1:
        axes = [axes]

    for ai, (field_prefix, pkt_label) in enumerate(pkt_fields):
        ax = axes[ai]
        x = np.arange(len(MODES))
        width = 0.35

        for pi, plat in enumerate(PLATFORMS):
            vals = []
            for mode in MODES:
                s = summary.get((plat, mode))
                vals.append(s[f"{field_prefix}_bytes"] / 1024 if s else 0)
            ax.bar(x + pi * width, vals, width,
                   label=PLATFORM_LABELS[plat],
                   hatch=PLAT_HATCH[plat], edgecolor="black", linewidth=0.5,
                   color=PKT_COLORS.get(pkt_label.replace(" ", ""), "#999"),
                   alpha=0.9 if pi == 0 else 0.55)

        ax.set_xlabel("Routing Mode")
        ax.set_ylabel("Traffic (KB)")
        ax.set_title(f"{pkt_label}: Sim vs Emu")
        ax.set_xticks(x + width / 2)
        ax.set_xticklabels([MODE_LABELS[m] for m in MODES])
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")

    fig.suptitle("Sim vs Emu by Packet Type", fontsize=14, fontweight="bold")
    path = os.path.join(out_dir, "sim_vs_emu_by_pkttype.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 4: Overhead delta — how much each mode adds over baseline ──

def plot_overhead_delta(summary, out_dir):
    """Bar chart showing traffic overhead over baseline for each mode × platform."""
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(2)  # two_step, one_step
    width = 0.35

    for pi, plat in enumerate(PLATFORMS):
        bl = summary.get((plat, "baseline"))
        if not bl:
            continue
        bl_bytes = bl["total_bytes"]
        vals = []
        for mode in ("two_step", "one_step"):
            s = summary.get((plat, mode))
            vals.append((s["total_bytes"] - bl_bytes) / 1024 if s else 0)
        bars = ax.bar(x + pi * width, vals, width,
                      label=PLATFORM_LABELS[plat],
                      hatch=PLAT_HATCH[plat], edgecolor="black", linewidth=0.5)
        for bar, mode in zip(bars, ("two_step", "one_step")):
            bar.set_facecolor(MODE_COLORS[mode])
            bar.set_alpha(0.6 if pi == 1 else 0.9)
        for i, v in enumerate(vals):
            ax.text(i + pi * width, v + 0.5, f"{v:.1f} KB",
                    ha="center", va="bottom", fontsize=9)

    ax.set_xlabel("Routing Mode")
    ax.set_ylabel("Overhead vs Baseline (KB)")
    ax.set_title("Prefix-Routing Overhead Above Baseline")
    ax.set_xticks(x + width / 2)
    ax.set_xticklabels([MODE_LABELS[m] for m in ("two_step", "one_step")])
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    ax.axhline(y=0, color="black", linewidth=0.5)

    path = os.path.join(out_dir, "overhead_delta.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 5: Packets vs bytes scatter — all combos ──

def plot_pkts_vs_bytes(summary, out_dir):
    """Scatter: packets vs bytes for each (platform, mode) combination."""
    fig, ax = plt.subplots(figsize=(8, 6))

    marker_map = {"baseline": "^", "two_step": "s", "one_step": "o"}
    fill_map = {"sim": "full", "emu": "none"}

    for plat in PLATFORMS:
        for mode in MODES:
            s = summary.get((plat, mode))
            if not s:
                continue
            ax.scatter(s["total_pkts"], s["total_bytes"] / 1024,
                       marker=marker_map[mode], s=120,
                       color=MODE_COLORS[mode],
                       facecolors=MODE_COLORS[mode] if plat == "sim" else "none",
                       edgecolors=MODE_COLORS[mode],
                       linewidths=2,
                       label=f"{PLATFORM_LABELS[plat]} {MODE_LABELS[mode]}",
                       zorder=5)
            ax.annotate(f"{s['total_bytes']/1024:.0f}KB",
                        (s["total_pkts"], s["total_bytes"] / 1024),
                        textcoords="offset points", xytext=(8, 5), fontsize=8)

    ax.set_xlabel("Total Routing Packets")
    ax.set_ylabel("Total Routing Traffic (KB)")
    ax.set_title("Packets vs Bytes: All Combinations")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(True, alpha=0.3)

    path = os.path.join(out_dir, "pkts_vs_bytes.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 6: I/O cumulative — all modes, sim vs emu overlaid ──

def plot_io_cumulative(sim_dir, emu_dir, out_dir):
    """Cumulative routing bytes over time: sim (solid) vs emu (dashed), all modes."""
    fig, axes = plt.subplots(1, 3, figsize=(18, 5), sharey=True)

    ls_map = {"sim": "-", "emu": "--"}

    for mi, mode in enumerate(MODES):
        ax = axes[mi]
        for plat, data_dir in [("sim", sim_dir), ("emu", emu_dir)]:
            traces = find_packet_traces(data_dir)
            trial_keys = [(m, g, t) for (m, g, t) in traces if m == mode]
            if not trial_keys:
                continue
            events = load_packet_trace(traces[trial_keys[0]])
            cum = 0
            ts, cs = [], []
            for t, cat, b in sorted(events):
                if cat in ROUTING_CATS:
                    cum += b
                    ts.append(t)
                    cs.append(cum / 1024)
            if ts:
                ax.plot(ts, cs, ls_map[plat],
                        color=MODE_COLORS[mode], linewidth=1.5,
                        label=f"{PLATFORM_LABELS[plat]}")

        ax.set_xlabel("Time (s)")
        if mi == 0:
            ax.set_ylabel("Cumulative Routing Traffic (KB)")
        ax.set_title(MODE_LABELS[mode])
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    fig.suptitle("I/O: Cumulative Routing Traffic Over Time", fontsize=14, fontweight="bold")
    path = os.path.join(out_dir, "io_cumulative.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 7: I/O per-category breakdown — 2×3 grid ──

def plot_io_breakdown(sim_dir, emu_dir, out_dir):
    """Per-category cumulative I/O: rows=platform, cols=mode."""
    fig, axes = plt.subplots(2, 3, figsize=(18, 10), sharey="row")
    cat_styles = {"DvAdvert": ("-", PKT_COLORS["DvAdvert"]),
                  "PrefixSync": ("--", PKT_COLORS["PrefixSync"]),
                  "Mgmt": (":", PKT_COLORS["Mgmt"])}

    for pi, (plat, data_dir) in enumerate([("sim", sim_dir), ("emu", emu_dir)]):
        traces = find_packet_traces(data_dir)
        for mi, mode in enumerate(MODES):
            ax = axes[pi][mi]
            trial_keys = [(m, g, t) for (m, g, t) in traces if m == mode]
            if not trial_keys:
                ax.set_title(f"{PLATFORM_LABELS[plat]}: {MODE_LABELS[mode]}")
                continue

            events = load_packet_trace(traces[trial_keys[0]])
            per_cat = {}
            for t, cat, b in sorted(events):
                if cat in ROUTING_CATS:
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
                ls, color = cat_styles[cat]
                ax.plot(ts, cs, ls, color=color, linewidth=1.5, label=cat)

            ax.set_xlabel("Time (s)")
            if mi == 0:
                ax.set_ylabel(f"{PLATFORM_LABELS[plat]}\nCumulative (KB)")
            ax.set_title(f"{PLATFORM_LABELS[plat]}: {MODE_LABELS[mode]}")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)

    fig.suptitle("I/O Breakdown by Packet Type", fontsize=14, fontweight="bold", y=1.01)
    path = os.path.join(out_dir, "io_breakdown.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 8: CDF of per-packet sizes by category ──

def plot_cdf_by_category(sim_dir, emu_dir, out_dir):
    """CDF of individual packet sizes, faceted by packet category, overlaid sim vs emu."""
    cats_to_plot = ["DvAdvert", "PrefixSync"]  # Mgmt is 0 in our data
    fig, axes = plt.subplots(1, len(cats_to_plot), figsize=(6 * len(cats_to_plot), 5))
    if len(cats_to_plot) == 1:
        axes = [axes]

    ls_map = {"sim": "-", "emu": "--"}

    for ci, cat in enumerate(cats_to_plot):
        ax = axes[ci]
        for plat, data_dir in [("sim", sim_dir), ("emu", emu_dir)]:
            traces = find_packet_traces(data_dir)
            for mode in ("two_step", "one_step"):
                sizes = []
                for (m, g, t), p in traces.items():
                    if m == mode:
                        for _, c, b in load_packet_trace(p):
                            if c == cat:
                                sizes.append(b)
                if sizes:
                    xs = np.sort(sizes)
                    ys = np.arange(1, len(xs) + 1) / len(xs)
                    ax.step(xs, ys, where="post",
                            color=MODE_COLORS[mode], linestyle=ls_map[plat],
                            linewidth=1.5,
                            label=f"{PLATFORM_LABELS[plat]} {MODE_LABELS[mode]}")

        ax.set_xlabel("Packet Size (bytes)")
        ax.set_ylabel("CDF")
        ax.set_title(f"{cat} Packet Sizes")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    fig.suptitle("CDF of Packet Sizes by Category", fontsize=14, fontweight="bold")
    path = os.path.join(out_dir, "cdf_by_category.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 9: Convergence comparison ──

def plot_convergence(summary, out_dir):
    """Grouped bar: convergence time by mode, sim vs emu."""
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(MODES))
    width = 0.35

    for pi, plat in enumerate(PLATFORMS):
        vals = []
        for mode in MODES:
            s = summary.get((plat, mode))
            vals.append(s["convergence_s"] * 1000 if s else 0)  # ms
        bars = ax.bar(x + pi * width, vals, width,
                      label=PLATFORM_LABELS[plat],
                      hatch=PLAT_HATCH[plat], edgecolor="black", linewidth=0.5)
        for bar, mode in zip(bars, MODES):
            bar.set_facecolor(MODE_COLORS[mode])
            bar.set_alpha(0.6 if pi == 1 else 0.9)
        for i, v in enumerate(vals):
            ax.text(i + pi * width, v + 1, f"{v:.0f}ms",
                    ha="center", va="bottom", fontsize=8)

    ax.set_xlabel("Routing Mode")
    ax.set_ylabel("Convergence Time (ms)")
    ax.set_title("Routing Convergence: Sim vs Emu")
    ax.set_xticks(x + width / 2)
    ax.set_xticklabels([MODE_LABELS[m] for m in MODES])
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")

    path = os.path.join(out_dir, "convergence.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Plot 10: Heatmap — all combinations in one view ──

def plot_heatmap(summary, out_dir):
    """Heatmap: rows = (platform × mode), columns = packet type.  Two panels: bytes and packets."""
    row_labels = []
    bytes_data = []
    pkts_data = []
    for plat in PLATFORMS:
        for mode in MODES:
            s = summary.get((plat, mode))
            if not s:
                continue
            row_labels.append(f"{PLATFORM_LABELS[plat]}\n{MODE_LABELS[mode]}")
            bytes_data.append([s["dv_bytes"] / 1024,
                               s["pfs_bytes"] / 1024,
                               s["mgmt_bytes"] / 1024,
                               s["total_bytes"] / 1024])
            pkts_data.append([s["dv_pkts"],
                              s["pfs_pkts"],
                              s["mgmt_pkts"],
                              s["total_pkts"]])

    col_labels = ["DV Advert", "PrefixSync", "Mgmt", "Total"]
    bytes_data = np.array(bytes_data)
    pkts_data = np.array(pkts_data)

    fig, axes = plt.subplots(1, 2, figsize=(18, 6))

    for ax, data, unit, title in [
        (axes[0], bytes_data, "KB", "Traffic Volume (KB)"),
        (axes[1], pkts_data, "pkts", "Packet Count"),
    ]:
        im = ax.imshow(data, cmap="YlOrRd", aspect="auto")
        ax.set_xticks(np.arange(len(col_labels)))
        ax.set_yticks(np.arange(len(row_labels)))
        ax.set_xticklabels(col_labels, fontsize=11)
        ax.set_yticklabels(row_labels, fontsize=10)

        for i in range(len(row_labels)):
            for j in range(len(col_labels)):
                v = data[i, j]
                color = "white" if v > data.max() * 0.6 else "black"
                fmt = f"{v:.1f}" if unit == "KB" else f"{int(v):,}"
                ax.text(j, i, fmt, ha="center", va="center",
                        fontsize=11, fontweight="bold", color=color)

        ax.set_title(title, fontsize=13, fontweight="bold", pad=10)
        fig.colorbar(im, ax=ax, label=unit, shrink=0.8)

    fig.suptitle("Platform × Mode × Packet Type", fontsize=14, fontweight="bold", y=1.02)
    path = os.path.join(out_dir, "heatmap.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {path}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Comprehensive onestep comparison plots")
    parser.add_argument("--sim-csv", default="results/onestep/sim/comparison.csv")
    parser.add_argument("--emu-csv", default="results/onestep/emu/comparison.csv")
    parser.add_argument("--sim-dir", default="results/onestep/sim")
    parser.add_argument("--emu-dir", default="results/onestep/emu")
    parser.add_argument("--out", default="results/onestep/plots")
    args = parser.parse_args()

    sim_rows = load_csv(args.sim_csv)
    emu_rows = load_csv(args.emu_csv)
    summary = build_summary(sim_rows, emu_rows)

    os.makedirs(args.out, exist_ok=True)

    # Numbers
    print_summary_table(summary)
    write_summary_md(summary, os.path.join(args.out, "summary.md"))

    # Graphs
    plot_total_by_mode(summary, args.out)          # 1. sim vs emu, by mode
    plot_pkttype_breakdown(summary, args.out)       # 2. packet types, by platform
    plot_sim_vs_emu_by_pkttype(summary, args.out)   # 3. sim vs emu, by pkt type
    plot_overhead_delta(summary, args.out)           # 4. overhead above baseline
    plot_pkts_vs_bytes(summary, args.out)            # 5. scatter all combos
    plot_convergence(summary, args.out)              # 6. convergence times
    plot_heatmap(summary, args.out)                  # 7. heatmap all combos
    plot_io_cumulative(args.sim_dir, args.emu_dir, args.out)  # 8. I/O cumulative
    plot_io_breakdown(args.sim_dir, args.emu_dir, args.out)   # 9. I/O per-category
    plot_cdf_by_category(args.sim_dir, args.emu_dir, args.out)  # 10. CDF by category

    print(f"\nAll plots saved to {args.out}/")


if __name__ == "__main__":
    main()
