#!/usr/bin/env python3
"""Compute per-link traffic overhead from introducing one prefix."""

import argparse
import csv
import glob
import os


CATEGORIES = ("DvAdvert", "PFS", "PSD", "PrefixSync", "Mgmt", "UserInterest", "UserData", "Other")
CONTROL = ("DvAdvert", "PFS", "PSD", "PrefixSync", "Mgmt")


def _link_key(row):
    a = row.get("Node", "")
    b = row.get("Peer", "")
    return "<->".join(sorted((a, b)))


def _read_links(path):
    totals = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            link = _link_key(row)
            acc = totals.setdefault(link, {})
            for cat in CATEGORIES:
                for suffix in ("Pkts", "Bytes"):
                    field = f"{cat}_{suffix}"
                    acc[field] = acc.get(field, 0) + int(row.get(field, 0) or 0)
    return totals


def _find_trace(root, phase, prefix_count):
    trace_dir = os.path.join(root, phase, f"p{prefix_count}")
    matches = sorted(glob.glob(os.path.join(trace_dir, "link-trace-routing-*-t1.csv")))
    if not matches:
        raise FileNotFoundError(os.path.join(trace_dir, "link-trace-routing-*-t1.csv"))
    if len(matches) > 1:
        raise RuntimeError(f"Expected one link trace under {trace_dir}, found {len(matches)}")
    return matches[0]


def _sum_fields(row, prefix, cats):
    pkts = sum(row.get(f"{prefix}_{cat}_Pkts", 0) for cat in cats)
    bytes_ = sum(row.get(f"{prefix}_{cat}_Bytes", 0) for cat in cats)
    return pkts, bytes_


def build_rows(root, phases):
    rows = []
    for phase in phases:
        p0 = _read_links(_find_trace(root, phase, 0))
        p1 = _read_links(_find_trace(root, phase, 1))
        for link in sorted(set(p0) | set(p1)):
            row = {"phase": phase, "trial": 1, "link": link}
            for cat in CATEGORIES:
                for suffix in ("Pkts", "Bytes"):
                    field = f"{cat}_{suffix}"
                    row[f"baseline_{field}"] = p0.get(link, {}).get(field, 0)
                    row[f"one_prefix_{field}"] = p1.get(link, {}).get(field, 0)
                    row[f"overhead_{field}"] = row[f"one_prefix_{field}"] - row[f"baseline_{field}"]

            base_pkts, base_bytes = _sum_fields(row, "baseline", CONTROL)
            one_pkts, one_bytes = _sum_fields(row, "one_prefix", CONTROL)
            row["baseline_control_packets"] = base_pkts
            row["baseline_control_bytes"] = base_bytes
            row["one_prefix_control_packets"] = one_pkts
            row["one_prefix_control_bytes"] = one_bytes
            row["overhead_control_packets"] = one_pkts - base_pkts
            row["overhead_control_bytes"] = one_bytes - base_bytes
            rows.append(row)
    return rows


def _plot_packet_overhead_boxplot(rows, out_path):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/atlas-matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    phase_order = ("onephase", "twophase")
    data = [
        [int(row["overhead_control_packets"]) for row in rows if row["phase"] == phase]
        for phase in phase_order
    ]
    if not any(data):
        return None

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig, axis = plt.subplots(figsize=(6.5, 4.5))
    box = axis.boxplot(
        data,
        patch_artist=True,
        showmeans=True,
        meanline=True,
        widths=0.55,
    )
    axis.set_xticklabels(("One-phase", "Two-phase"))
    colors = ("#4C72B0", "#55A868")
    for patch, color in zip(box["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
        patch.set_edgecolor("#222222")
    for key in ("whiskers", "caps", "medians", "means"):
        for artist in box[key]:
            artist.set_color("#222222")
            artist.set_linewidth(1.2)
    axis.set_title("Per-link packet overhead from one prefix")
    axis.set_ylabel("Overhead packets per link")
    axis.grid(axis="y", linestyle="--", alpha=0.35)
    fig.tight_layout()
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    return out_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="Queue run root")
    parser.add_argument("--out", default=None, help="Output CSV path")
    parser.add_argument("--plot-out", default=None, help="Output PNG path for the packet-overhead box plot")
    parser.add_argument("--no-plot", action="store_true", help="Only write the CSV")
    parser.add_argument("--phase", action="append", choices=("twophase", "onephase"),
                        help="Phase to include; default includes both")
    args = parser.parse_args(argv)

    phases = args.phase or ["twophase", "onephase"]
    rows = build_rows(args.data, phases)
    out = args.out or os.path.join(args.data, "routing_link_overhead.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fieldnames = ["phase", "trial", "link",
                  "baseline_control_packets", "baseline_control_bytes",
                  "one_prefix_control_packets", "one_prefix_control_bytes",
                  "overhead_control_packets", "overhead_control_bytes"]
    for cat in CATEGORIES:
        for suffix in ("Pkts", "Bytes"):
            fieldnames.extend([
                f"baseline_{cat}_{suffix}",
                f"one_prefix_{cat}_{suffix}",
                f"overhead_{cat}_{suffix}",
            ])
    with open(out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} per-link overhead rows to {out}")
    if not args.no_plot:
        plot_out = args.plot_out or os.path.join(args.data, "plots", "packet_overhead_boxplot.png")
        plotted = _plot_packet_overhead_boxplot(rows, plot_out)
        if plotted:
            print(f"Wrote packet-overhead box plot to {plotted}")


if __name__ == "__main__":
    main()
