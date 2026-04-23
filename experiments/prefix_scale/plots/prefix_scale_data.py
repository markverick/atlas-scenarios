import csv
import json
import os
import re


def human_bytes(value, _pos=None):
    if value >= 1e9:
        return f"{value / 1e9:.1f} GB"
    if value >= 1e6:
        return f"{value / 1e6:.1f} MB"
    if value >= 1e3:
        return f"{value / 1e3:.1f} KB"
    return f"{value:.0f} B"


def _load_csv(path):
    with open(path) as handle:
        return list(csv.DictReader(handle))


def source_label_from_dir(data_dir):
    base = os.path.basename(os.path.abspath(data_dir))
    if "sim" in base:
        return "Simulation"
    if "emu" in base:
        return "Emulation"
    return "Results"


def load_churn_csv(path):
    return _load_csv(path)


def has_core_edge_result_layout(data_dir):
    for phase in ("onephase", "twophase"):
        phase_dir = os.path.join(data_dir, phase)
        if not os.path.isdir(phase_dir):
            return False
        if not os.path.exists(os.path.join(phase_dir, "runs.csv")):
            return False
        if not os.path.exists(os.path.join(phase_dir, "role_table_summary.csv")):
            return False
    return True


def load_core_edge_results(data_dir):
    if not has_core_edge_result_layout(data_dir):
        raise FileNotFoundError(f"core/edge result layout not found under {data_dir}")

    results = {}
    for phase in ("onephase", "twophase"):
        phase_dir = os.path.join(data_dir, phase)
        results[phase] = {
            "runs": _load_csv(os.path.join(phase_dir, "runs.csv")),
            "role_table_summary": _load_csv(os.path.join(phase_dir, "role_table_summary.csv")),
        }
    return results


def detect_role_table_topology(data_dir):
    topologies = set()
    for phase in ("onephase", "twophase"):
        metadata_path = os.path.join(data_dir, phase, "metadata.json")
        if not os.path.exists(metadata_path):
            continue
        with open(metadata_path) as handle:
            metadata = json.load(handle)
        topology = metadata.get("topology")
        if topology:
            topologies.add(topology)

    if len(topologies) > 1:
        raise ValueError(f"conflicting topology metadata under {data_dir}: {sorted(topologies)}")
    if len(topologies) == 1:
        return next(iter(topologies))

    base = os.path.basename(os.path.abspath(data_dir))
    if "rocketfuel_2914" in base:
        return "rocketfuel_2914"
    if "rocketfuel_4755" in base:
        return "rocketfuel_4755"
    if "core_edge" in base:
        return "core_edge"

    runs_path = os.path.join(data_dir, "onephase", "runs.csv")
    if os.path.exists(runs_path):
        rows = _load_csv(runs_path)
        if rows:
            num_nodes = int(rows[0].get("num_nodes", 0) or 0)
            num_links = int(rows[0].get("num_links", 0) or 0)
            if (num_nodes, num_links) == (10, 12):
                return "core_edge"
            if num_nodes >= 900:
                return "rocketfuel_2914"
            if (num_nodes, num_links) == (11, 12):
                return "rocketfuel_4755"

    raise ValueError(f"unable to detect prefix-scale topology for {data_dir}")


_CORE_EDGE_LINK_TRACE_RE = re.compile(r"link-trace-(onephase|twophase)-p(\d+)-t(\d+)\.csv$")


def load_core_edge_link_trace_summaries(data_dir):
    fields = [
        "DvAdvert_Pkts",
        "DvAdvert_Bytes",
        "PrefixSync_Pkts",
        "PrefixSync_Bytes",
        "Mgmt_Pkts",
        "Mgmt_Bytes",
        "UserInterest_Pkts",
        "UserInterest_Bytes",
        "UserData_Pkts",
        "UserData_Bytes",
        "Other_Pkts",
        "Other_Bytes",
    ]
    results = {"onephase": {}, "twophase": {}}

    for phase in results:
        phase_dir = os.path.join(data_dir, phase)
        if not os.path.isdir(phase_dir):
            continue
        for name in os.listdir(phase_dir):
            match = _CORE_EDGE_LINK_TRACE_RE.fullmatch(name)
            if not match:
                continue
            prefix_count = int(match.group(2))
            path = os.path.join(phase_dir, name)
            totals = {field: 0 for field in fields}
            with open(path) as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    for field in fields:
                        totals[field] += int(row.get(field, 0) or 0)
            results[phase].setdefault(prefix_count, []).append(totals)
    return results


def load_packet_trace(path):
    times, categories, sizes = [], [], []
    with open(path) as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            times.append(float(row["Time"]))
            categories.append(row["Category"])
            sizes.append(int(row["Bytes"]))
    return times, categories, sizes


def load_event_log(path):
    rows = []
    with open(path) as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                when = float(row["Time"])
            except (KeyError, ValueError):
                continue
            rows.append({
                "time": when,
                "event": row.get("Event", ""),
                "details": row.get("Details", ""),
            })
    return rows


def load_svs_suppression_dir(data_dir):
    results = {}
    for name in os.listdir(data_dir):
        if not (name.startswith("svs-suppression-") and name.endswith(".json")):
            continue
        if "one_phase" not in name:
            continue
        marker = "-p"
        if marker not in name:
            continue
        try:
            prefix_count = int(name.split(marker, 1)[1].split("-", 1)[0])
        except ValueError:
            continue
        path = os.path.join(data_dir, name)
        with open(path) as handle:
            results[prefix_count] = json.load(handle)
    return results


def bin_io(times, sizes, bin_width=1.0):
    if not times:
        return [], []
    minimum = min(times)
    if minimum < 0:
        times = [point - minimum for point in times]
    maximum = max(times)
    num_bins = int(maximum / bin_width) + 1
    bins = [0.0] * num_bins
    for point, size in zip(times, sizes):
        index = min(int(point / bin_width), num_bins - 1)
        bins[index] += size
    edges = [index * bin_width for index in range(num_bins)]
    return edges, bins