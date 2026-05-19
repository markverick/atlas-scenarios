#!/usr/bin/env python3
"""Aggregate one-prefix-from-scratch prefix update traffic per link."""

import argparse
import csv
import os
from collections import Counter, defaultdict

CATEGORIES = ("DvAdvert", "PFS", "PSD", "Mgmt", "UserInterest", "UserData", "Other")
PHASE_CATEGORY = {
    "onephase": "PFS",
    "twophase": "PSD",
}


def _norm_link(a, b):
    return "<->".join(sorted((a, b)))


def _find_packet_trace(run_dir):
    for name in sorted(os.listdir(run_dir)):
        if name.startswith("packet-trace-") and name.endswith(".csv"):
            return os.path.join(run_dir, name)
    return None


def _find_link_trace(run_dir):
    for name in sorted(os.listdir(run_dir)):
        if name.startswith("link-trace-") and name.endswith(".csv"):
            return os.path.join(run_dir, name)
    return None


def _read_links(run_dir):
    link_trace = _find_link_trace(run_dir)
    if link_trace is None:
        return []

    links = []
    seen = set()
    with open(link_trace, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            link = _norm_link(row["Node"], row["Peer"])
            if link not in seen:
                seen.add(link)
                links.append(link)
    return links


def _read_phase_rows(data_root, phase, start_time, end_time):
    phase_dir = os.path.join(data_root, phase, "p1")
    packet_trace = _find_packet_trace(phase_dir)
    links = _read_links(phase_dir)

    per_link = defaultdict(Counter)
    if packet_trace is not None:
        with open(packet_trace, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t = float(row["Time"])
                if t < start_time or t > end_time:
                    continue
                category = row.get("Category", "Other")
                if category not in CATEGORIES:
                    category = "Other"
                link = _norm_link(row["Node"], row["Peer"])
                per_link[link][f"{category}_Pkts"] += 1
                per_link[link][f"{category}_Bytes"] += int(row["Bytes"])
                packet_type = row.get("PacketType", "Unknown")
                if packet_type in ("Interest", "Data"):
                    per_link[link][f"{category}_{packet_type}_Pkts"] += 1
                if link not in links:
                    links.append(link)

    phase_category = PHASE_CATEGORY[phase]
    rows = []
    for link in sorted(links):
        counts = per_link[link]
        row = {
            "phase": phase,
            "trial": 1,
            "link": link,
            "prefix_update_packets": counts[f"{phase_category}_Pkts"],
            "prefix_update_bytes": counts[f"{phase_category}_Bytes"],
            "prefix_update_interest_packets": counts[f"{phase_category}_Interest_Pkts"],
            "prefix_update_data_packets": counts[f"{phase_category}_Data_Pkts"],
        }
        for category in CATEGORIES:
            row[f"{category}_Pkts"] = counts[f"{category}_Pkts"]
            row[f"{category}_Bytes"] = counts[f"{category}_Bytes"]
            row[f"{category}_Interest_Pkts"] = counts[f"{category}_Interest_Pkts"]
            row[f"{category}_Data_Pkts"] = counts[f"{category}_Data_Pkts"]
        rows.append(row)
    return rows


def _write_rows(rows, out_path):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fields = [
        "phase",
        "trial",
        "link",
        "prefix_update_packets",
        "prefix_update_bytes",
        "prefix_update_interest_packets",
        "prefix_update_data_packets",
    ]
    for category in CATEGORIES:
        fields.extend(
            (
                f"{category}_Pkts",
                f"{category}_Bytes",
                f"{category}_Interest_Pkts",
                f"{category}_Data_Pkts",
            )
        )

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _plot(rows, out_path):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    data = []
    labels = []
    for phase in ("onephase", "twophase"):
        values = [int(r["prefix_update_packets"]) for r in rows if r["phase"] == phase]
        if values:
            data.append(values)
            labels.append(f"{phase}\n{PHASE_CATEGORY[phase]}")
    if not data:
        return None

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    ax.boxplot(data, showmeans=True, patch_artist=True)
    ax.set_xticks(range(1, len(labels) + 1), labels)
    ax.set_ylabel("Packets per link")
    ax.set_title("One Prefix From Scratch: Prefix Update Link Traffic")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    return out_path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Run root containing onephase/p1 and twophase/p1")
    parser.add_argument("--start-time", type=float, default=100.0)
    parser.add_argument("--end-time", type=float, default=150.0)
    parser.add_argument("--out", default=None)
    parser.add_argument("--plot-out", default=None)
    args = parser.parse_args(argv)

    rows = []
    for phase in ("twophase", "onephase"):
        rows.extend(_read_phase_rows(args.data, phase, args.start_time, args.end_time))

    out_path = args.out or os.path.join(args.data, "routing_link_traffic_prefix_event.csv")
    _write_rows(rows, out_path)
    print(f"Wrote {out_path}")

    plot_out = args.plot_out or os.path.join(args.data, "plots", "packet_traffic_prefix_event_boxplot.png")
    plotted = _plot(rows, plot_out)
    if plotted:
        print(f"Wrote {plotted}")


if __name__ == "__main__":
    main()
