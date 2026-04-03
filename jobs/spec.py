import itertools
import json
import os
import sys
from datetime import datetime, timezone


def load_job_spec(path):
    with open(path) as handle:
        text = handle.read()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError:
            print(
                "ERROR: job file is not valid JSON and PyYAML is not installed.\n"
                "       pip install pyyaml   OR   use JSON format.",
                file=sys.stderr,
            )
            sys.exit(1)
        data = yaml.safe_load(text)

    if not isinstance(data, dict) or "jobs" not in data:
        print("ERROR: job file must have a top-level 'jobs' array.", file=sys.stderr)
        sys.exit(1)
    template = data.get("run_root_template")
    if template and "{timestamp}" not in template:
        print(
            "ERROR: run_root_template must include '{timestamp}' so each run is saved separately.",
            file=sys.stderr,
        )
        sys.exit(1)
    return data


def format_template(value, context, *, field_name="value"):
    if not isinstance(value, str):
        return value
    try:
        return value.format(**context)
    except KeyError as exc:
        missing = exc.args[0]
        print(
            f"ERROR: missing template variable '{missing}' while rendering {field_name}.",
            file=sys.stderr,
        )
        sys.exit(1)


def expand_matrix(job_template, base_context=None):
    base_context = dict(base_context or {})
    matrix = job_template.get("matrix") or {}
    keys = sorted(matrix.keys())
    combos = list(itertools.product(*(matrix[key] for key in keys))) if keys else [()]

    expanded = []
    for combo in combos:
        context = {**base_context, **dict(zip(keys, combo))}
        item = {}
        for field, value in job_template.items():
            if field == "matrix":
                continue
            item[field] = format_template(value, context, field_name=field)
        expanded.append(item)
    return expanded


def load_jobs(path, context=None):
    data = load_job_spec(path)
    jobs = []
    for raw in data["jobs"]:
        jobs.extend(expand_matrix(raw, context))

    for index, job in enumerate(jobs, start=1):
        job["id"] = index
        if "cmd" not in job:
            print(f"ERROR: job #{job['id']} missing 'cmd' field.", file=sys.stderr)
            sys.exit(1)
        job.setdefault("name", f"job-{index}")
    return jobs


def build_run_context(job_path, spec, state, *, selector, stem):
    meta = state.get("__meta__", {})
    cached = meta.get("run_context")
    current_template = spec.get("run_root_template")
    if cached and meta.get("run_root_template") == current_template:
        return cached

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    context = {
        "selector": selector,
        "job_stem": stem,
        "queue_name": spec.get("name") or stem,
        "timestamp": timestamp,
    }
    for key in ("experiment", "topology", "mode"):
        if key in spec:
            context[key] = spec[key]

    variables = spec.get("variables", {})
    if isinstance(variables, dict):
        for key, value in variables.items():
            context[key] = format_template(value, context, field_name=f"variables.{key}")

    template = spec.get("run_root_template")
    if template:
        context["run_root"] = format_template(
            template,
            context,
            field_name="run_root_template",
        )

    state["__meta__"] = {
        **meta,
        "selector": selector,
        "run_root_template": current_template,
        "run_context": context,
    }
    return context