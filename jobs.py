#!/usr/bin/env python3
"""
Job queue runner for atlas-scenarios experiments.

Each job queue runs inside a named screen session so it survives
disconnects.  State is persisted in <jobfile>.state.json; a log of
all output is written to <jobfile>.log.

Commands:
    start   <jobfile>          Launch queue in a detached screen
    attach  <jobfile>          Reattach to the screen
    stop    <jobfile>          Kill the screen session
    log     <jobfile> [-f]     Tail the output log
    status  <jobfile>          Show job status (no screen needed)
    run     <jobfile> [--dry]  Run directly (no screen; used by start)
    reset   <jobfile> [ID]     Reset job(s) to pending

Examples:
    sudo python3 jobs.py start  jobs_churn_grids.json
    python3 jobs.py attach jobs_churn_grids.json   # no sudo needed
    python3 jobs.py status jobs_churn_grids.json
    python3 jobs.py log    jobs_churn_grids.json -f
    python3 jobs.py stop   jobs_churn_grids.json   # no sudo needed
    python3 jobs.py reset  jobs_churn_grids.json 3
"""

import argparse
import atexit
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

STATE_PENDING  = "pending"
STATE_RUNNING  = "running"
STATE_DONE     = "done"
STATE_FAILED   = "failed"

RUNNER_HOST = socket.gethostname()

# --------------- paths ---------------

def _state_path(job_path):
    return job_path + ".state.json"


def _log_path(job_path):
    return job_path + ".log"


def _screen_name(job_path):
    """Derive a screen session name from the job file stem."""
    return os.path.splitext(os.path.basename(job_path))[0]


def _screen_exists(name):
    """Return True if a screen session with *name* is alive."""
    r = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
    return f".{name}\t" in r.stdout


import itertools


def _expand_matrix(job_template):
    """Expand a job with a ``matrix`` dict into concrete jobs.

    Example matrix::

        {"mode": ["two_step", "one_step"], "prefixes": [1, 5, 10]}

    Produces the Cartesian product (2 × 3 = 6 jobs).  ``{key}``
    placeholders in *name* and *cmd* are replaced with each value.
    """
    matrix = job_template.get("matrix")
    if not matrix:
        return [job_template]

    keys = sorted(matrix.keys())
    combos = list(itertools.product(*(matrix[k] for k in keys)))

    expanded = []
    for combo in combos:
        subs = dict(zip(keys, combo))
        j = {}
        for field, val in job_template.items():
            if field == "matrix":
                continue
            if isinstance(val, str):
                j[field] = val.format(**subs)
            else:
                j[field] = val
        expanded.append(j)
    return expanded


def _load_jobs(path):
    """Load job definitions from JSON or YAML.

    Jobs with a ``matrix`` key are expanded into one job per combination
    (Cartesian product).  ``{key}`` placeholders in *name* and *cmd* are
    substituted with each value.
    """
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

    jobs = []
    for raw in data["jobs"]:
        jobs.extend(_expand_matrix(raw))
    for i, j in enumerate(jobs):
        j["id"] = i + 1
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


def _clear_runtime_fields(entry):
    for field in (
        "elapsed_s",
        "error",
        "started",
        "finished",
        "runner_pid",
        "runner_host",
        "runner_mode",
        "interrupted",
    ):
        entry.pop(field, None)


def _pid_is_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cleanup_stale_running(job_path, jobs, state, *, keep_pid=None):
    stale = []

    for job in jobs:
        key = _job_key(job)
        entry = state.get(key)
        if not entry or entry.get("status") != STATE_RUNNING:
            continue

        pid = entry.get("runner_pid")
        host = entry.get("runner_host")
        if host == RUNNER_HOST and pid == keep_pid:
            continue
        if host == RUNNER_HOST and _pid_is_alive(pid):
            continue

        entry["status"] = STATE_FAILED
        entry["error"] = "runner disappeared before completion"
        entry["interrupted"] = True
        entry["finished"] = datetime.now(timezone.utc).isoformat()
        entry.pop("runner_pid", None)
        entry.pop("runner_host", None)
        entry.pop("runner_mode", None)
        stale.append(job)

    if stale:
        _save_state(job_path, state)

    return stale


