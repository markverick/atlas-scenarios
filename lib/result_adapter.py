"""
Result adapter — unified result format for both emulation and simulation.

Both emu and sim scenarios produce raw outputs in different forms:
  - Emulation: direct Python measurements (convergence time, diff check, RSS)
  - Simulation: ndndSIM rate-trace CSVs

This adapter translates both into a common TrialResult that gets written
to the shared CSV format consumed by plot.py.
"""

import csv
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime


FIELDNAMES = [
    "grid_size",
    "num_nodes",
    "num_links",
    "trial",
    "convergence_s",
    "transfer_ok",
    "avg_mem_kb",
    "total_packets",
    "total_bytes",
    "dv_packets",
    "dv_bytes",
    "user_packets",
    "user_bytes",
]


@dataclass
class TrialResult:
    """One row of results in the unified schema."""
    grid_size: int
    num_nodes: int
    num_links: int
    trial: int = 1
    convergence_s: float = -1
    transfer_ok: bool = False
    avg_mem_kb: int = 0
    total_packets: int = 0
    total_bytes: int = 0
    dv_packets: int = 0
    dv_bytes: int = 0
    user_packets: int = 0
    user_bytes: int = 0


class ResultWriter:
    """Context manager for writing TrialResult rows to CSV."""

    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._file = open(path, "w", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()

    def write(self, result: TrialResult):
        self._writer.writerow(asdict(result))
        self._file.flush()

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── Sim adapter ─────────────────────────────────────────────────────

def parse_sim_convergence(rate_trace_path, producer_start=0.5):
    """Extract DV convergence time from an ndndSIM rate-trace CSV.

    Convergence is defined as the time of the first DataReceived event
    minus the producer start time.

    Returns convergence time in seconds (float), or -1 on failure.
    """
    if not os.path.isfile(rate_trace_path):
        return -1
    first_data_time = None
    with open(rate_trace_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Type"] == "DataReceived" and int(row["Packets"]) > 0:
                t = float(row["Time"])
                if first_data_time is None or t < first_data_time:
                    first_data_time = t
    if first_data_time is None:
        return -1
    return round(first_data_time - producer_start, 4)


def parse_conv_trace(conv_trace_path):
    """Read convergence time from a one-line file written by the C++ scenario.

    Returns convergence time in seconds (float), or -1 on failure.
    """
    if not conv_trace_path or not os.path.isfile(conv_trace_path):
        return -1
    with open(conv_trace_path) as f:
        val = f.read().strip()
    try:
        t = float(val)
        return round(t, 4) if t >= 0 else -1
    except ValueError:
        return -1


def _parse_log_time_to_epoch(ts):
    """Parse RFC3339-ish timestamp from NDNd logs to Unix epoch seconds."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_dv_update_span_log(log_path, prefix="/ndn/test"):
    """Parse one NDNd DV log and return (first_global_ts, last_add_ts).

    first_global_ts is the first timestamp where the prefix is globally announced.
    last_add_ts is the last timestamp where the prefix is added as a remote prefix.
    """
    if not log_path or not os.path.isfile(log_path):
        return None, None

    first_global = None
    last_add = None
    prefix_token = f"name={prefix}"

    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "time=" not in line or prefix_token not in line:
                continue
            m = re.search(r"time=([^\s]+)", line)
            if not m:
                continue
            ts = _parse_log_time_to_epoch(m.group(1))
            if ts is None:
                continue

            if 'msg="Global announce"' in line:
                if first_global is None or ts < first_global:
                    first_global = ts
            elif 'msg="Add remote prefix"' in line:
                if last_add is None or ts > last_add:
                    last_add = ts

    return first_global, last_add


def parse_dv_update_span_logs(log_paths, prefix="/ndn/test"):
    """Return convergence as last update received - first update originated.

    Definition:
      convergence_s = max(AddRemotePrefix[name=prefix].time)
                      - min(GlobalAnnounce[name=prefix].time)

    Returns rounded seconds (4 d.p.), or -1 if either endpoint is missing.
    """
    first_global = None
    last_add = None

    for path in log_paths or []:
        fg, la = parse_dv_update_span_log(path, prefix=prefix)
        if fg is not None and (first_global is None or fg < first_global):
            first_global = fg
        if la is not None and (last_add is None or la > last_add):
            last_add = la

    if first_global is None or last_add is None or last_add < first_global:
        return -1
    return round(last_add - first_global, 4)


def parse_router_reachable_logs(log_paths, num_nodes):
    """Compute routing convergence from DV 'Router is now reachable' events.

    Convergence = (timestamp of event completing all FIBs) − (first event).
    Each log file corresponds to one node.  Convergence is achieved when
    every node has learned routes to all other (num_nodes − 1) routers.

    Returns convergence in seconds (float, 4 d.p.) or −1 on failure.
    """
    if not log_paths or num_nodes < 2:
        return -1

    target = num_nodes - 1
    first_event_ts = None
    last_completion_ts = None
    all_complete = True

    for path in log_paths or []:
        if not path or not os.path.isfile(path):
            all_complete = False
            continue
        seen = set()
        node_complete_ts = None
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if 'msg="Router is now reachable"' not in line:
                    continue
                m = re.search(r"time=([^\s]+)", line)
                if not m:
                    continue
                ts = _parse_log_time_to_epoch(m.group(1))
                if ts is None:
                    continue
                if first_event_ts is None or ts < first_event_ts:
                    first_event_ts = ts
                nm = re.search(r"\bname=([^\s]+)", line)
                if nm:
                    seen.add(nm.group(1))
                if len(seen) >= target and node_complete_ts is None:
                    node_complete_ts = ts
        if node_complete_ts is None:
            all_complete = False
        elif last_completion_ts is None or node_complete_ts > last_completion_ts:
            last_completion_ts = node_complete_ts

    if not all_complete or first_event_ts is None or last_completion_ts is None:
        return -1
    return round(last_completion_ts - first_event_ts, 4)


def parse_link_trace(link_trace_path):
    """Parse a link-tracer CSV and return aggregate traffic counters.

    Returns dict with keys: total_packets, total_bytes,
    dv_packets, dv_bytes, user_packets, user_bytes.
    """
    result = dict(total_packets=0, total_bytes=0,
                  dv_packets=0, dv_bytes=0,
                  user_packets=0, user_bytes=0)
    if not link_trace_path or not os.path.isfile(link_trace_path):
        return result

    with open(link_trace_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            for cat in ("DvAdvert", "PrefixSync", "Mgmt",
                        "UserInterest", "UserData", "Other"):
                pkts = int(row.get(f"{cat}_Pkts", 0))
                bts = int(row.get(f"{cat}_Bytes", 0))
                result["total_packets"] += pkts
                result["total_bytes"] += bts
                if cat in ("DvAdvert", "PrefixSync", "Mgmt"):
                    result["dv_packets"] += pkts
                    result["dv_bytes"] += bts
                elif cat in ("UserInterest", "UserData"):
                    result["user_packets"] += pkts
                    result["user_bytes"] += bts
    return result


def sim_trial_result(grid_size, num_nodes, num_links, rate_trace_path,
                     trial=1, producer_start=0.5, conv_trace_path=None,
                     link_trace_path=None, dv_log_paths=None,
                     prefix="/ndn/test"):
    """Build a TrialResult from ndndSIM outputs.

    Convergence is read strictly from convTrace generated by ns-3 scenario
    code (simulated time). No fallback is used.
    """
    conv = parse_conv_trace(conv_trace_path)
    traffic = parse_link_trace(link_trace_path)
    return TrialResult(
        grid_size=grid_size,
        num_nodes=num_nodes,
        num_links=num_links,
        trial=trial,
        convergence_s=conv,
        transfer_ok=conv >= 0,
        avg_mem_kb=0,
        **traffic,
    )
