import csv
import json
import os


def human_bytes(value, _pos=None):
    if value >= 1e9:
        return f"{value / 1e9:.1f} GB"
    if value >= 1e6:
        return f"{value / 1e6:.1f} MB"
    if value >= 1e3:
        return f"{value / 1e3:.1f} KB"
    return f"{value:.0f} B"


def source_label_from_dir(data_dir):
    base = os.path.basename(os.path.abspath(data_dir))
    if "sim" in base:
        return "Simulation"
    if "emu" in base:
        return "Emulation"
    return "Results"


def load_churn_csv(path):
    with open(path) as handle:
        return list(csv.DictReader(handle))


def load_packet_trace(path):
    times, categories, sizes = [], [], []
    with open(path) as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            times.append(float(row["Time"]))
            categories.append(row["Category"])
            sizes.append(int(row["Bytes"]))
    return times, categories, sizes


def load_svs_suppression_dir(data_dir):
    results = {}
    for name in os.listdir(data_dir):
        if not (name.startswith("svs-suppression-") and name.endswith(".json")):
            continue
        if "two_step" not in name:
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