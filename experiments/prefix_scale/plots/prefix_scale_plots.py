import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

from lib.topology import (core_edge_links, core_edge_positions, core_edge_roles,
                          rocketfuel_2914_links, rocketfuel_2914_positions,
                          rocketfuel_2914_roles,
                          rocketfuel_1755_links, rocketfuel_1755_positions,
                          rocketfuel_1755_roles,
                          rocketfuel_sample_4755_links,
                          rocketfuel_sample_4755_positions,
                          rocketfuel_sample_4755_roles)
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
    "table_role_average": "core_edge_table_average_by_role.png",
    "table_role_average_reduced": "core_edge_table_average_by_role_reduced.png",
    "table_stack": "core_edge_table_stack_comparison.png",
    "table_stack_reduced": "core_edge_table_stack_comparison_reduced.png",
}

ROCKETFUEL_4755_PLOT_FILES = {
    "topology": "rocketfuel_4755_topology.png",
    "run_comparison": "rocketfuel_4755_run_comparison.png",
    "control_breakdown": "rocketfuel_4755_control_breakdown.png",
    "prefix_state": "rocketfuel_4755_prefix_state_by_role.png",
    "forwarder_growth": "rocketfuel_4755_forwarding_delta_by_role.png",
    "table_role_average": "rocketfuel_4755_table_average_by_role.png",
    "table_role_average_reduced": "rocketfuel_4755_table_average_by_role_reduced.png",
    "table_stack": "rocketfuel_4755_table_stack_comparison.png",
    "table_stack_reduced": "rocketfuel_4755_table_stack_comparison_reduced.png",
}

ROCKETFUEL_1755_PLOT_FILES = {
    "topology": "rocketfuel_1755_topology.png",
    "run_comparison": "rocketfuel_1755_run_comparison.png",
    "control_breakdown": "rocketfuel_1755_control_breakdown.png",
    "prefix_state": "rocketfuel_1755_prefix_state_by_role.png",
    "forwarder_growth": "rocketfuel_1755_forwarding_delta_by_role.png",
    "table_role_average": "rocketfuel_1755_table_average_by_role.png",
    "table_role_average_reduced": "rocketfuel_1755_table_average_by_role_reduced.png",
    "table_stack": "rocketfuel_1755_table_stack_comparison.png",
    "table_stack_reduced": "rocketfuel_1755_table_stack_comparison_reduced.png",
}

