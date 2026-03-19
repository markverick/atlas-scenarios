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
from dataclasses import asdict, dataclass


FIELDNAMES = [
    "grid_size",
    "num_nodes",
    "num_links",
    "trial",
    "convergence_s",
    "transfer_ok",
    "avg_mem_kb",
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
    return round(first_data_time - producer_start, 2)


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
        return round(t, 2) if t >= 0 else -1
    except ValueError:
        return -1


def sim_trial_result(grid_size, num_nodes, num_links, rate_trace_path,
                     trial=1, producer_start=0.5, conv_trace_path=None):
    """Build a TrialResult from ndndSIM outputs.

    If conv_trace_path is provided, uses the direct RIB-based convergence
    measurement. Otherwise falls back to rate-trace first-Data heuristic.
    """
    if conv_trace_path:
        conv = parse_conv_trace(conv_trace_path)
    else:
        conv = parse_sim_convergence(rate_trace_path, producer_start)
    return TrialResult(
        grid_size=grid_size,
        num_nodes=num_nodes,
        num_links=num_links,
        trial=trial,
        convergence_s=conv,
        transfer_ok=conv >= 0,
        avg_mem_kb=0,
    )


# ── Emu adapter ─────────────────────────────────────────────────────

def emu_trial_result(grid_size, num_nodes, num_links, convergence_s,
                     transfer_ok, avg_mem_kb, trial=1):
    """Build a TrialResult from emulation measurements."""
    return TrialResult(
        grid_size=grid_size,
        num_nodes=num_nodes,
        num_links=num_links,
        trial=trial,
        convergence_s=convergence_s,
        transfer_ok=transfer_ok,
        avg_mem_kb=avg_mem_kb,
    )
