#!/usr/bin/env python3
"""
Job queue runner for atlas-scenarios experiments.

Reads a YAML/JSON job file and executes each job sequentially,
tracking status (pending/running/done/failed) so you can resume
after a failure without re-running completed jobs.

Usage:
    python3 jobs.py run   jobs.yaml          # run all pending jobs
    python3 jobs.py run   jobs.yaml --dry    # preview without executing
    python3 jobs.py status jobs.yaml         # show job status
    python3 jobs.py reset  jobs.yaml         # mark all jobs as pending
    python3 jobs.py reset  jobs.yaml 3       # mark job #3 as pending

Job file format (YAML):

    jobs:
      - name: sim churn 3x3
        cmd:  ./run.sh sim churn.py --config scenarios/churn_3x3.json
      - name: emu churn 3x3
        cmd:  sudo ./run.sh emu churn.py --config scenarios/churn_3x3.json
      - name: plot 3x3
        cmd:  python3 plot_churn.py --sim results/sim_churn/churn.csv ...

Or JSON (same structure with "jobs" array).

State is persisted in <jobfile>.state.json alongside the job file.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

STATE_PENDING  = "pending"
STATE_RUNNING  = "running"
STATE_DONE     = "done"
STATE_FAILED   = "failed"


def _state_path(job_path):
    return job_path + ".state.json"


def _load_jobs(path):
    """Load job definitions from JSON or YAML."""
    with open(path) as f:
        text = f.read()

    # Try JSON first
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to YAML
        try:
            import yaml
            data = yaml.safe_load(text)
        except ImportError:
            print("ERROR: job file is not valid JSON and PyYAML is not installed.\n"
                  "       pip install pyyaml   OR   use JSON format.", file=sys.stderr)
            sys.exit(1)

    if not isinstance(data, dict) or "jobs" not in data:
        print("ERROR: job file must have a top-level 'jobs' array.", file=sys.stderr)
        sys.exit(1)

    jobs = data["jobs"]
    for i, j in enumerate(jobs):
        j.setdefault("id", i + 1)
        if "cmd" not in j:
            print(f"ERROR: job #{j['id']} missing 'cmd' field.", file=sys.stderr)
            sys.exit(1)
        j.setdefault("name", f"job-{j['id']}")
    return jobs


def _load_state(path):
    sp = _state_path(path)
    if os.path.exists(sp):
        with open(sp) as f:
            return json.load(f)
    return {}


def _save_state(path, state):
    sp = _state_path(path)
    with open(sp, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def _job_key(job):
    return str(job["id"])


def cmd_status(job_path):
    jobs = _load_jobs(job_path)
    state = _load_state(job_path)

    counts = {STATE_PENDING: 0, STATE_RUNNING: 0, STATE_DONE: 0, STATE_FAILED: 0}
    for j in jobs:
        s = state.get(_job_key(j), {})
        st = s.get("status", STATE_PENDING)
        counts[st] += 1
        elapsed = ""
        if s.get("elapsed_s"):
            elapsed = f"  ({s['elapsed_s']:.0f}s)"
        mark = {"pending": " ", "running": "~", "done": "✓", "failed": "✗"}[st]
        print(f"  [{mark}] #{j['id']:>2}  {st:<8}  {j['name']}{elapsed}")

    total = len(jobs)
    print(f"\n  {counts[STATE_DONE]}/{total} done, "
          f"{counts[STATE_FAILED]} failed, "
          f"{counts[STATE_PENDING]} pending")


def cmd_reset(job_path, job_id=None):
    state = _load_state(job_path)
    if job_id is not None:
        key = str(job_id)
        if key in state:
            state[key]["status"] = STATE_PENDING
            state[key].pop("elapsed_s", None)
            state[key].pop("error", None)
            print(f"  Reset job #{job_id} to pending.")
        else:
            state[key] = {"status": STATE_PENDING}
            print(f"  Reset job #{job_id} to pending (no prior state).")
    else:
        for key in state:
            state[key]["status"] = STATE_PENDING
            state[key].pop("elapsed_s", None)
            state[key].pop("error", None)
        print(f"  Reset all {len(state)} jobs to pending.")
    _save_state(job_path, state)


def cmd_run(job_path, dry=False):
    jobs = _load_jobs(job_path)
    state = _load_state(job_path)
    total = len(jobs)
    done = 0
    failed = 0

    for j in jobs:
        key = _job_key(j)
        s = state.get(key, {})
        st = s.get("status", STATE_PENDING)

        if st == STATE_DONE:
            done += 1
            continue

        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"\n{'='*60}")
        print(f"  [{now_str}] Job #{j['id']}/{total}: {j['name']}")
        print(f"  cmd: {j['cmd']}")
        print(f"{'='*60}")

        if dry:
            print("  (dry run — skipped)")
            continue

        state[key] = {"status": STATE_RUNNING,
                      "started": datetime.now(timezone.utc).isoformat()}
        _save_state(job_path, state)

        t0 = time.monotonic()
        try:
            subprocess.run(j["cmd"], shell=True, check=True)
            elapsed = time.monotonic() - t0
            state[key] = {
                "status": STATE_DONE,
                "elapsed_s": round(elapsed, 1),
                "finished": datetime.now(timezone.utc).isoformat(),
            }
            done += 1
            print(f"\n  ✓ Job #{j['id']} done ({elapsed:.0f}s)")
        except subprocess.CalledProcessError as e:
            elapsed = time.monotonic() - t0
            state[key] = {
                "status": STATE_FAILED,
                "elapsed_s": round(elapsed, 1),
                "error": f"exit code {e.returncode}",
                "finished": datetime.now(timezone.utc).isoformat(),
            }
            failed += 1
            print(f"\n  ✗ Job #{j['id']} FAILED (exit {e.returncode}, {elapsed:.0f}s)")
            print(f"    Resume later:  python3 jobs.py run {job_path}")
            # Continue to next job instead of aborting entire queue
            continue
        finally:
            _save_state(job_path, state)

    print(f"\n{'='*60}")
    print(f"  Summary: {done}/{total} done, {failed} failed, "
          f"{total - done - failed} skipped/pending")
    print(f"{'='*60}")

    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(
        description="Job queue runner for atlas-scenarios experiments")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Run all pending jobs")
    p_run.add_argument("jobfile", help="Path to job file (JSON or YAML)")
    p_run.add_argument("--dry", action="store_true",
                       help="Print commands without executing")

    p_status = sub.add_parser("status", help="Show job status")
    p_status.add_argument("jobfile")

    p_reset = sub.add_parser("reset", help="Reset job(s) to pending")
    p_reset.add_argument("jobfile")
    p_reset.add_argument("job_id", nargs="?", type=int, default=None,
                         help="Reset specific job # (default: all)")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        sys.exit(cmd_run(args.jobfile, dry=args.dry))
    elif args.command == "status":
        cmd_status(args.jobfile)
    elif args.command == "reset":
        cmd_reset(args.jobfile, args.job_id)


if __name__ == "__main__":
    main()
