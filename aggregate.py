#!/usr/bin/env python3
"""Render per-trial packet and byte summary tables from scalability runs."""

import argparse
import csv
import os
from typing import Dict, Iterable, List, Tuple


CATEGORIES = ["DvAdvert", "PrefixSync", "Mgmt", "UserInterest", "UserData", "Other"]
COLUMNS = [
    "trial",
    "convergence_s",
    "DvAdvert_pkts",
    "DvAdvert_bytes",
    "PrefixSync_pkts",
    "PrefixSync_bytes",
    "Mgmt_pkts",
    "Mgmt_bytes",
    "UserInterest_pkts",
    "UserInterest_bytes",
    "UserData_pkts",
    "UserData_bytes",
    "Other_pkts",
    "Other_bytes",
    "total_pkts",
    "total_bytes",
]


def parse_input_arg(value: str) -> Tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"invalid --input '{value}'; expected LABEL=DIR"
        )

    label, directory = value.split("=", 1)
    label = label.strip()
    directory = directory.strip()
    if not label or not directory:
        raise argparse.ArgumentTypeError(
            f"invalid --input '{value}'; expected LABEL=DIR"
        )
    return label, directory


def load_scalability_rows(directory: str, grid_size: int) -> List[Dict[str, str]]:
    scalability_path = os.path.join(directory, "scalability.csv")
    if not os.path.exists(scalability_path):
        raise FileNotFoundError(f"missing scalability.csv in {directory}")

    rows: List[Dict[str, str]] = []
    with open(scalability_path, newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if int(row["grid_size"]) == grid_size:
                rows.append(row)

    rows.sort(key=lambda item: int(item["trial"]))
    if not rows:
        raise ValueError(f"no grid_size={grid_size} rows found in {scalability_path}")
    return rows


def summarize_link_trace(trace_path: str) -> Dict[str, int]:
    if not os.path.exists(trace_path):
        raise FileNotFoundError(f"missing link trace {trace_path}")

    sums = {f"{cat}_pkts": 0 for cat in CATEGORIES}
    sums.update({f"{cat}_bytes": 0 for cat in CATEGORIES})

    with open(trace_path, newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for cat in CATEGORIES:
                sums[f"{cat}_pkts"] += int(row[f"{cat}_Pkts"])
                sums[f"{cat}_bytes"] += int(row[f"{cat}_Bytes"])

    sums["total_pkts"] = sum(sums[f"{cat}_pkts"] for cat in CATEGORIES)
    sums["total_bytes"] = sum(sums[f"{cat}_bytes"] for cat in CATEGORIES)
    return sums


def aggregate_dir(directory: str, *, grid_size: int) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    for row in load_scalability_rows(directory, grid_size):
        trial = int(row["trial"])
        tag = f"{grid_size}x{grid_size}-t{trial}"
        trace_path = os.path.join(directory, f"link-trace-{tag}.csv")
        breakdown = summarize_link_trace(trace_path)
        result: Dict[str, object] = {
            "trial": trial,
            "convergence_s": row["convergence_s"],
        }
        result.update(breakdown)
        results.append(result)
    return results


def render_markdown_table(label: str, results: Iterable[Dict[str, object]]) -> str:
    lines = [f"## {label}", ""]
    lines.append("| " + " | ".join(COLUMNS) + " |")
    lines.append("| " + " | ".join(["---"] * len(COLUMNS)) + " |")
    for row in results:
        lines.append("| " + " | ".join(str(row[column]) for column in COLUMNS) + " |")
    return "\n".join(lines)


def render_report(inputs: Iterable[Tuple[str, str]], *, grid_size: int) -> str:
    sections = []
    for label, directory in inputs:
        sections.append(
            render_markdown_table(label, aggregate_dir(directory, grid_size=grid_size))
        )
    return "\n\n".join(sections) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render per-trial packet and byte tables from scalability output directories"
    )
    parser.add_argument(
        "--input",
        action="append",
        dest="inputs",
        metavar="LABEL=DIR",
        type=parse_input_arg,
        required=True,
        help="Input label and output directory, e.g. twophase=results/twophase",
    )
    parser.add_argument(
        "--grid-size",
        type=int,
        default=3,
        help="Grid size to report (default: 3)",
    )
    parser.add_argument(
        "--out",
        help="Optional path to write the rendered Markdown report",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = render_report(args.inputs, grid_size=args.grid_size)
    print(report, end="")
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