def _report_stale_running(job_path, stale_jobs):
    if not stale_jobs:
        return
    print("ERROR: stale running job state detected and cleaned up:", file=sys.stderr)
    for job in stale_jobs:
        print(f"  - job #{job['id']}: {job['name']}", file=sys.stderr)
    print(
        f"Queue execution was interrupted earlier. Review with 'python3 jobs.py status {job_path}' "
        f"and reset intentionally before rerunning.",
        file=sys.stderr,
    )


def cmd_status(job_path):
    jobs = _load_jobs(job_path)
    state = _load_state(job_path)
    stale = _cleanup_stale_running(job_path, jobs, state)
    if stale:
        print("WARNING: cleaned up stale running state:")
        for job in stale:
            print(f"  - job #{job['id']}: {job['name']}")
        print("  Review failure details, then reset explicitly before rerunning.\n")
        state = _load_state(job_path)

    counts = {STATE_PENDING: 0, STATE_RUNNING: 0, STATE_DONE: 0, STATE_FAILED: 0}
    for j in jobs:
        s = state.get(_job_key(j), {})
        st = s.get("status", STATE_PENDING)
        counts[st] += 1
        elapsed = ""
        if s.get("elapsed_s"):
            elapsed = f"  ({s['elapsed_s']:.0f}s)"
        mark = {"pending": " ", "running": "~", "done": "+", "failed": "X"}[st]
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
            _clear_runtime_fields(state[key])
            print(f"  Reset job #{job_id} to pending.")
        else:
            state[key] = {"status": STATE_PENDING}
            print(f"  Reset job #{job_id} to pending (no prior state).")
    else:
        for key in state:
            state[key]["status"] = STATE_PENDING
            _clear_runtime_fields(state[key])
        print(f"  Reset all {len(state)} jobs to pending.")
    _save_state(job_path, state)


