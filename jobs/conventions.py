import os
import sys
from pathlib import Path

from .spec import load_job_spec


def workspace_root():
    return Path(__file__).resolve().parent.parent


def experiments_root(root=None):
    return Path(root or workspace_root()) / "experiments"


def queue_stem(path):
    return Path(path).stem


def selector_from_path(path, root=None):
    queue_path = Path(path).resolve()
    parts = queue_path.relative_to(Path(root or workspace_root()).resolve()).parts
    if len(parts) >= 4 and parts[0] == "experiments" and parts[2] == "queues":
        return f"{parts[1]}/{queue_path.stem}"
    raise ValueError(f"Queue path does not follow experiments/<name>/queues convention: {path}")


def discover_catalog(root=None):
    exp_root = experiments_root(root)
    catalog = []
    if not exp_root.exists():
        return catalog

    for exp_dir in sorted(path for path in exp_root.iterdir() if path.is_dir()):
        queue_dir = exp_dir / "queues"
        scenario_dir = exp_dir / "scenarios"
        scenarios = sorted(path.name for path in scenario_dir.glob("*.json")) if scenario_dir.exists() else []
        queues = []
        if queue_dir.exists():
            for queue_path in sorted(queue_dir.glob("*.json")):
                spec = load_job_spec(queue_path)
                selector = spec.get("selector") or selector_from_path(queue_path, root=root)
                queues.append(
                    {
                        "path": str(queue_path.resolve()),
                        "selector": selector,
                        "name": spec.get("name") or queue_path.stem,
                        "description": spec.get("description") or spec.get("_comment", ""),
                        "topology": spec.get("topology", ""),
                        "mode": spec.get("mode", ""),
                    }
                )
        if queues or scenarios:
            catalog.append(
                {
                    "experiment": exp_dir.name,
                    "path": str(exp_dir.resolve()),
                    "queues": queues,
                    "scenarios": scenarios,
                }
            )
    return catalog


def select_queue_interactively(catalog):
    if not sys.stdin.isatty():
        print("ERROR: no queue specified and stdin is not interactive.", file=sys.stderr)
        sys.exit(1)
    if not catalog:
        print("ERROR: no experiment queues found under experiments/.", file=sys.stderr)
        sys.exit(1)

    print("Experiments:\n")
    for index, entry in enumerate(catalog, start=1):
        print(f"  {index:>2}. {entry['experiment']}")
        if entry["scenarios"]:
            print(f"      scenarios: {', '.join(entry['scenarios'])}")
        for queue in entry["queues"]:
            meta = []
            if queue.get("topology"):
                meta.append(f"topology={queue['topology']}")
            if queue.get("mode"):
                meta.append(f"mode={queue['mode']}")
            suffix = f"  [{', '.join(meta)}]" if meta else ""
            print(f"      - {queue['selector']}{suffix}")

    while True:
        exp_choice = input("\nSelect experiment number (or 'q' to cancel): ").strip()
        if exp_choice.lower() in {"q", "quit", "exit"}:
            sys.exit(1)
        if exp_choice.isdigit():
            exp_index = int(exp_choice)
            if 1 <= exp_index <= len(catalog):
                experiment = catalog[exp_index - 1]
                break
        print("Invalid selection.", file=sys.stderr)

    if not experiment["queues"]:
        print(f"ERROR: experiment '{experiment['experiment']}' has no queues.", file=sys.stderr)
        sys.exit(1)

    print("")
    for index, queue in enumerate(experiment["queues"], start=1):
        print(f"  {index:>2}. {queue['selector']}")
        if queue.get("description"):
            print(f"      {queue['description']}")

    while True:
        queue_choice = input("\nSelect queue number (or 'q' to cancel): ").strip()
        if queue_choice.lower() in {"q", "quit", "exit"}:
            sys.exit(1)
        if queue_choice.isdigit():
            queue_index = int(queue_choice)
            if 1 <= queue_index <= len(experiment["queues"]):
                return experiment["queues"][queue_index - 1]["path"]
        print("Invalid selection.", file=sys.stderr)


def resolve_queue_path(target=None, root=None):
    if target and os.path.exists(target):
        return str(Path(target).resolve())

    catalog = discover_catalog(root)
    if not target:
        return select_queue_interactively(catalog)

    needle = target.strip().rstrip("/")
    if needle.endswith(".json"):
        needle = needle[:-5]

    matches = []
    for experiment in catalog:
        for queue in experiment["queues"]:
            if needle == queue["selector"] or needle == queue["name"]:
                matches.append(queue["path"])

    if not matches:
        print(f"ERROR: unknown queue '{target}'.", file=sys.stderr)
        print("Use './jobs.sh list' to see experiment selectors.", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(f"ERROR: queue selector '{target}' is ambiguous.", file=sys.stderr)
        for path in matches:
            print(f"  - {selector_from_path(path, root=root)}", file=sys.stderr)
        sys.exit(1)
    return matches[0]