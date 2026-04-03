import os
import shutil
import subprocess
import sys

from .runner import cmd_reset, queue_context, queue_ref
from .state import log_path, screen_exists, screen_name, state_path


def cmd_start(job_path, dry=False, fresh=False):
    if not shutil.which("screen"):
        print("ERROR: screen is not installed.", file=sys.stderr)
        sys.exit(1)

    selector = queue_ref(job_path)
    name = screen_name(job_path)
    if screen_exists(name):
        sudo_hint = "sudo " if os.geteuid() == 0 else ""
        print(f"  Screen '{name}' already running.")
        print(f"  Attach: {sudo_hint}./jobs.sh attach {selector}")
        print(f"  Stop:   {sudo_hint}./jobs.sh stop {selector}")
        sys.exit(1)

    if fresh:
        cmd_reset(job_path)

    _, _, run_context, _ = queue_context(job_path)
    abs_job = os.path.abspath(job_path)
    abs_self = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "jobs.sh"))
    log = log_path(abs_job)
    cwd = os.path.dirname(abs_job) or "."
    run_cmd = f"{abs_self} run {selector}"
    if dry:
        run_cmd += " --dry"

    env_prefix = ""
    real_user = os.environ.get("SUDO_USER") or os.environ.get("ATLAS_USER")
    if real_user:
        env_prefix = f"export ATLAS_USER={real_user}; "

    inner = (
        f"{env_prefix}cd {cwd} && {run_cmd} 2>&1 | tee -a {log}; rc=${{PIPESTATUS[0]}}; "
        "echo ''; "
        f"echo \"--- Queue finished (exit $rc) at $(date) ---\" | tee -a {log}; "
    )
    if real_user:
        state_file = state_path(abs_job)
        inner += f"chown {real_user}:{real_user} {log} {state_file} 2>/dev/null; "
    inner += "echo 'Screen will close in 30s.  Press Enter to close now.'; read -t 30 || true"

    subprocess.run(["screen", "-dmS", name, "bash", "-c", inner], check=True)

    prefix = "sudo " if os.geteuid() == 0 else ""
    print(f"  Started screen '{name}'")
    print(f"  Queue:  {selector}")
    if run_context.get("run_root"):
        print(f"  Output: {run_context['run_root']}")
    print(f"  Log:    {log}")
    print(f"  Attach: {prefix}./jobs.sh attach {selector}")
    print(f"  Status: ./jobs.sh status {selector}")
    if os.geteuid() == 0:
        print("  (Screen owned by root -- attach/stop need sudo)")


def cmd_attach(job_path):
    selector = queue_ref(job_path)
    name = screen_name(job_path)
    if not screen_exists(name):
        print(f"  No screen '{name}' found.")
        if os.geteuid() != 0:
            print(f"  If started with sudo: sudo ./jobs.sh attach {selector}")
        else:
            print(f"  Start: ./jobs.sh start {selector}")
        sys.exit(1)
    os.execvp("screen", ["screen", "-rd", name])


def cmd_stop(job_path):
    selector = queue_ref(job_path)
    name = screen_name(job_path)
    if not screen_exists(name):
        print(f"  No screen '{name}' found.")
        if os.geteuid() != 0:
            print(f"  If started with sudo: sudo ./jobs.sh stop {selector}")
        return
    subprocess.run(["screen", "-S", name, "-X", "quit"], check=True)
    print(f"  Stopped screen '{name}' for {selector}.")


def cmd_log(job_path, follow=False):
    path = log_path(job_path)
    if not os.path.exists(path):
        print(f"  No log file: {path}")
        sys.exit(1)
    if follow:
        os.execvp("tail", ["tail", "-f", path])
    os.execvp("tail", ["tail", "-40", path])