def cmd_run(job_path, dry=False):
    jobs = _load_jobs(job_path)
    state = _load_state(job_path)
    stale = _cleanup_stale_running(job_path, jobs, state, keep_pid=os.getpid())
    if stale:
        _report_stale_running(job_path, stale)
        return 1
    state = _load_state(job_path)
    total = len(jobs)
    done = 0
    failed = 0
    is_root = os.geteuid() == 0
    current_job = {"key": None}

    for job in jobs:
        entry = state.get(_job_key(job), {})
        if entry.get("status") != STATE_RUNNING:
            continue
        pid = entry.get("runner_pid")
        if entry.get("runner_host") == RUNNER_HOST and _pid_is_alive(pid) and pid != os.getpid():
            print(
                f"ERROR: job queue already running via PID {pid}. "
                f"Use 'python3 jobs.py status {job_path}' or reset it explicitly.",
                file=sys.stderr,
            )
            return 1

    def mark_interrupted(signum=None):
        key = current_job["key"]
        if key is None:
            return
        latest = _load_state(job_path)
        entry = latest.get(key, {})
        if entry.get("status") != STATE_RUNNING:
            return
        entry["status"] = STATE_FAILED
        entry["error"] = "interrupted" if signum is None else f"interrupted by signal {signum}"
        entry["interrupted"] = True
        entry["finished"] = datetime.now(timezone.utc).isoformat()
        entry.pop("runner_pid", None)
        entry.pop("runner_host", None)
        entry.pop("runner_mode", None)
        latest[key] = entry
        _save_state(job_path, latest)
        current_job["key"] = None

    def handle_signal(signum, _frame):
        mark_interrupted(signum)
        raise SystemExit(128 + signum)

    atexit.register(mark_interrupted)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    for j in jobs:
        key = _job_key(j)
        s = state.get(key, {})
        st = s.get("status", STATE_PENDING)

        if st == STATE_DONE:
            done += 1
            continue

        cmd = j["cmd"]
        # When already root, strip leading "sudo" -- it's redundant and
        # it clobbers SUDO_USER/ATLAS_USER in the child process.
        if is_root and cmd.lstrip().startswith("sudo "):
            cmd = cmd.lstrip().removeprefix("sudo ").lstrip()

        now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"\n{'='*60}", flush=True)
        print(f"  [{now_str}] Job #{j['id']}/{total}: {j['name']}", flush=True)
        print(f"  cmd: {cmd}", flush=True)
        print(f"{'='*60}", flush=True)

        if dry:
            print("  (dry run -- skipped)", flush=True)
            continue

        state[key] = {
            "status": STATE_RUNNING,
            "started": datetime.now(timezone.utc).isoformat(),
            "runner_pid": os.getpid(),
            "runner_host": RUNNER_HOST,
            "runner_mode": "direct",
        }
        _save_state(job_path, state)
        current_job["key"] = key

        t0 = time.monotonic()
        try:
            sys.stdout.flush()
            subprocess.run(cmd, shell=True, check=True)
            elapsed = time.monotonic() - t0
            state[key] = {
                "status": STATE_DONE,
                "elapsed_s": round(elapsed, 1),
                "finished": datetime.now(timezone.utc).isoformat(),
            }
            done += 1
            print(f"\n  [+] Job #{j['id']} done ({elapsed:.0f}s)")
        except subprocess.CalledProcessError as e:
            elapsed = time.monotonic() - t0
            state[key] = {
                "status": STATE_FAILED,
                "elapsed_s": round(elapsed, 1),
                "error": f"exit code {e.returncode}",
                "finished": datetime.now(timezone.utc).isoformat(),
            }
            failed += 1
            print(f"\n  [X] Job #{j['id']} FAILED (exit {e.returncode}, {elapsed:.0f}s)")
            print(f"    Resume later:  python3 jobs.py run {job_path}")
            # Continue to next job instead of aborting entire queue
            continue
        finally:
            current_job["key"] = None
            _save_state(job_path, state)

    print(f"\n{'='*60}")
    print(f"  Summary: {done}/{total} done, {failed} failed, "
          f"{total - done - failed} skipped/pending")
    print(f"{'='*60}")

    return 1 if failed else 0


# --------------- screen commands ---------------

def cmd_start(job_path, dry=False, fresh=False):
    """Launch the queue in a detached screen session."""
    if not shutil.which("screen"):
        print("ERROR: screen is not installed.", file=sys.stderr)
        sys.exit(1)

    name = _screen_name(job_path)
    if _screen_exists(name):
        sudo_hint = "sudo " if os.geteuid() == 0 else ""
        print(f"  Screen '{name}' already running.")
        print(f"  Attach: {sudo_hint}python3 jobs.py attach {job_path}")
        print(f"  Stop:   {sudo_hint}python3 jobs.py stop {job_path}")
        sys.exit(1)

    if fresh:
        cmd_reset(job_path)

    abs_job = os.path.abspath(job_path)
    abs_self = os.path.abspath(__file__)
    log = _log_path(abs_job)
    cwd = os.path.dirname(abs_job) or "."

    # -u: unbuffered stdout so tee output ordering matches execution
    run_cmd = f"python3 -u {abs_self} run {abs_job}"
    if dry:
        run_cmd += " --dry"

    # Set ATLAS_USER so run.sh can drop privileges and chown results
    # back to the real user.  Unlike SUDO_USER, this survives nested
    # sudo calls because it is a plain env var, not overwritten by sudo.
    env_prefix = ""
    real_user = os.environ.get("SUDO_USER") or os.environ.get("ATLAS_USER")
    if real_user:
        env_prefix = f"export ATLAS_USER={real_user}; "

    inner = (
        f"{env_prefix}"
        f"cd {cwd} && "
        f"{run_cmd} 2>&1 | tee -a {log}; rc=${{PIPESTATUS[0]}}; "
        f"echo ''; "
        f"echo \"--- Queue finished (exit $rc) at $(date) ---\" | tee -a {log}; "
    )
    # If started with sudo, fix ownership of log/state files
    if real_user:
        state = _state_path(abs_job)
        inner += (
            f"chown {real_user}:{real_user} {log} {state} 2>/dev/null; "
        )
    inner += (
        f"echo 'Screen will close in 30s.  Press Enter to close now.'; "
        f"read -t 30 || true"
    )

    subprocess.run(
        ["screen", "-dmS", name, "bash", "-c", inner],
        check=True,
    )

    is_root = os.geteuid() == 0
    prefix = "sudo " if is_root else ""
    print(f"  Started screen '{name}'")
    print(f"  Log:    {log}")
    print(f"  Attach: {prefix}python3 jobs.py attach {job_path}")
    print(f"  Status: python3 jobs.py status {job_path}")
    if is_root:
        print(f"  (Screen owned by root -- attach/stop need sudo)")


