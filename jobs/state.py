import hashlib
import json
import os
import pwd
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone


def _fix_owner(path):
    """Chown *path* to the real (non-root) user when running under sudo."""
    if os.geteuid() != 0:
        return
    real_user = os.environ.get("SUDO_USER") or os.environ.get("ATLAS_USER")
    if not real_user:
        return
    try:
        pw = pwd.getpwnam(real_user)
        os.chown(path, pw.pw_uid, pw.pw_gid)
    except (KeyError, OSError):
        pass

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_META_KEY = "__meta__"
RUNNER_HOST = socket.gethostname()


def jobs_meta_dir(job_path):
    abs_job = os.path.abspath(job_path)
    stem = os.path.splitext(os.path.basename(abs_job))[0]
    digest = hashlib.sha1(abs_job.encode("utf-8")).hexdigest()[:8]
    meta_dir = os.path.join(os.path.dirname(abs_job), ".jobs", f"{stem}-{digest}")
    os.makedirs(meta_dir, exist_ok=True)
    _fix_owner(meta_dir)
    return meta_dir


def state_path(job_path):
    return os.path.join(jobs_meta_dir(job_path), "state.json")


def log_path(job_path):
    return os.path.join(jobs_meta_dir(job_path), "queue.log")


def screen_name(job_path):
    abs_job = os.path.abspath(job_path)
    stem = os.path.splitext(os.path.basename(abs_job))[0]
    digest = hashlib.sha1(abs_job.encode("utf-8")).hexdigest()[:8]
    return f"{stem}-{digest}"


def screen_exists(name):
    result = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
    return f".{name}\t" in result.stdout


def load_state(job_path):
    path = state_path(job_path)
    for attempt in range(5):
        if not os.path.exists(path):
            return {}
        try:
            with open(path) as handle:
                return json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError):
            if attempt == 4:
                raise
            time.sleep(0.02)
    return {}


def save_state(job_path, state):
    path = state_path(job_path)
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(prefix="state-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _fix_owner(tmp_path)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    _fix_owner(path)


def state_job_keys(state):
    return [key for key in state.keys() if key != STATE_META_KEY]


def clear_runtime_fields(entry):
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


def pid_is_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def cleanup_stale_running(job_path, jobs, state, *, keep_pid=None):
    stale = []
    for job in jobs:
        key = str(job["id"])
        entry = state.get(key)
        if not entry or entry.get("status") != STATE_RUNNING:
            continue

        pid = entry.get("runner_pid")
        host = entry.get("runner_host")
        if host == RUNNER_HOST and pid == keep_pid:
            continue
        if host == RUNNER_HOST and pid_is_alive(pid):
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
        save_state(job_path, state)
    return stale


def report_stale_running(job_ref, stale_jobs):
    if not stale_jobs:
        return
    print("ERROR: stale running job state detected and cleaned up:", file=sys.stderr)
    for job in stale_jobs:
        print(f"  - job #{job['id']}: {job['name']}", file=sys.stderr)
    print(
        f"Queue execution was interrupted earlier. Review with './jobs.sh status {job_ref}' "
        "and reset intentionally before rerunning.",
        file=sys.stderr,
    )