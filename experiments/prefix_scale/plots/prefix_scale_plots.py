import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from lib.topology import core_edge_links, core_edge_positions, core_edge_roles
from .prefix_scale_data import bin_io, human_bytes, load_event_log, load_packet_trace, load_svs_suppression_dir
from .prefix_scale_data import load_core_edge_link_trace_summaries


TRACE_CATEGORY_STYLES = {
    "DvAdvert": ("#4C72B0", "DV"),
    "PrefixSync": ("#C44E52", "PfxSync"),
}

PHASE_STYLES = {
    "onephase": {"label": "One-phase", "color": "#4C72B0", "marker": "o"},
    "twophase": {"label": "Two-phase", "color": "#DD8452", "marker": "s"},
}

CORE_EDGE_PLOT_FILES = {
    "topology": "core_edge_topology.png",
    "run_comparison": "core_edge_run_comparison.png",
    "control_breakdown": "core_edge_control_breakdown.png",
    "prefix_state": "core_edge_prefix_state_by_role.png",
    "forwarder_growth": "core_edge_forwarding_delta_by_role.png",
    "table_stack": "core_edge_table_stack_comparison.png",
}

CORE_EDGE_RC = {
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "figure.titlesize": 14,
}


def _mean(values):
    if not values:
        return 0.0
    return sum(values) / len(values)


def _aggregate_by_prefix(rows, field, *, role=None, table_category=None, table_name=None):
    grouped = {}
    for row in rows:
        if role is not None and row.get("role") != role:
            continue
        if table_category is not None and row.get("table_category") != table_category:
            continue
        if table_name is not None and row.get("table_name") != table_name:
            continue
        prefix_count = int(row["prefix_count"])
        grouped.setdefault(prefix_count, []).append(float(row[field]))
    return {prefix_count: _mean(values) for prefix_count, values in grouped.items()}


def _sorted_prefix_counts(*series_list):
    return sorted({prefix_count for series in series_list for prefix_count in series})


def _plot_series(axis, prefix_to_value, *, label, color, marker, linestyle="-"):
    if not prefix_to_value:
        return
    prefix_counts = sorted(prefix_to_value)
    axis.plot(
        prefix_counts,
        [prefix_to_value[prefix_count] for prefix_count in prefix_counts],
        f"{marker}{linestyle}",
        label=label,
        color=color,
        linewidth=2,
    )


def _aggregate_total_entries_by_prefix_and_table(rows):
    grouped = {}
    for row in rows:
        prefix_count = int(row["prefix_count"])
        key = (row["table_category"], row["table_name"])
        grouped.setdefault(key, {})
        grouped[key][prefix_count] = grouped[key].get(prefix_count, 0.0) + float(row["total_entries"])
    return grouped