def cmd_attach(job_path):
    """Reattach to the screen session."""
    name = _screen_name(job_path)
    if not _screen_exists(name):
        print(f"  No screen '{name}' found.")
        if os.geteuid() != 0:
            print(f"  If started with sudo: sudo python3 jobs.py attach {job_path}")
        else:
            print(f"  Start: python3 jobs.py start {job_path}")
        sys.exit(1)
    os.execvp("screen", ["screen", "-rd", name])


def cmd_stop(job_path):
    """Kill the screen session."""
    name = _screen_name(job_path)
    if not _screen_exists(name):
        print(f"  No screen '{name}' found.")
        if os.geteuid() != 0:
            print(f"  If started with sudo: sudo python3 jobs.py stop {job_path}")
        return
    subprocess.run(["screen", "-S", name, "-X", "quit"], check=True)
    print(f"  Stopped screen '{name}'.")


def cmd_log(job_path, follow=False):
    """Tail the output log."""
    log = _log_path(job_path)
    if not os.path.exists(log):
        print(f"  No log file: {log}")
        sys.exit(1)
    if follow:
        os.execvp("tail", ["tail", "-f", log])
    else:
        os.execvp("tail", ["tail", "-40", log])


def main():
    parser = argparse.ArgumentParser(
        description="Job queue runner for atlas-scenarios experiments")
    sub = parser.add_subparsers(dest="command")

    p_start = sub.add_parser("start", help="Launch queue in a detached screen")
    p_start.add_argument("jobfile", help="Path to job file (JSON or YAML)")
    p_start.add_argument("--dry", action="store_true",
                         help="Dry-run inside the screen (preview only)")
    p_start.add_argument("--fresh", action="store_true",
                         help="Reset all jobs to pending before starting")

    p_attach = sub.add_parser("attach", help="Reattach to the running screen")
    p_attach.add_argument("jobfile")

    p_stop = sub.add_parser("stop", help="Kill the screen session")
    p_stop.add_argument("jobfile")

    p_log = sub.add_parser("log", help="Tail the output log")
    p_log.add_argument("jobfile")
    p_log.add_argument("-f", "--follow", action="store_true",
                       help="Follow (like tail -f)")

    p_run = sub.add_parser("run", help="Run directly (no screen)")
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

    if args.command == "start":
        cmd_start(args.jobfile, dry=args.dry, fresh=args.fresh)
    elif args.command == "attach":
        cmd_attach(args.jobfile)
    elif args.command == "stop":
        cmd_stop(args.jobfile)
    elif args.command == "log":
        cmd_log(args.jobfile, follow=args.follow)
    elif args.command == "run":
        sys.exit(cmd_run(args.jobfile, dry=args.dry))
    elif args.command == "status":
        cmd_status(args.jobfile)
    elif args.command == "reset":
        cmd_reset(args.jobfile, args.job_id)


if __name__ == "__main__":
    main()
