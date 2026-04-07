#!/usr/bin/env python3

import argparse
import csv
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


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


def is_link_scale_sweep(rows):
    if not rows:
        return False
    counts = {row["num_churn_links"] for row in rows}
    return len(counts) > 1


def plot_link_scale_compare(sim_rows, emu_rows, out_dir):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    mode_styles = {
        "baseline": ("#999999", "o-"),
        "two_step": ("#e74c3c", "s-"),
        "one_step": ("#2ecc71", "^-"),
    }

    for ax, rows, title in ((axes[0], sim_rows, "Simulation"), (axes[1], emu_rows, "Emulation")):
        if not rows:
            ax.set_title(f"{title} (no data)")
            continue

        link_counts = sorted({row["num_churn_links"] for row in rows if row["phase"] == "churn"})
        for mode, (color, style) in mode_styles.items():
            points = []
            for link_count in link_counts:
                match = [
                    row for row in rows
                    if row["phase"] == "churn"
                    and row["mode"] == mode
                    and row["num_churn_links"] == link_count
                ]
                if match:
                    points.append((link_count, match[0]["total_routing_bytes"] / 1024.0))
            if points:
                ax.plot(
                    [x for x, _ in points],
                    [y for _, y in points],
                    style,
                    color=color,
                    linewidth=2,
                    label=mode.replace("_", " "),
                )

        ax.set_xlabel("Churned Links")
        ax.set_xticks(link_counts)
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        ax.legend()

    axes[0].set_ylabel("Churn-Phase Routing Traffic (KB)")
    fig.suptitle("Simultaneous Link Churn Scaling: Baseline vs Two-Step", fontsize=13)
    fig.tight_layout()
    out = os.path.join(out_dir, "link_scale_churn_compare.png")
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
            handle.write("## Simultaneous Link Churn Scaling\n\n")
            handle.write(
                "This run sweeps how many links churn simultaneously at the start of the churn phase. "
                "Use it to compare scaling under concurrent link churn against the baseline heartbeat floor.\n\n"
            )
            for rows, label in ((sim_rows, "Simulation"), (emu_rows, "Emulation")):
                if not rows:
                    continue
                handle.write(f"### {label}\n\n")
                handle.write("| Churned links | Mode | Churn total (KB) | DvAdvert (KB) | PfxSync (KB) |\n")
                handle.write("|---------------|------|------------------|---------------|--------------|\n")
                link_counts = sorted({row["num_churn_links"] for row in rows if row["phase"] == "churn"})
                for link_count in link_counts:
                    for mode in ("baseline", "two_step", "one_step"):
                        match = [
                            row for row in rows
                            if row["phase"] == "churn"
                            and row["mode"] == mode
                            and row["num_churn_links"] == link_count
                        ]
                        if not match:
                            continue
                        row = match[0]
                        handle.write(
                            f"| {link_count} | {mode} | {row['total_routing_bytes']/1024:.1f} | "
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
    write_summary(sim_rows, emu_rows, args.out, args.sim, args.emu)
    print("Done.")


if __name__ == "__main__":
    main()