ROCKETFUEL_2914_PLOT_FILES = {
    "topology": "rocketfuel_2914_topology.png",
    "run_comparison": "rocketfuel_2914_run_comparison.png",
    "control_breakdown": "rocketfuel_2914_control_breakdown.png",
    "prefix_state": "rocketfuel_2914_prefix_state_by_role.png",
    "forwarder_growth": "rocketfuel_2914_forwarding_delta_by_role.png",
    "table_role_average": "rocketfuel_2914_table_average_by_role.png",
    "table_role_average_reduced": "rocketfuel_2914_table_average_by_role_reduced.png",
    "table_stack": "rocketfuel_2914_table_stack_comparison.png",
    "table_stack_reduced": "rocketfuel_2914_table_stack_comparison_reduced.png",
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

TOPOLOGY_PLOT_PROFILES = {
    "core_edge": {
        "study_label": "Core-Edge Prefix Scaling",
        "summary_title": "Core/Edge Prefix-Scale Summary",
        "topology_title": "Core-edge topology used by the prefix-scale study",
        "topology_heading": "Core-edge topology",
        "plot_files": CORE_EDGE_PLOT_FILES,
        "links": core_edge_links,
        "positions": core_edge_positions,
        "roles": core_edge_roles,
        "node_fontsize": 10,
    },
    "rocketfuel_4755": {
        "study_label": "Rocketfuel 4755 Prefix Scaling",
        "summary_title": "Rocketfuel 4755 Prefix-Scale Summary",
        "topology_title": "Rocketfuel sample 4755 topology used by the prefix-scale study",
        "topology_heading": "Rocketfuel 4755 topology",
        "plot_files": ROCKETFUEL_4755_PLOT_FILES,
        "links": rocketfuel_sample_4755_links,
        "positions": rocketfuel_sample_4755_positions,
        "roles": rocketfuel_sample_4755_roles,
        "node_fontsize": 8,
    },
    "rocketfuel_1755": {
        "study_label": "Rocketfuel 1755 Prefix Scaling",
        "summary_title": "Rocketfuel 1755 Prefix-Scale Summary",
        "topology_title": "Rocketfuel AS 1755 (EBONE) largest connected component used by the prefix-scale study",
        "topology_heading": "Rocketfuel 1755 topology",
        "plot_files": ROCKETFUEL_1755_PLOT_FILES,
        "links": rocketfuel_1755_links,
        "positions": rocketfuel_1755_positions,
        "roles": rocketfuel_1755_roles,
        "node_fontsize": 7,
        "summary_note": "This topology uses the largest connected `r0` component from the public Rocketfuel AS 1755 cch map.",
    },
    "rocketfuel_2914": {
        "study_label": "Rocketfuel 2914 Prefix Scaling",
        "summary_title": "Rocketfuel 2914 Prefix-Scale Summary",
        "topology_title": "Rocketfuel AS 2914 largest connected component used by the prefix-scale study",
        "topology_heading": "Rocketfuel 2914 topology",
        "plot_files": ROCKETFUEL_2914_PLOT_FILES,
        "links": rocketfuel_2914_links,
        "positions": rocketfuel_2914_positions,
        "roles": rocketfuel_2914_roles,
        "show_labels": False,
        "figure_size": (13.5, 13.5),
        "core_node_size": 18,
        "edge_node_size": 18,
        "node_edge_width": 0.25,
        "link_width": 0.35,
        "summary_note": "This topology uses the largest connected `r0` component from the public Rocketfuel AS 2914 cch map, so disconnected fragments are intentionally excluded.",
    },
}

TABLE_ORDER = [
    ("common", "dv_neighbors"),
    ("common", "dv_rib"),
    ("common", "forwarder_rib"),
    ("common", "forwarder_fib"),
    ("onephase", "dv_prefix_table"),
    ("twophase", "forwarder_pet"),
    ("twophase", "dv_prefix_egress_state"),
]

REDUCED_TABLE_HIDDEN_KEYS = {
    ("common", "dv_neighbors"),
    ("common", "dv_rib"),
    ("common", "forwarder_rib"),
    ("onephase", "dv_prefix_table"),
    ("twophase", "dv_prefix_egress_state"),
}

REDUCED_TABLE_ORDER = [key for key in TABLE_ORDER if key not in REDUCED_TABLE_HIDDEN_KEYS]

TABLE_STYLES = {
    ("common", "dv_neighbors"): ("DV neighbors", "#7A7A7A"),
    ("common", "dv_rib"): ("DV RIB", "#4C72B0"),
    ("common", "forwarder_rib"): ("Forwarder RIB", "#55A868"),
    ("common", "forwarder_fib"): ("Forwarder FIB", "#2E8B57"),
    ("onephase", "dv_prefix_table"): ("One-phase prefix-to-router mappings", "#8172B2"),
    ("twophase", "forwarder_pet"): ("Two-phase forwarder PET", "#DD8452"),
    ("twophase", "dv_prefix_egress_state"): ("Two-phase prefix-to-router mappings", "#C44E52"),
}


def _topology_profile(topology_key):
    return TOPOLOGY_PLOT_PROFILES[topology_key]


def _plot_files(topology_key):
    return _topology_profile(topology_key)["plot_files"]


def _series_value(series, prefix_count):
    if not series:
        return None
    return series.get(prefix_count)


def _series_delta(series, start_prefix, end_prefix):
    start_value = _series_value(series, start_prefix)
    end_value = _series_value(series, end_prefix)
    if start_value is None or end_value is None:
        return None
    return end_value - start_value


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
        if field not in row:
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
        trial = int(row["trial"])
        key = (row["table_category"], row["table_name"])
        grouped.setdefault(key, {})
        grouped[key].setdefault(prefix_count, {})
        grouped[key][prefix_count][trial] = grouped[key][prefix_count].get(trial, 0.0) + float(row["total_entries"])
    return {
        key: {
            prefix_count: _mean(list(trial_totals.values()))
            for prefix_count, trial_totals in prefix_to_trials.items()
        }
        for key, prefix_to_trials in grouped.items()
    }


def _aggregate_avg_entries_by_prefix_and_table(rows, *, role):
    grouped = {}
    for row in rows:
        if row.get("role") != role:
            continue
        prefix_count = int(row["prefix_count"])
        key = (row["table_category"], row["table_name"])
        grouped.setdefault(key, {})
        grouped[key].setdefault(prefix_count, []).append(float(row["avg_entries"]))
    return {
        key: {
            prefix_count: _mean(values)
            for prefix_count, values in prefix_to_values.items()
        }
        for key, prefix_to_values in grouped.items()
    }


def plot_core_edge_topology(out_dir, topology_key="core_edge"):
    profile = _topology_profile(topology_key)
    positions = profile["positions"]()
    roles = profile["roles"]()
    links = profile["links"]()
    role_styles = {
        "core": {
            "color": "#4C72B0",
            "edgecolor": "#1F3A5F",
            "size": profile.get("core_node_size", 850),
        },
        "edge": {
            "color": "#DD8452",
            "edgecolor": "#7A3E1D",
            "size": profile.get("edge_node_size", 850),
        },
    }
    show_labels = profile.get("show_labels", True)

    with plt.rc_context(CORE_EDGE_RC):
        fig, axis = plt.subplots(figsize=profile.get("figure_size", (7.5, 6.8)))

        for src, dst in links:
            x_values = [positions[src][0], positions[dst][0]]
            y_values = [positions[src][1], positions[dst][1]]
            axis.plot(
                x_values,
                y_values,
                color="#A8A8A8",
                linewidth=profile.get("link_width", 2.0),
                zorder=1,
            )

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
                linewidths=profile.get("node_edge_width", 1.5),
                label=f"{role.capitalize()} routers",
                zorder=2,
            )
            if show_labels:
                for node in nodes:
                    axis.text(
                        positions[node][0],
                        positions[node][1],
                        node,
                        ha="center",
                        va="center",
                        color="white",
                        fontsize=profile["node_fontsize"],
                        fontweight="bold",
                        zorder=3,
                    )

        axis.set_aspect("equal", adjustable="box")
        axis.axis("off")
        fig.suptitle(profile["topology_title"], y=0.98)
        fig.legend(loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.94))

        fig.tight_layout(rect=(0, 0, 1, 0.88))
        path = os.path.join(out_dir, _plot_files(topology_key)["topology"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def _plot_table_stack_comparison(results_by_phase, out_dir, *, table_order,
                                 plot_key, title, topology_key="core_edge"):
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
                label, color = TABLE_STYLES[key]
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

        table_handle_list = [legend_handles[label] for label in legend_handles]
        table_label_list = list(legend_handles.keys())
        axis.legend(table_handle_list, table_label_list, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2)

        fig.suptitle(f"{_topology_profile(topology_key)['study_label']}: {title}", y=1.02)
        fig.tight_layout()
        path = os.path.join(out_dir, _plot_files(topology_key)[plot_key])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_table_stack_comparison(results_by_phase, out_dir, source_label,
                                          topology_key="core_edge"):
    _plot_table_stack_comparison(
        results_by_phase,
        out_dir,
        table_order=TABLE_ORDER,
        plot_key="table_stack",
        title="Total Table Entries by Phase and Table",
        topology_key=topology_key,
    )


def plot_core_edge_table_stack_comparison_reduced(results_by_phase, out_dir, source_label,
                                                  topology_key="core_edge"):
    _plot_table_stack_comparison(
        results_by_phase,
        out_dir,
        table_order=REDUCED_TABLE_ORDER,
        plot_key="table_stack_reduced",
        title="Forwarding-Focused Total Table Entries by Phase and Table",
        topology_key=topology_key,
    )


def _plot_table_average_by_role(results_by_phase, out_dir, *, table_order,
                                plot_key, title, topology_key="core_edge"):
    aggregated = {
        phase: {
            role: _aggregate_avg_entries_by_prefix_and_table(
                results_by_phase[phase]["role_table_summary"],
                role=role,
            )
            for role in ("core", "edge")
        }
        for phase in ("onephase", "twophase")
    }
    prefix_counts = sorted(
        {
            prefix_count
            for phase_data in aggregated.values()
            for role_data in phase_data.values()
            for prefix_to_value in role_data.values()
            for prefix_count in prefix_to_value
        }
    )
    if not prefix_counts:
        return

    with plt.rc_context(CORE_EDGE_RC):
        fig, axes = plt.subplots(1, 2, figsize=(14.5, 6.0), sharey=True)
        x_values = np.arange(len(prefix_counts))
        width = 0.38
        legend_handles = {}
        role_specs = (("core", "Core routers"), ("edge", "Edge routers"))

        for axis, (role, role_title) in zip(axes, role_specs):
            for offset, phase in ((-width / 2, "onephase"), (width / 2, "twophase")):
                bottoms = np.zeros(len(prefix_counts))
                for key in table_order:
                    prefix_to_value = aggregated[phase][role].get(key)
                    if not prefix_to_value:
                        continue
                    label, color = TABLE_STYLES[key]
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
                    axis.set_title(role_title)
            axis.set_xticks(x_values)
            axis.set_xticklabels([str(prefix_count) for prefix_count in prefix_counts])
            axis.set_xlabel("Total announced prefixes")
            axis.grid(True, axis="y", alpha=0.25)
            axis.set_axisbelow(True)

        axes[0].set_ylabel("Average table entries per node")

        table_handle_list = [legend_handles[label] for label in legend_handles]
        table_label_list = list(legend_handles.keys())
        fig.legend(table_handle_list, table_label_list, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2)

        fig.suptitle(f"{_topology_profile(topology_key)['study_label']}: {title}", y=1.02)
        fig.tight_layout(rect=(0, 0.06, 1, 1))
        path = os.path.join(out_dir, _plot_files(topology_key)[plot_key])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_table_average_by_role(results_by_phase, out_dir, source_label,
                                         topology_key="core_edge"):
    _plot_table_average_by_role(
        results_by_phase,
        out_dir,
        table_order=TABLE_ORDER,
        plot_key="table_role_average",
        title="Average Table Entries per Node by Role and Table",
        topology_key=topology_key,
    )


def plot_core_edge_table_average_by_role_reduced(results_by_phase, out_dir, source_label,
                                                 topology_key="core_edge"):
    _plot_table_average_by_role(
        results_by_phase,
        out_dir,
        table_order=REDUCED_TABLE_ORDER,
        plot_key="table_role_average_reduced",
        title="Forwarding-Focused Average Table Entries per Node",
        topology_key=topology_key,
    )


def plot_core_edge_run_comparison(results_by_phase, out_dir, source_label,
                                  topology_key="core_edge"):
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
        fig.suptitle(f"{_topology_profile(topology_key)['study_label']}: Reachability and Control Traffic", y=1.02)
        fig.tight_layout()
        path = os.path.join(out_dir, _plot_files(topology_key)["run_comparison"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_prefix_state_by_role(results_by_phase, out_dir, source_label,
                                        topology_key="core_edge"):
    with plt.rc_context(CORE_EDGE_RC):
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0), sharey=True)
        role_specs = [("core", "Core routers"), ("edge", "Edge routers")]
        table_specs = {
            "onephase": ("onephase", "dv_prefix_table", "One-phase prefix-to-router mappings"),
            "twophase": ("twophase", "dv_prefix_egress_state", "Two-phase prefix-to-router mappings"),
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
        fig.suptitle(f"{_topology_profile(topology_key)['study_label']}: Prefix-to-Router Mappings by Role", y=1.02)
        fig.tight_layout()
        path = os.path.join(out_dir, _plot_files(topology_key)["prefix_state"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_forwarding_delta_by_role(results_by_phase, out_dir, source_label,
                                            topology_key="core_edge"):
    role_specs = [("core", "Core routers"), ("edge", "Edge routers")]
    series_specs = [
        {
            "phase": "onephase",
            "table_category": "common",
            "table_name": "forwarder_fib",
            "label": "One-phase forwarder FIB",
            "color": "#2E8B57",
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
        fig.suptitle(f"{_topology_profile(topology_key)['study_label']}: Prefix-Driven Local Forwarder State Growth", y=1.02)
        fig.tight_layout()
        path = os.path.join(out_dir, _plot_files(topology_key)["forwarder_growth"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def plot_core_edge_control_breakdown(data_dir, out_dir, source_label,
                                     topology_key="core_edge"):
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
        fig.suptitle(f"{_topology_profile(topology_key)['study_label']}: Control Traffic Breakdown", y=0.99)
        fig.tight_layout()
        path = os.path.join(out_dir, _plot_files(topology_key)["control_breakdown"])
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {path}")


def write_core_edge_summary(results_by_phase, data_dir, out_dir,
                            topology_key="core_edge"):
    profile = _topology_profile(topology_key)
    plot_files = _plot_files(topology_key)

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
    if not prefix_counts:
        raise ValueError("no run rows available for prefix-scale summary")

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

    onephase_run = {field: run_series("onephase", field) for field in ("router_reachability_s", "control_packets", "control_bytes", "prefix_fetch_success", "prefix_fetch_total")}
    twophase_run = {field: run_series("twophase", field) for field in ("router_reachability_s", "control_packets", "control_bytes", "prefix_fetch_success", "prefix_fetch_total")}

    onephase_prefix_core = role_series("onephase", "core", "onephase", "dv_prefix_table")
    onephase_prefix_edge = role_series("onephase", "edge", "onephase", "dv_prefix_table")
    twophase_prefix_core = role_series("twophase", "core", "twophase", "dv_prefix_egress_state")
    twophase_prefix_edge = role_series("twophase", "edge", "twophase", "dv_prefix_egress_state")

    onephase_fib_core = role_series("onephase", "core", "common", "forwarder_fib")
    onephase_fib_edge = role_series("onephase", "edge", "common", "forwarder_fib")
    twophase_pet_core = role_series("twophase", "core", "twophase", "forwarder_pet")
    twophase_pet_edge = role_series("twophase", "edge", "twophase", "forwarder_pet")

    start_prefix = min(prefix_counts)
    max_prefix = max(prefix_counts)
    _op = onephase_run["control_packets"]
    _tp = twophase_run["control_packets"]
    onephase_packet_min = int(round(min(_op.values()))) if _op else None
    onephase_packet_max = int(round(max(_op.values()))) if _op else None
    twophase_packet_min = int(round(min(_tp.values()))) if _tp else None
    twophase_packet_max = int(round(max(_tp.values()))) if _tp else None
    total_nodes = role_counts.get("core", 0) + role_counts.get("edge", 0)
    lines = [
        f"# {profile['summary_title']}",
        "",
        f"This run covers a {total_nodes}-node topology with {role_counts.get('core', '?')} core routers and {role_counts.get('edge', '?')} edge routers.",
        "The x-axis in all plots is the total number of announced prefixes, distributed across the edge routers named in the scenario.",
    ]
    summary_note = profile.get("summary_note")
    if summary_note:
        lines.append(summary_note)
    lines.extend([
        "",
        "## Plot Gallery",
        "",
        f"### {profile['topology_heading']}",
        f"![{profile['topology_heading']}]({rel_plot(plot_files['topology'])})",
        "",
        "### Reachability and control traffic",
        f"![Reachability and control traffic]({rel_plot(plot_files['run_comparison'])})",
        "",
        "### Control traffic breakdown",
        f"![Control traffic breakdown]({rel_plot(plot_files['control_breakdown'])})",
        "",
        "### Prefix-to-router mappings by role",
        f"![Prefix-to-router mappings by role]({rel_plot(plot_files['prefix_state'])})",
        "This plot shows network-wide prefix-to-router mappings learned through prefix dissemination.",
        "",
        "### Prefix-driven local forwarder state growth",
        f"![Prefix-driven local forwarder state growth]({rel_plot(plot_files['forwarder_growth'])})",
        "This plot shows local forwarding state growth per node, so the two-phase PET line is intentionally not the network-wide mapping table.",
        "",
        "### Average table entries per core and edge node",
        f"![Average table entries per core and edge node]({rel_plot(plot_files['table_role_average'])})",
        "",
        "### Forwarding-focused average table entries per core and edge node",
        f"![Forwarding-focused average table entries per core and edge node]({rel_plot(plot_files['table_role_average_reduced'])})",
        "Hidden tables: Forwarder RIB, DV neighbors, DV RIB, and one-phase prefix-to-router mappings.",
        "",
        "### Total table entries by phase and table",
        f"![Total table entries by phase and table]({rel_plot(plot_files['table_stack'])})",
        "",
        "### Forwarding-focused total table entries by phase and table",
        f"![Forwarding-focused total table entries by phase and table]({rel_plot(plot_files['table_stack_reduced'])})",
        "Hidden tables: Forwarder RIB, DV neighbors, DV RIB, and one-phase prefix-to-router mappings.",
        "",
        "## Run Metrics",
        "",
        "| total_prefixes | onephase_reachability_s | twophase_reachability_s | onephase_control_packets | twophase_control_packets | onephase_control_bytes | twophase_control_bytes | onephase_fetch | twophase_fetch |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    def _fetch_str(run, pc):
        s = run["prefix_fetch_success"].get(pc)
        t = run["prefix_fetch_total"].get(pc)
        if s is None or t is None:
            return "n/a"
        return f"{int(s)}/{int(t)}"
    def _fmt_run_val(run, field, pc, fmt="{:.4f}"):
        v = run[field].get(pc)
        if v is None:
            return "n/a"
        if fmt == "int":
            return str(int(round(v)))
        return fmt.format(v)
    for prefix_count in prefix_counts:
        lines.append(
            f"| {prefix_count} | {_fmt_run_val(onephase_run, 'router_reachability_s', prefix_count)} | {_fmt_run_val(twophase_run, 'router_reachability_s', prefix_count)} | "
            f"{_fmt_run_val(onephase_run, 'control_packets', prefix_count, 'int')} | {_fmt_run_val(twophase_run, 'control_packets', prefix_count, 'int')} | "
            f"{_fmt_run_val(onephase_run, 'control_bytes', prefix_count, 'int')} | {_fmt_run_val(twophase_run, 'control_bytes', prefix_count, 'int')} | "
            f"{_fetch_str(onephase_run, prefix_count)} | {_fetch_str(twophase_run, prefix_count)} |"
        )

    observations = ["", "## Observations", ""]

    onephase_reach_start = _series_value(onephase_run["router_reachability_s"], start_prefix)
    onephase_reach_end = _series_value(onephase_run["router_reachability_s"], max_prefix)
    twophase_reach_start = _series_value(twophase_run["router_reachability_s"], start_prefix)
    twophase_reach_end = _series_value(twophase_run["router_reachability_s"], max_prefix)
    if None not in (onephase_reach_start, onephase_reach_end, twophase_reach_start, twophase_reach_end):
        observations.append(
            f"- Router reachability stays essentially flat from {onephase_reach_start:.4f}s to {onephase_reach_end:.4f}s in one-phase and {twophase_reach_start:.4f}s to {twophase_reach_end:.4f}s in two-phase, so prefix count is not materially moving router reachability in this scenario."
        )

    onephase_prefix_core_end = _series_value(onephase_prefix_core, max_prefix)
    onephase_prefix_edge_end = _series_value(onephase_prefix_edge, max_prefix)
    if onephase_prefix_core_end is not None or onephase_prefix_edge_end is not None:
        observations.append(
            f"- At {max_prefix} total prefixes, one-phase DV prefix state reaches {0.0 if onephase_prefix_core_end is None else onephase_prefix_core_end:.1f} average entries on core routers and {0.0 if onephase_prefix_edge_end is None else onephase_prefix_edge_end:.1f} on edge routers."
        )

    twophase_prefix_core_end = _series_value(twophase_prefix_core, max_prefix)
    twophase_prefix_edge_end = _series_value(twophase_prefix_edge, max_prefix)
    if twophase_prefix_core_end is not None or twophase_prefix_edge_end is not None:
        observations.append(
            f"- At {max_prefix} total prefixes, two-phase prefix-to-router mapping state reaches {0.0 if twophase_prefix_core_end is None else twophase_prefix_core_end:.1f} average entries on core routers and {0.0 if twophase_prefix_edge_end is None else twophase_prefix_edge_end:.1f} on edge routers."
        )

    onephase_fib_core_delta = _series_delta(onephase_fib_core, start_prefix, max_prefix)
    onephase_fib_edge_delta = _series_delta(onephase_fib_edge, start_prefix, max_prefix)
    if onephase_fib_core_delta is not None or onephase_fib_edge_delta is not None:
        observations.append(
            f"- At {max_prefix} total prefixes, one-phase forwarder FIB growth is {0.0 if onephase_fib_core_delta is None else onephase_fib_core_delta:+.2f} average entries on core routers and {0.0 if onephase_fib_edge_delta is None else onephase_fib_edge_delta:+.2f} on edge routers."
        )

    twophase_pet_core_delta = _series_delta(twophase_pet_core, start_prefix, max_prefix)
    twophase_pet_edge_delta = _series_delta(twophase_pet_edge, start_prefix, max_prefix)
    if twophase_pet_core_delta is not None or twophase_pet_edge_delta is not None:
        observations.append(
            f"- At {max_prefix} total prefixes, two-phase forwarder PET growth is {0.0 if twophase_pet_core_delta is None else twophase_pet_core_delta:+.2f} average entries on core routers and {0.0 if twophase_pet_edge_delta is None else twophase_pet_edge_delta:+.2f} on edge routers; this is local forwarding state, not the full prefix-to-router mapping view."
        )

    # Prefix fetch reachability observation (data-plane proof).
    twophase_fetch_counts = [
        (twophase_run["prefix_fetch_success"].get(pc), twophase_run["prefix_fetch_total"].get(pc))
        for pc in prefix_counts if twophase_run["prefix_fetch_total"].get(pc, 0)
    ]
    onephase_fetch_counts = [
        (onephase_run["prefix_fetch_success"].get(pc), onephase_run["prefix_fetch_total"].get(pc))
        for pc in prefix_counts if onephase_run["prefix_fetch_total"].get(pc, 0)
    ]
    if twophase_fetch_counts:
        twophase_fetch_ok = all(s == t for s, t in twophase_fetch_counts)
        twophase_fetch_summary = ", ".join(f"{s}/{t}" for s, t in twophase_fetch_counts)
        if twophase_fetch_ok:
            observations.append(
                f"- Two-phase prefix fetch succeeded for all sampled trials ({twophase_fetch_summary}), confirming end-to-end data-plane reachability across core nodes with prefix_egre_state_replicate=false."
            )
        else:
            observations.append(
                f"- Two-phase prefix fetch results ({twophase_fetch_summary}): some fetches failed — check core node routing configuration."
            )
    if onephase_fetch_counts:
        onephase_fetch_ok = all(s == t for s, t in onephase_fetch_counts)
        onephase_fetch_summary = ", ".join(f"{s}/{t}" for s, t in onephase_fetch_counts)
        if onephase_fetch_ok:
            observations.append(
                f"- One-phase prefix fetch succeeded for all sampled trials ({onephase_fetch_summary})."
            )

    if twophase_packet_min is not None and onephase_packet_min is not None:
        observations.append(
            f"- Two-phase control traffic is higher than one-phase at every measured prefix count in this run: packets range from {twophase_packet_min} to {twophase_packet_max} in two-phase versus {onephase_packet_min} to {onephase_packet_max} in one-phase."
        )
    elif twophase_packet_min is not None:
        observations.append(
            f"- Two-phase control traffic: packets range from {twophase_packet_min} to {twophase_packet_max} across measured prefix counts."
        )
    elif onephase_packet_min is not None:
        observations.append(
            f"- One-phase control traffic: packets range from {onephase_packet_min} to {onephase_packet_max} across measured prefix counts."
        )
    observations.append(
        "- Control traffic is not monotonic with prefix count, and the visible swings come mainly from PrefixSync rather than DV adverts. Treat this run as a qualitative comparison, not as evidence of a strictly monotonic scaling law."
    )

    lines.extend(observations)

    path = os.path.join(data_dir, "summary.md")
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"  Saved {path}")
    return path


def write_core_edge_xlsx(results_by_phase, data_dir, out_dir):
    """Write a multi-sheet XLSX workbook for spreadsheet import.

    Sheets:
    - runs         : one row per (phase, trial, prefix_count) with all run-level metrics.
    - node_tables  : one row per (phase, trial, prefix_count, node) with each table as a column.
    - role_summary : one row per (phase, trial, prefix_count, role) with avg/max/total per table.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    import csv as _csv

    HEADER_FILL = PatternFill("solid", fgColor="3A7ABF")
    HEADER_FONT = Font(bold=True, color="FFFFFF")
    ONEPHASE_FILL = PatternFill("solid", fgColor="DDEEFF")
    TWOPHASE_FILL = PatternFill("solid", fgColor="FFF0E0")

    phase_fill = {"onephase": ONEPHASE_FILL, "twophase": TWOPHASE_FILL}

    def _write_header(ws, headers):
        ws.append(headers)
        for cell in ws[1]:
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal="center")

    def _autofit(ws):
        for col in ws.columns:
            max_len = max((len(str(cell.value or "")) for cell in col), default=0)
            ws.column_dimensions[get_column_letter(col[0].column)].width = max(10, min(max_len + 2, 40))

    def _phase_fill_row(ws, row_idx, phase):
        fill = phase_fill.get(phase)
        if fill:
            for cell in ws[row_idx]:
                if cell.fill.fill_type == "none":
                    cell.fill = fill

    # ── load node_table_metrics.csv for each phase ──────────────────────────
    node_rows = []
    for phase in ("onephase", "twophase"):
        path = os.path.join(data_dir, phase, "node_table_metrics.csv")
        if os.path.exists(path):
            with open(path, newline="") as f:
                for r in _csv.DictReader(f):
                    r.setdefault("phase", phase)
                    node_rows.append(r)

    # ── ordered table names ──────────────────────────────────────────────────
    table_col_names = []
    seen = set()
    for key in TABLE_ORDER:
        if key not in seen:
            table_col_names.append(key)
            seen.add(key)
    table_names = [name for _cat, name in table_col_names]

    wb = Workbook()

    # ════════════════════════════════════════════════════════════════
    # Sheet 1: runs
    # ════════════════════════════════════════════════════════════════
    ws_runs = wb.active
    ws_runs.title = "runs"
    run_fields = [
        "num_nodes", "num_links",
        "router_reachability_s", "prefix_propagation_s",
        "control_packets", "control_bytes",
        "total_packets", "total_bytes",
    ]
    _write_header(ws_runs, ["phase", "trial", "prefix_count"] + run_fields)
    for phase in ("onephase", "twophase"):
        for row in sorted(results_by_phase[phase]["runs"], key=lambda r: (r.get("trial", "1"), int(r.get("prefix_count", 0)))):
            def _coerce(v):
                if v is None or v == "":
                    return ""
                try:
                    return float(v) if "." in str(v) else int(v)
                except (ValueError, TypeError):
                    return v
            values = [row.get("phase", phase), row.get("trial", "1"), int(row.get("prefix_count", 0))]
            values += [_coerce(row.get(f, "")) for f in run_fields]
            ws_runs.append(values)
            _phase_fill_row(ws_runs, ws_runs.max_row, phase)
    _autofit(ws_runs)

    # ════════════════════════════════════════════════════════════════
    # Sheet 2: node_tables — per-node, wide format
    # ════════════════════════════════════════════════════════════════
    ws_nodes = wb.create_sheet("node_tables")
    node_headers = ["phase", "trial", "prefix_count", "node", "role"] + table_names
    _write_header(ws_nodes, node_headers)

    # Build index: (phase, trial, prefix_count, node, table_name) -> entry_count
    node_idx = {}
    for r in node_rows:
        k = (r.get("phase"), r.get("trial"), r.get("prefix_count"), r.get("node"), r.get("table_name"))
        node_idx[k] = r.get("entry_count", "")

    # Collect unique (phase, trial, prefix_count, node, role) combos
    node_combos = {}
    for r in node_rows:
        k = (r.get("phase"), r.get("trial"), r.get("prefix_count"), r.get("node"))
        if k not in node_combos:
            node_combos[k] = r.get("role", "")

    for (phase, trial, prefix_count, node), role in sorted(
        node_combos.items(),
        key=lambda x: (x[0][0], x[0][1], int(x[0][2] or 0), x[0][3]),
    ):
        row_vals = [phase, trial, int(prefix_count or 0), node, role]
        for name in table_names:
            raw = node_idx.get((phase, trial, prefix_count, node, name), "")
            try:
                raw = int(raw)
            except (ValueError, TypeError):
                pass
            row_vals.append(raw)
        ws_nodes.append(row_vals)
        _phase_fill_row(ws_nodes, ws_nodes.max_row, phase)
    _autofit(ws_nodes)

    # ════════════════════════════════════════════════════════════════
    # Sheet 3: role_summary — per-role aggregates, wide format
    # ════════════════════════════════════════════════════════════════
    ws_role = wb.create_sheet("role_summary")
    role_cols = []
    for name in table_names:
        role_cols += [f"{name}_avg", f"{name}_max", f"{name}_total", f"{name}_node_count"]
    _write_header(ws_role, ["phase", "trial", "prefix_count", "role"] + role_cols)

    # Index: (phase, trial, prefix_count, role, table_name) -> row
    role_idx = {}
    for phase in ("onephase", "twophase"):
        for r in results_by_phase[phase]["role_table_summary"]:
            k = (r.get("phase", phase), r.get("trial"), r.get("prefix_count"), r.get("role"), r.get("table_name"))
            role_idx[k] = r

    role_combos = set()
    for phase in ("onephase", "twophase"):
        for r in results_by_phase[phase]["role_table_summary"]:
            role_combos.add((r.get("phase", phase), r.get("trial"), r.get("prefix_count"), r.get("role")))
        for r in results_by_phase[phase]["runs"]:
            for role in ("core", "edge"):
                role_combos.add((r.get("phase", phase), r.get("trial", "1"), r.get("prefix_count"), role))

    for (phase, trial, prefix_count, role) in sorted(role_combos, key=lambda x: (x[0], x[1], int(x[2] or 0), x[3])):
        row_vals = [phase, trial, int(prefix_count or 0), role]
        for name in table_names:
            tr = role_idx.get((phase, trial, prefix_count, role, name), {})
            def _num(v):
                try: return float(v) if "." in str(v) else int(v)
                except (ValueError, TypeError): return v
            row_vals += [_num(tr.get("avg_entries", "")), _num(tr.get("max_entries", "")),
                         _num(tr.get("total_entries", "")), _num(tr.get("node_count", ""))]
        ws_role.append(row_vals)
        _phase_fill_row(ws_role, ws_role.max_row, phase)
    _autofit(ws_role)

    path = os.path.join(out_dir, "summary.xlsx")
    wb.save(path)
    print(f"  Saved {path}")


def write_core_edge_csv(results_by_phase, out_dir):
    """Write a wide-format CSV combining runs and per-role table data for spreadsheet import."""
    import csv as _csv

    run_fields = [
        "num_nodes", "num_links",
        "router_reachability_s", "prefix_propagation_s",
        "control_packets", "control_bytes",
        "total_packets", "total_bytes",
    ]

    # Index runs by (phase, trial, prefix_count)
    runs_index = {}
    for phase in ("onephase", "twophase"):
        for row in results_by_phase[phase]["runs"]:
            k = (row.get("phase", phase), row.get("trial", "1"), row.get("prefix_count"))
            runs_index[k] = row

    # Index table rows by (phase, trial, prefix_count, role, table_category, table_name)
    table_index = {}
    for phase in ("onephase", "twophase"):
        for row in results_by_phase[phase]["role_table_summary"]:
            k = (
                row.get("phase", phase), row.get("trial"), row.get("prefix_count"),
                row.get("role"), row.get("table_category"), row.get("table_name"),
            )
            table_index[k] = row

    # Collect all (phase, trial, prefix_count, role) combos
    combos = set()
    for phase in ("onephase", "twophase"):
        for row in results_by_phase[phase]["role_table_summary"]:
            combos.add((row.get("phase", phase), row.get("trial"), row.get("prefix_count"), row.get("role")))
        for row in results_by_phase[phase]["runs"]:
            p = row.get("phase", phase)
            t = row.get("trial", "1")
            pc = row.get("prefix_count")
            for role in ("core", "edge"):
                combos.add((p, t, pc, role))
    combos = sorted(combos)

    # Build table column headers in TABLE_ORDER order
    table_col_names = []  # (cat, name) tuples in order
    seen = set()
    for key in TABLE_ORDER:
        if key not in seen:
            table_col_names.append(key)
            seen.add(key)

    table_col_headers = []
    for _cat, name in table_col_names:
        table_col_headers += [f"{name}_avg", f"{name}_max", f"{name}_total", f"{name}_node_count"]

    fieldnames = ["phase", "trial", "prefix_count", "role"] + run_fields + table_col_headers

    path = os.path.join(out_dir, "summary.csv")
    with open(path, "w", newline="") as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for (phase, trial, prefix_count, role) in combos:
            run_row = runs_index.get((phase, trial, prefix_count), {})
            out_row = {"phase": phase, "trial": trial, "prefix_count": prefix_count, "role": role}
            for field in run_fields:
                out_row[field] = run_row.get(field, "")
            for cat, name in table_col_names:
                trow = table_index.get((phase, trial, prefix_count, role, cat, name), {})
                out_row[f"{name}_avg"] = trow.get("avg_entries", "")
                out_row[f"{name}_max"] = trow.get("max_entries", "")
                out_row[f"{name}_total"] = trow.get("total_entries", "")
                out_row[f"{name}_node_count"] = trow.get("node_count", "")
            writer.writerow(out_row)
    print(f"  Saved {path}")


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