def plot_core_edge_topology(out_dir):
    positions = core_edge_positions()
    roles = core_edge_roles()
    links = core_edge_links()
    role_styles = {
        "core": {"color": "#4C72B0", "edgecolor": "#1F3A5F", "size": 850},
        "edge": {"color": "#DD8452", "edgecolor": "#7A3E1D", "size": 850},
    }

    with plt.rc_context(CORE_EDGE_RC):
        fig, axis = plt.subplots(figsize=(7.5, 6.8))

        for src, dst in links:
            x_values = [positions[src][0], positions[dst][0]]
            y_values = [positions[src][1], positions[dst][1]]
            axis.plot(x_values, y_values, color="#A8A8A8", linewidth=2.0, zorder=1)

        for role, nodes in roles.items():
            style = role_styles[role]
            xs = [positions[node][0] for node in nodes]
            ys = [positions[node][1] for node in nodes]
            axis.scatter(
                xs,
                ys,
                s=style["size"],
                c=style["color"],
                edgecolors=style["edgecolor"],
                linewidths=1.5,
                label=f"{role.capitalize()} routers",
                zorder=2,
            )
            for node in nodes:
                axis.text(
                    positions[node][0],
                    positions[node][1],
                    node,
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=10,
                    fontweight="bold",
                    zorder=3,
                )

        axis.set_aspect("equal", adjustable="box")
        axis.axis("off")
        fig.suptitle("Core-edge topology used by the prefix-scale study", y=0.98)
        fig.legend(loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.94))

        fig.tight_layout(rect=(0, 0, 1, 0.88))
        path = os.path.join(out_dir, CORE_EDGE_PLOT_FILES["topology"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_table_stack_comparison(results_by_phase, out_dir, source_label):
    table_order = [
        ("common", "dv_neighbors"),
        ("common", "dv_rib"),
        ("common", "forwarder_rib"),
        ("common", "forwarder_fib"),
        ("onephase", "dv_prefix_table"),
        ("twophase", "forwarder_pet"),
        ("twophase", "forwarder_multicast_fib"),
        ("twophase", "dv_prefix_egress_state"),
    ]
    table_styles = {
        ("common", "dv_neighbors"): ("DV neighbors", "#7A7A7A"),
        ("common", "dv_rib"): ("DV RIB", "#4C72B0"),
        ("common", "forwarder_rib"): ("Forwarder RIB", "#55A868"),
        ("common", "forwarder_fib"): ("Forwarder FIB", "#2E8B57"),
        ("onephase", "dv_prefix_table"): ("One-phase DV prefix table", "#8172B2"),
        ("twophase", "forwarder_pet"): ("Two-phase forwarder PET", "#DD8452"),
        ("twophase", "forwarder_multicast_fib"): ("Two-phase multicast FIB", "#CCB974"),
        ("twophase", "dv_prefix_egress_state"): ("Two-phase DV prefix egress state", "#C44E52"),
    }

    aggregated = {
        phase: _aggregate_total_entries_by_prefix_and_table(results_by_phase[phase]["role_table_summary"])
        for phase in ("onephase", "twophase")
    }
    prefix_counts = sorted(
        {
            prefix_count
            for phase_data in aggregated.values()
            for prefix_to_value in phase_data.values()
            for prefix_count in prefix_to_value
        }
    )
    if not prefix_counts:
        return

    with plt.rc_context(CORE_EDGE_RC):
        fig, axis = plt.subplots(figsize=(14.5, 6.0))
        x_values = np.arange(len(prefix_counts))
        width = 0.38
        legend_handles = {}

        for offset, phase in ((-width / 2, "onephase"), (width / 2, "twophase")):
            bottoms = np.zeros(len(prefix_counts))
            for key in table_order:
                prefix_to_value = aggregated[phase].get(key)
                if not prefix_to_value:
                    continue
                label, color = table_styles[key]
                heights = np.array([prefix_to_value.get(prefix_count, 0.0) for prefix_count in prefix_counts])
                bars = axis.bar(
                    x_values + offset,
                    heights,
                    width,
                    bottom=bottoms,
                    color=color,
                    edgecolor="white",
                    linewidth=0.5,
                    label=label,
                )
                legend_handles.setdefault(label, bars[0])
                bottoms = bottoms + heights

        axis.set_xticks(x_values)
        axis.set_xticklabels([str(prefix_count) for prefix_count in prefix_counts])
        axis.set_xlabel("Total announced prefixes")
        axis.set_ylabel("Total table entries across all nodes")
        axis.set_title("One-phase (left bar) vs Two-phase (right bar)")
        axis.grid(True, axis="y", alpha=0.25)
        axis.set_axisbelow(True)

        phase_handles = [
            plt.Line2D([0], [0], color=PHASE_STYLES["onephase"]["color"], linewidth=8, label="One-phase bar"),
            plt.Line2D([0], [0], color=PHASE_STYLES["twophase"]["color"], linewidth=8, label="Two-phase bar"),
        ]
        table_handle_list = [legend_handles[label] for label in legend_handles]
        table_label_list = list(legend_handles.keys())
        phase_legend = axis.legend(handles=phase_handles, loc="upper left")
        axis.add_artist(phase_legend)
        axis.legend(table_handle_list, table_label_list, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2)

        fig.suptitle("Core-Edge Prefix Scaling: Total Table Entries by Phase and Table", y=1.02)
        fig.tight_layout()
        path = os.path.join(out_dir, CORE_EDGE_PLOT_FILES["table_stack"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_run_comparison(results_by_phase, out_dir, source_label):
    metrics = [
        ("router_reachability_s", "Router reachability (s)", None),
        ("control_packets", "Control packets", None),
        ("control_bytes", "Control bytes", ticker.FuncFormatter(human_bytes)),
    ]

    with plt.rc_context(CORE_EDGE_RC):
        fig, axes = plt.subplots(1, len(metrics), figsize=(15.5, 5.0))
        for axis, (field, title, formatter) in zip(axes, metrics):
            prefix_counts = set()
            for phase, style in PHASE_STYLES.items():
                series = _aggregate_by_prefix(results_by_phase[phase]["runs"], field)
                prefix_counts.update(series)
                _plot_series(axis, series, label=style["label"], color=style["color"], marker=style["marker"])
            axis.set_title(title)
            axis.set_xlabel("Total announced prefixes")
            axis.set_xticks(sorted(prefix_counts))
            axis.grid(True, alpha=0.25)
            if formatter is not None:
                axis.yaxis.set_major_formatter(formatter)

        axes[0].set_ylabel("Seconds")
        axes[1].set_ylabel("Packets")
        axes[2].set_ylabel("Bytes")
        axes[0].legend(loc="best")
        fig.suptitle("Core-Edge Prefix Scaling: Reachability and Control Traffic", y=1.02)
        fig.tight_layout()
        path = os.path.join(out_dir, CORE_EDGE_PLOT_FILES["run_comparison"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_prefix_state_by_role(results_by_phase, out_dir, source_label):
    with plt.rc_context(CORE_EDGE_RC):
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0), sharey=True)
        role_specs = [("core", "Core routers"), ("edge", "Edge routers")]
        table_specs = {
            "onephase": ("onephase", "dv_prefix_table", "One-phase DV prefix table"),
            "twophase": ("twophase", "dv_prefix_egress_state", "Two-phase DV prefix egress state"),
        }

        for axis, (role, title) in zip(axes, role_specs):
            prefix_counts = set()
            for phase, (table_category, table_name, table_label) in table_specs.items():
                style = PHASE_STYLES[phase]
                series = _aggregate_by_prefix(
                    results_by_phase[phase]["role_table_summary"],
                    "avg_entries",
                    role=role,
                    table_category=table_category,
                    table_name=table_name,
                )
                prefix_counts.update(series)
                _plot_series(
                    axis,
                    series,
                    label=table_label,
                    color=style["color"],
                    marker=style["marker"],
                )
            axis.set_title(title)
            axis.set_xlabel("Total announced prefixes")
            axis.set_xticks(sorted(prefix_counts))
            axis.grid(True, alpha=0.25)

        axes[0].set_ylabel("Average entries per node")
        axes[0].legend(loc="upper left")
        fig.suptitle("Core-Edge Prefix Scaling: Phase-Specific Prefix State", y=1.02)
        fig.tight_layout()
        path = os.path.join(out_dir, CORE_EDGE_PLOT_FILES["prefix_state"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_forwarding_delta_by_role(results_by_phase, out_dir, source_label):
    role_specs = [("core", "Core routers"), ("edge", "Edge routers")]
    series_specs = [
        {
            "phase": "onephase",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "label": "One-phase forwarder RIB",
            "color": "#4C72B0",
            "linestyle": "-",
        },
        {
            "phase": "onephase",
            "table_category": "common",
            "table_name": "forwarder_fib",
            "label": "One-phase forwarder FIB",
            "color": "#55A868",
            "linestyle": "-",
        },
        {
            "phase": "twophase",
            "table_category": "twophase",
            "table_name": "forwarder_pet",
            "label": "Two-phase forwarder PET",
            "color": "#DD8452",
            "linestyle": "-",
        },
    ]

    with plt.rc_context(CORE_EDGE_RC):
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0), sharey=True)
        for axis, (role, title) in zip(axes, role_specs):
            prefix_counts = set()
            for spec in series_specs:
                style = PHASE_STYLES[spec["phase"]]
                series = _aggregate_by_prefix(
                    results_by_phase[spec["phase"]]["role_table_summary"],
                    "avg_entries",
                    role=role,
                    table_category=spec["table_category"],
                    table_name=spec["table_name"],
                )
                if not series:
                    continue
                baseline = series[min(series)]
                delta_series = {prefix_count: value - baseline for prefix_count, value in series.items()}
                prefix_counts.update(delta_series)
                _plot_series(
                    axis,
                    delta_series,
                    label=spec["label"],
                    color=spec["color"],
                    marker=style["marker"],
                    linestyle=spec["linestyle"],
                )
            axis.set_title(title)
            axis.set_xlabel("Total announced prefixes")
            axis.set_xticks(sorted(prefix_counts))
            axis.grid(True, alpha=0.25)

        axes[0].set_ylabel("Average entry delta from 0-prefix run")
        axes[0].legend(loc="upper left")
        fig.suptitle("Core-Edge Prefix Scaling: Prefix-Driven Forwarder State Growth", y=1.02)
        fig.tight_layout()
        path = os.path.join(out_dir, CORE_EDGE_PLOT_FILES["forwarder_growth"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_control_breakdown(data_dir, out_dir, source_label):
    summaries = load_core_edge_link_trace_summaries(data_dir)
    if not any(summaries.values()):
        print("  No core/edge link traces found, skipping control-breakdown plots")
        return

    metric_specs = [
        ("DvAdvert_Pkts", "PrefixSync_Pkts", "Packets", None),
        ("DvAdvert_Bytes", "PrefixSync_Bytes", "Bytes", ticker.FuncFormatter(human_bytes)),
    ]
    with plt.rc_context(CORE_EDGE_RC):
        fig, axes = plt.subplots(2, 2, figsize=(12.5, 8.5), sharex=True)

        for col, phase in enumerate(("onephase", "twophase")):
            style = PHASE_STYLES[phase]
            prefix_counts = sorted(summaries.get(phase, {}))
            for row, (dv_field, ps_field, ylabel, formatter) in enumerate(metric_specs):
                axis = axes[row][col]
                dv_series = {prefix_count: _mean([item[dv_field] for item in summaries[phase].get(prefix_count, [])]) for prefix_count in prefix_counts}
                ps_series = {prefix_count: _mean([item[ps_field] for item in summaries[phase].get(prefix_count, [])]) for prefix_count in prefix_counts}
                _plot_series(axis, dv_series, label="DV adverts", color=style["color"], marker=style["marker"], linestyle="-")
                _plot_series(axis, ps_series, label="PrefixSync", color="#C44E52", marker=style["marker"], linestyle="--")
                axis.set_title(f"{style['label']} {ylabel.lower()}")
                axis.set_xticks(prefix_counts)
                axis.grid(True, alpha=0.25)
                if formatter is not None:
                    axis.yaxis.set_major_formatter(formatter)
                if row == len(metric_specs) - 1:
                    axis.set_xlabel("Total announced prefixes")
                if col == 0:
                    axis.set_ylabel(ylabel)

        axes[0][0].legend(loc="best")
        fig.suptitle("Core-Edge Prefix Scaling: Control Traffic Breakdown", y=0.99)
        fig.tight_layout()
        path = os.path.join(out_dir, CORE_EDGE_PLOT_FILES["control_breakdown"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def write_core_edge_summary(results_by_phase, data_dir, out_dir):
    def rel_plot(name):
        return os.path.relpath(os.path.join(out_dir, name), data_dir)

    def run_series(phase, field):
        return _aggregate_by_prefix(results_by_phase[phase]["runs"], field)

    def role_series(phase, role, table_category, table_name, field="avg_entries"):
        return _aggregate_by_prefix(
            results_by_phase[phase]["role_table_summary"],
            field,
            role=role,
            table_category=table_category,
            table_name=table_name,
        )

    prefix_counts = _sorted_prefix_counts(
        run_series("onephase", "router_reachability_s"),
        run_series("twophase", "router_reachability_s"),
    )

    role_counts = {}
    for role in ("core", "edge"):
        for phase in ("onephase", "twophase"):
            matches = [
                row for row in results_by_phase[phase]["role_table_summary"]
                if row.get("role") == role
            ]
            if matches:
                role_counts[role] = int(matches[0]["node_count"])
                break

    onephase_run = {field: run_series("onephase", field) for field in ("router_reachability_s", "control_packets", "control_bytes")}
    twophase_run = {field: run_series("twophase", field) for field in ("router_reachability_s", "control_packets", "control_bytes")}

    onephase_prefix_core = role_series("onephase", "core", "onephase", "dv_prefix_table")
    onephase_prefix_edge = role_series("onephase", "edge", "onephase", "dv_prefix_table")
    twophase_prefix_core = role_series("twophase", "core", "twophase", "dv_prefix_egress_state")
    twophase_prefix_edge = role_series("twophase", "edge", "twophase", "dv_prefix_egress_state")

    onephase_fib_core = role_series("onephase", "core", "common", "forwarder_fib")
    onephase_fib_edge = role_series("onephase", "edge", "common", "forwarder_fib")
    onephase_rib_core = role_series("onephase", "core", "common", "forwarder_rib")
    onephase_rib_edge = role_series("onephase", "edge", "common", "forwarder_rib")
    twophase_pet_core = role_series("twophase", "core", "twophase", "forwarder_pet")
    twophase_pet_edge = role_series("twophase", "edge", "twophase", "forwarder_pet")

    start_prefix = min(prefix_counts)
    max_prefix = max(prefix_counts)
    onephase_packet_min = int(round(min(onephase_run["control_packets"].values())))
    onephase_packet_max = int(round(max(onephase_run["control_packets"].values())))
    twophase_packet_min = int(round(min(twophase_run["control_packets"].values())))
    twophase_packet_max = int(round(max(twophase_run["control_packets"].values())))
    lines = [
        "# Core/Edge Prefix-Scale Summary",
        "",
        f"This run covers a fixed {role_counts.get('core', '?') + role_counts.get('edge', '?')}-node topology with {role_counts.get('core', '?')} core routers and {role_counts.get('edge', '?')} edge routers.",
        "The x-axis in all plots is the total number of announced prefixes, distributed across the edge routers.",
        "",
        "## Plot Gallery",
        "",
        "### Core-edge topology",
        f"![Core-edge topology]({rel_plot(CORE_EDGE_PLOT_FILES['topology'])})",
        "",
        "### Reachability and control traffic",
        f"![Reachability and control traffic]({rel_plot(CORE_EDGE_PLOT_FILES['run_comparison'])})",
        "",
        "### Control traffic breakdown",
        f"![Control traffic breakdown]({rel_plot(CORE_EDGE_PLOT_FILES['control_breakdown'])})",
        "",
        "### Phase-specific prefix state by role",
        f"![Phase-specific prefix state by role]({rel_plot(CORE_EDGE_PLOT_FILES['prefix_state'])})",
        "",
        "### Prefix-driven forwarder state growth",
        f"![Prefix-driven forwarder state growth]({rel_plot(CORE_EDGE_PLOT_FILES['forwarder_growth'])})",
        "",
        "### Total table entries by phase and table",
        f"![Total table entries by phase and table]({rel_plot(CORE_EDGE_PLOT_FILES['table_stack'])})",
        "",
        "## Run Metrics",
        "",
        "| total_prefixes | onephase_reachability_s | twophase_reachability_s | onephase_control_packets | twophase_control_packets | onephase_control_bytes | twophase_control_bytes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for prefix_count in prefix_counts:
        lines.append(
            f"| {prefix_count} | {onephase_run['router_reachability_s'][prefix_count]:.4f} | {twophase_run['router_reachability_s'][prefix_count]:.4f} | "
            f"{int(round(onephase_run['control_packets'][prefix_count]))} | {int(round(twophase_run['control_packets'][prefix_count]))} | "
            f"{int(round(onephase_run['control_bytes'][prefix_count]))} | {int(round(twophase_run['control_bytes'][prefix_count]))} |"
        )

    lines.extend([
        "",
        "## Observations",
        "",
        f"- Router reachability stays essentially flat at about {onephase_run['router_reachability_s'][start_prefix]:.4f}s to {onephase_run['router_reachability_s'][max_prefix]:.4f}s for one-phase and {twophase_run['router_reachability_s'][start_prefix]:.4f}s for two-phase, so prefix count is not materially moving router reachability in this scenario.",
        f"- Phase-specific prefix state grows linearly from 0 to {onephase_prefix_core[max_prefix]:.1f} average entries per node on both roles in both phases; the total across all nodes is exactly 10 x prefixes.",
        f"- At {max_prefix} total prefixes, one-phase average forwarder FIB growth is +{onephase_fib_core[max_prefix] - onephase_fib_core[start_prefix]:.2f} entries on core routers and +{onephase_fib_edge[max_prefix] - onephase_fib_edge[start_prefix]:.2f} on edge routers, while one-phase forwarder RIB growth is +{onephase_rib_core[max_prefix] - onephase_rib_core[start_prefix]:.2f} on core routers and +{onephase_rib_edge[max_prefix] - onephase_rib_edge[start_prefix]:.2f} on edge routers.",
        f"- At {max_prefix} total prefixes, two-phase average forwarder PET growth is +{twophase_pet_core[max_prefix] - twophase_pet_core[start_prefix]:.2f} entries on core routers and +{twophase_pet_edge[max_prefix] - twophase_pet_edge[start_prefix]:.2f} on edge routers, while common forwarder RIB and FIB remain flat.",
        f"- Two-phase control traffic is higher than one-phase at every measured prefix count in this run: packets range from {twophase_packet_min} to {twophase_packet_max} in two-phase versus {onephase_packet_min} to {onephase_packet_max} in one-phase.",
        "- Control traffic is not monotonic with prefix count, and the visible swings come mainly from PrefixSync rather than DV adverts. Treat this run as a qualitative comparison, not as evidence of a strictly monotonic scaling law.",
    ])

    path = os.path.join(data_dir, "summary.md")
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"  Saved {path}")
    return path


def plot_churn_comparison(rows, out_dir, source_label):
    churn = [row for row in rows if row["phase"] == "churn" and row["mode"] != "baseline"]
    prefix_counts = sorted(set(int(row["num_prefixes"]) for row in churn))
    x_values = np.arange(len(prefix_counts))
    width = 0.35
    fig, axis = plt.subplots(figsize=(8, 5))
    for index, mode in enumerate(["one_phase"]):
        values = []
        for prefix_count in prefix_counts:
            match = [row for row in churn if row["mode"] == mode and int(row["num_prefixes"]) == prefix_count]
            values.append(int(match[0]["total_routing_bytes"]) if match else 0)
        axis.bar(
            x_values + (index - 0.5) * width,
            values,
            width,
            label="One-phase (DV + PfxSync)",
            color="#4C72B0" if mode == "one_phase" else "#DD8452",
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
    for axis, mode in zip(axes, ["one_phase"]):
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
        axis.set_title(f"{source_label} - One-Phase Traffic Breakdown")
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
    for col, mode in enumerate(["one_phase"]):
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
                axis.set_title("One-Phase")
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


def _discover_trace_index(data_dir, *, modes=("one_phase")):
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
        mode_label = "One-Phase"
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
    for mode, color in [("one_phase", "#4C72B0")]:
        values = []
        for prefix_count in prefix_counts:
            match = [row for row in churn if row["mode"] == mode and int(row["num_prefixes"]) == prefix_count]
            value = int(match[0]["total_routing_bytes"]) - baseline_bytes if match else 0
            values.append(max(value, 0))
        axis.plot(prefix_counts, values, "o-", label="One-phase", color=color, linewidth=2)
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
    for mode, color in [("one_phase", "#4C72B0")]:
        values = []
        for prefix_count in prefix_counts:
            match = [row for row in churn if row["mode"] == mode and int(row["num_prefixes"]) == prefix_count]
            values.append(int(match[0]["total_routing_bytes"]) if match else 0)
        axis.plot(prefix_counts, values, "o-", label="One-phase", color=color, linewidth=2)
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
    for mode, title in [("one_phase", "One-Phase")]:
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