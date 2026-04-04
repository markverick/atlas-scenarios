import argparse
import os
import shutil
import sys

from .conventions import resolve_queue_path, selector_from_path
from .runner import cmd_list, cmd_reset, cmd_run, cmd_status
from .screen_ops import cmd_attach, cmd_log, cmd_start, cmd_stop


def build_parser():
    parser = argparse.ArgumentParser(description="Experiment queue runner for atlas-scenarios")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Show experiments, scenarios, and queues")
    p_list.add_argument("--running", action="store_true", help="Show only currently running queues")

    sub.add_parser("running", help="Show currently running queues")

    p_start = sub.add_parser("start", help="Launch queue in a detached screen")
    p_start.add_argument("queue", nargs="?", help="Queue selector like prefix_scale/sprint_twostep_0to50")
    p_start.add_argument("--dry", action="store_true", help="Dry-run inside the screen")
    p_start.add_argument("--fresh", action="store_true", help="Reset all jobs to pending before starting")

    p_attach = sub.add_parser("attach", help="Reattach to the running screen")
    p_attach.add_argument("queue", nargs="?", help="Queue selector")

    p_stop = sub.add_parser("stop", help="Kill the screen session")
    p_stop.add_argument("queue", nargs="?", help="Queue selector")

    p_log = sub.add_parser("log", help="Tail the output log")
    p_log.add_argument("queue", nargs="?", help="Queue selector")
    p_log.add_argument("-f", "--follow", action="store_true", help="Follow log output")

    p_run = sub.add_parser("run", help="Run directly (used internally by start)")
    p_run.add_argument("queue", nargs="?", help="Queue selector")
    p_run.add_argument("--dry", action="store_true", help="Print commands without executing")

    p_status = sub.add_parser("status", help="Show job status")
    p_status.add_argument("queue", nargs="?", help="Queue selector")
    p_status.add_argument("-w", "--watch", action="store_true", help="Refresh status continuously")
    p_status.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds for --watch (default: 1.0)")

    p_reset = sub.add_parser("reset", help="Reset job(s) to pending")
    p_reset.add_argument("queue", nargs="?", help="Queue selector")
    p_reset.add_argument("job_id", nargs="?", type=int, default=None, help="Reset specific job #")
    return parser


def select_command_interactively():
    if not sys.stdin.isatty():
        return None

    options = [
        ("list", "List experiments and queues"),
        ("running", "List running queues"),
        ("start", "Start a queue"),
        ("status", "Show queue status"),
        ("log", "Show queue log"),
        ("attach", "Attach to running screen"),
        ("stop", "Stop a running screen"),
        ("reset", "Reset queue jobs to pending"),
        ("run", "Run queue in foreground"),
        ("quit", "Exit"),
    ]

    print("Jobs Menu:\n")
    for index, (_, label) in enumerate(options, start=1):
        print(f"  {index:>2}. {label}")

    while True:
        choice = input("\nSelect action number: ").strip()
        if not choice:
            continue
        if choice.isdigit():
            option_index = int(choice)
            if 1 <= option_index <= len(options):
                command = options[option_index - 1][0]
                return None if command == "quit" else command
        print("Invalid selection.", file=sys.stderr)


def prompt_yes_no(prompt, *, default=False):
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        answer = input(prompt + suffix).strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.", file=sys.stderr)


def prompt_job_id():
    while True:
        value = input("Reset specific job number (blank = all): ").strip()
        if not value:
            return None
        if value.isdigit():
            return int(value)
        print("Invalid job number.", file=sys.stderr)


def prompt_float(prompt, *, default):
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            parsed = float(value)
        except ValueError:
            print("Please enter a number.", file=sys.stderr)
            continue
        if parsed <= 0:
            print("Please enter a positive number.", file=sys.stderr)
            continue
        return parsed


def command_requires_sudo(command):
    return command in {"start", "run", "attach", "stop", "log"}


def exec_with_sudo(cli_args):
    if shutil.which("sudo") is None:
        print("ERROR: sudo is not installed.", file=sys.stderr)
        raise SystemExit(1)
    os.execvp("sudo", ["sudo", "-E", sys.executable, "-m", "jobs.cli", *cli_args])


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        command = select_command_interactively()
        if command is None:
            return 0
        if command == "list":
            cmd_list()
            return 0
        if command == "running":
            cmd_list(running_only=True)
            return 0

        prefer_active = command in {"status", "log", "attach", "stop"}
        queue_path = resolve_queue_path(None, prefer_active=prefer_active)
        queue_selector = selector_from_path(queue_path)
        if command == "start":
            fresh = prompt_yes_no("Reset all jobs before starting?", default=True)
            if os.geteuid() != 0 and command_requires_sudo(command):
                cli_args = [command, queue_selector]
                if fresh:
                    cli_args.append("--fresh")
                exec_with_sudo(cli_args)
            cmd_start(queue_path, dry=False, fresh=fresh)
            return 0
        if command == "attach":
            if os.geteuid() != 0 and command_requires_sudo(command):
                exec_with_sudo([command, queue_selector])
            cmd_attach(queue_path)
            return 0
        if command == "stop":
            if os.geteuid() != 0 and command_requires_sudo(command):
                exec_with_sudo([command, queue_selector])
            cmd_stop(queue_path)
            return 0
        if command == "log":
            follow = prompt_yes_no("Follow log output?", default=False)
            if os.geteuid() != 0 and command_requires_sudo(command):
                cli_args = [command, queue_selector]
                if follow:
                    cli_args.append("--follow")
                exec_with_sudo(cli_args)
            cmd_log(queue_path, follow=follow)
            return 0
        if command == "run":
            dry = prompt_yes_no("Dry run only?", default=False)
            if os.geteuid() != 0 and command_requires_sudo(command):
                cli_args = [command, queue_selector]
                if dry:
                    cli_args.append("--dry")
                exec_with_sudo(cli_args)
            return cmd_run(queue_path, dry=dry)
        if command == "status":
            watch = prompt_yes_no("Watch status updates?", default=False)
            interval = prompt_float("Refresh interval in seconds", default=1.0) if watch else 1.0
            cmd_status(queue_path, watch=watch, interval_s=interval)
            return 0
        if command == "reset":
            cmd_reset(queue_path, prompt_job_id())
            return 0
        parser.print_help()
        return 1

    if os.geteuid() != 0 and command_requires_sudo(args.command):
        exec_with_sudo(argv)

    if args.command == "list":
        cmd_list(running_only=args.running)
        return 0
    if args.command == "running":
        cmd_list(running_only=True)
        return 0

    prefer_active = args.command in {"status", "log", "attach", "stop"}
    queue_path = resolve_queue_path(getattr(args, "queue", None), prefer_active=prefer_active)
    if args.command == "start":
        cmd_start(queue_path, dry=args.dry, fresh=args.fresh)
        return 0
    if args.command == "attach":
        cmd_attach(queue_path)
        return 0
    if args.command == "stop":
        cmd_stop(queue_path)
        return 0
    if args.command == "log":
        cmd_log(queue_path, follow=args.follow)
        return 0
    if args.command == "run":
        return cmd_run(queue_path, dry=args.dry)
    if args.command == "status":
        cmd_status(queue_path, watch=args.watch, interval_s=args.interval)
        return 0
    if args.command == "reset":
        cmd_reset(queue_path, args.job_id)
        return 0
    print(f"Unknown command: {args.command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())