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
    raise ValueError(f"cannot determine source label (sim/emu) from directory name: {base!r}")


def load_churn_csv(path):
    return _load_csv(path)


def _has_classic_result_layout(data_dir):
    """True if data_dir has the classic {phase}/ subdirectory layout."""
    for phase in ("onephase", "twophase"):
        phase_dir = os.path.join(data_dir, phase)
        if not os.path.isdir(phase_dir):
            return False
        if not os.path.exists(os.path.join(phase_dir, "runs.csv")):
            return False
        if not os.path.exists(os.path.join(phase_dir, "role_table_summary.csv")):
            return False
    return True


def _has_prefix_phase_layout(data_dir):
    """True if data_dir has the prefix-phase layout (e.g., p0/onephase/, p0/twophase/)."""
    if not os.path.isdir(data_dir):
        return False
    # Find p* directories
    prefix_dirs = [d for d in os.listdir(data_dir) if d.startswith("p") and os.path.isdir(os.path.join(data_dir, d))]
    if not prefix_dirs:
        return False
    # Check that at least one prefix dir has both phase subdirs with runs.csv
    for prefix_dir in prefix_dirs[:3]:
        for phase in ("onephase", "twophase"):
            phase_dir = os.path.join(data_dir, prefix_dir, phase)
            if not os.path.isdir(phase_dir):
                return False
            if not os.path.exists(os.path.join(phase_dir, "runs.csv")):
                return False
        return True
    return False


def has_core_edge_result_layout(data_dir):
    return _has_classic_result_layout(data_dir) or _has_prefix_phase_layout(data_dir)


def load_core_edge_results(data_dir):
    if _has_classic_result_layout(data_dir):
        results = {}
        for phase in ("onephase", "twophase"):
            phase_dir = os.path.join(data_dir, phase)
            results[phase] = {
                "runs": _load_csv(os.path.join(phase_dir, "runs.csv")),
                "role_table_summary": _load_csv(os.path.join(phase_dir, "role_table_summary.csv")),
            }
        return results

    if _has_prefix_phase_layout(data_dir):
        # Prefix-phase layout: aggregate from p*/{phase}/ directories
        results = {"onephase": {"runs": [], "role_table_summary": []},
                   "twophase": {"runs": [], "role_table_summary": []}}
        prefix_dirs = sorted([d for d in os.listdir(data_dir)
                            if d.startswith("p") and os.path.isdir(os.path.join(data_dir, d))])
        for prefix_dir in prefix_dirs:
            for phase in ("onephase", "twophase"):
                phase_dir = os.path.join(data_dir, prefix_dir, phase)
                runs_path = os.path.join(phase_dir, "runs.csv")
                if os.path.exists(runs_path):
                    results[phase]["runs"].extend(_load_csv(runs_path))
                role_path = os.path.join(phase_dir, "role_table_summary.csv")
                if os.path.exists(role_path):
                    results[phase]["role_table_summary"].extend(_load_csv(role_path))
        return results

    raise FileNotFoundError(f"result layout not found under {data_dir}")


def detect_role_table_topology(data_dir):
    topologies = set()

    def check_metadata(path):
        if os.path.exists(path):
            with open(path) as handle:
                metadata = json.load(handle)
            return metadata.get("topology")
        return None

    # Classic layout: check {phase}/metadata.json
    if _has_classic_result_layout(data_dir):
        for phase in ("onephase", "twophase"):
            topology = check_metadata(os.path.join(data_dir, phase, "metadata.json"))
            if topology:
                topologies.add(topology)
    # Prefix-phase layout: check p*/{phase}/metadata.json
    elif _has_prefix_phase_layout(data_dir):
        prefix_dirs = sorted([d for d in os.listdir(data_dir)
                            if d.startswith("p") and os.path.isdir(os.path.join(data_dir, d))])
        for prefix_dir in prefix_dirs:
            for phase in ("onephase", "twophase"):
                topology = check_metadata(os.path.join(data_dir, prefix_dir, phase, "metadata.json"))
                if topology:
                    topologies.add(topology)
                    break  # Only need one per prefix
            if topologies:
                break  # Only need one prefix dir

    if len(topologies) > 1:
        raise ValueError(f"conflicting topology metadata under {data_dir}: {sorted(topologies)}")
    if len(topologies) == 1:
        return next(iter(topologies))

    raise ValueError(f"no topology field found in any metadata.json under {data_dir}")


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

    def _scan_dir_for_traces(scan_dir):
        if not os.path.isdir(scan_dir):
            return
        for name in os.listdir(scan_dir):
            match = _CORE_EDGE_LINK_TRACE_RE.fullmatch(name)
            if not match:
                continue
            phase = match.group(1)
            prefix_count = int(match.group(2))
            path = os.path.join(scan_dir, name)
            totals = {field: 0 for field in fields}
            with open(path) as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    for field in fields:
                        totals[field] += int(row.get(field, 0) or 0)
            results[phase].setdefault(prefix_count, []).append(totals)

    # Classic layout: scan {data_dir}/{phase}/
    for phase in results:
        _scan_dir_for_traces(os.path.join(data_dir, phase))

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