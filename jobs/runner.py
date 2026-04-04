import atexit
import curses
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from .conventions import discover_active_queues, discover_catalog, queue_stem, selector_from_path
from .spec import build_run_context, load_job_spec, load_jobs
from .state import (
    RUNNER_HOST,
    STATE_DONE,
    STATE_FAILED,
    STATE_PENDING,
    STATE_RUNNING,
    STATE_META_KEY,
    cleanup_stale_running,
    clear_runtime_fields,
    load_state,
    log_path,
    pid_is_alive,
    report_stale_running,
    save_state,
    state_job_keys,
)


def queue_ref(job_path):
    return selector_from_path(job_path)


def queue_context(job_path):
    state = load_state(job_path)
    spec = load_job_spec(job_path)
    selector = spec.get("selector") or queue_ref(job_path)
    context = build_run_context(job_path, spec, state, selector=selector, stem=queue_stem(job_path))
    save_state(job_path, state)
    return spec, state, context, selector


def format_queue_error(exc):
    message = str(exc).strip()
    if message:
        return f"{type(exc).__name__}: {message}"
    return type(exc).__name__


def record_queue_error(job_path, message):
    latest = load_state(job_path)
    meta = latest.setdefault(STATE_META_KEY, {})
    meta["queue_error"] = message
    meta["queue_error_at"] = datetime.now(timezone.utc).isoformat()
    latest[STATE_META_KEY] = meta
    save_state(job_path, latest)


def clear_queue_error(state):
    meta = state.get(STATE_META_KEY)
    if not isinstance(meta, dict):
        return
    meta.pop("queue_error", None)
    meta.pop("queue_error_at", None)


def cmd_list(*, running_only=False):
    if running_only:
        active = discover_active_queues()
        if not active:
            print("No running queues found.")
            return

        print("Running queues\n")
        for queue in active:
            counts = queue["counts"]
            meta = []
            if queue.get("topology"):
                meta.append(f"topology={queue['topology']}")
            if queue.get("mode"):
                meta.append(f"mode={queue['mode']}")
            suffix = f" ({', '.join(meta)})" if meta else ""
            print(f"- {queue['selector']}{suffix}")
            print(
                "  "
                f"running={counts[STATE_RUNNING]} done={counts[STATE_DONE]} "
                f"pending={counts[STATE_PENDING]} failed={counts[STATE_FAILED]}"
            )
            if queue.get("run_root"):
                print(f"  run_root: {queue['run_root']}")
            print("")
        return

    catalog = discover_catalog()
    if not catalog:
        print("No experiment queues discovered under experiments/.")
        return

    for experiment in catalog:
        print(experiment["experiment"])
        if experiment["scenarios"]:
            print(f"  scenarios: {', '.join(experiment['scenarios'])}")
        else:
            print("  scenarios: none")
        if experiment["queues"]:
            print("  queues:")
            for queue in experiment["queues"]:
                meta = []
                if queue.get("topology"):
                    meta.append(f"topology={queue['topology']}")
                if queue.get("mode"):
                    meta.append(f"mode={queue['mode']}")
                suffix = f" ({', '.join(meta)})" if meta else ""
                print(f"    - {queue['selector']}{suffix}")
                if queue.get("description"):
                    print(f"      {queue['description']}")
        else:
            print("  queues: none")
        print("")


def _status_lines(job_path, *, running_mark="~"):
    _, state, run_context, selector = queue_context(job_path)
    jobs = load_jobs(job_path, run_context)
    stale = cleanup_stale_running(job_path, jobs, state)
    lines = []
    if stale:
        lines.append("WARNING: cleaned up stale running state:")
        for job in stale:
            lines.append(f"  - job #{job['id']}: {job['name']}")
        lines.append("  Review failure details, then reset explicitly before rerunning.")
        lines.append("")
        state = load_state(job_path)

    if run_context.get("run_root"):
        lines.append(f"Run root: {run_context['run_root']}")
    lines.append(f"Queue:    {selector}")

    meta = state.get(STATE_META_KEY, {})
    if meta.get("queue_error"):
        timestamp = meta.get("queue_error_at")
        suffix = f" ({timestamp})" if timestamp else ""
        lines.append("")
        lines.append(f"Queue error: {meta['queue_error']}{suffix}")

    counts = {STATE_PENDING: 0, STATE_RUNNING: 0, STATE_DONE: 0, STATE_FAILED: 0}
    marks = {STATE_PENDING: " ", STATE_RUNNING: running_mark, STATE_DONE: "+", STATE_FAILED: "X"}
    for job in jobs:
        entry = state.get(str(job["id"]), {})
        status = entry.get("status", STATE_PENDING)
        counts[status] += 1

    total = len(jobs)
    completed = counts[STATE_DONE] + counts[STATE_FAILED]
    lines.append("")
    lines.append(
        f"Progress: [{_progress_bar(completed, total)}] "
        f"{completed}/{total} complete"
    )
    lines.append(
        "State:    "
        f"running={counts[STATE_RUNNING]} done={counts[STATE_DONE]} "
        f"pending={counts[STATE_PENDING]} failed={counts[STATE_FAILED]}"
    )
    lines.append("")

    for job in jobs:
        entry = state.get(str(job["id"]), {})
        status = entry.get("status", STATE_PENDING)
        elapsed = f"  ({entry['elapsed_s']:.0f}s)" if entry.get("elapsed_s") else ""
        lines.append(f"  [{marks[status]}] #{job['id']:>2}  {status:<8}  {job['name']}{elapsed}")

    lines.append("")
    lines.append(f"  {counts[STATE_DONE]}/{total} done, {counts[STATE_FAILED]} failed, {counts[STATE_PENDING]} pending")
    return lines


def _render_status(job_path):
    return "\n".join(_status_lines(job_path))


def _trim_line(line, width):
    if width <= 0:
        return ""
    if len(line) <= width:
        return line
    if width <= 3:
        return line[:width]
    return f"{line[:width - 3]}..."


def _progress_bar(completed, total, *, width=24):
    if width <= 0:
        return ""
    if total <= 0:
        return "-" * width
    filled = min(width, max(0, int(round((completed / total) * width))))
    return "#" * filled + "-" * (width - filled)


def _watch_status_tui(job_path, *, interval_s):
    spinner_frames = "|/-\\"
    running_frames = ("~", ">", "~", "<")

    def run(stdscr):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        stdscr.nodelay(False)
        stdscr.timeout(max(100, int(interval_s * 1000)))

        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_CYAN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)

        scroll = 0
        spinner_index = 0

        while True:
            lines = _status_lines(
                job_path,
                running_mark=running_frames[spinner_index % len(running_frames)],
            )
            rows, cols = stdscr.getmaxyx()
            body_top = 1
            footer_rows = 2
            body_height = max(1, rows - body_top - footer_rows)
            max_scroll = max(0, len(lines) - body_height)
            scroll = min(scroll, max_scroll)

            stdscr.erase()

            title = f" {spinner_frames[spinner_index % len(spinner_frames)]} Live Queue Status "
            subtitle = f"refresh {interval_s:g}s"
            header = _trim_line(f"{title} {subtitle}", cols - 1)
            try:
                attr = curses.color_pair(1) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
                stdscr.addnstr(0, 0, header, max(0, cols - 1), attr)
            except curses.error:
                pass

            visible_lines = lines[scroll:scroll + body_height]
            for index, line in enumerate(visible_lines, start=body_top):
                try:
                    stdscr.addnstr(index, 0, _trim_line(line, cols - 1), max(0, cols - 1))
                except curses.error:
                    pass

            footer_y = rows - 2
            nav = "Arrows scroll  PgUp/PgDn jump  Home/End bounds  q quit"
            pos = f"lines {scroll + 1}-{min(len(lines), scroll + body_height)}/{len(lines)}"
            try:
                attr = curses.color_pair(2) if curses.has_colors() else curses.A_REVERSE
                stdscr.addnstr(footer_y, 0, _trim_line(nav, cols - 1), max(0, cols - 1), attr)
                stdscr.addnstr(footer_y + 1, 0, _trim_line(pos, cols - 1), max(0, cols - 1), attr)
            except curses.error:
                pass

            stdscr.refresh()
            spinner_index += 1

            key = stdscr.getch()
            if key in (-1, curses.KEY_RESIZE):
                continue
            if key in (ord("q"), ord("Q")):
                return
            if key == curses.KEY_UP:
                scroll = max(0, scroll - 1)
            elif key == curses.KEY_DOWN:
                scroll = min(max_scroll, scroll + 1)
            elif key == curses.KEY_PPAGE:
                scroll = max(0, scroll - body_height)
            elif key == curses.KEY_NPAGE:
                scroll = min(max_scroll, scroll + body_height)
            elif key == curses.KEY_HOME:
                scroll = 0
            elif key == curses.KEY_END:
                scroll = max_scroll

    curses.wrapper(run)


def cmd_status(job_path, *, watch=False, interval_s=1.0, output=None, _max_updates=None):
    output = output or sys.stdout
    updates = 0

    if watch and _max_updates is None and hasattr(output, "isatty") and output.isatty():
        _watch_status_tui(job_path, interval_s=interval_s)
        return

    while True:
        report = _render_status(job_path)
        if watch:
            if hasattr(output, "isatty") and output.isatty():
                output.write("\x1b[2J\x1b[H")
            elif updates > 0:
                output.write("\n")
            output.write(report)
            output.write(f"\n\nRefreshing every {interval_s:g}s. Press Ctrl-C to stop.\n")
            output.flush()

            updates += 1
            if _max_updates is not None and updates >= _max_updates:
                return
            time.sleep(interval_s)
            continue

        output.write(report)
        output.write("\n")
        output.flush()
        return


def cmd_reset(job_path, job_id=None):
    state = load_state(job_path)
    if job_id is not None:
        key = str(job_id)
        if key in state:
            state[key]["status"] = STATE_PENDING
            clear_runtime_fields(state[key])
            print(f"  Reset job #{job_id} to pending.")
        else:
            state[key] = {"status": STATE_PENDING}
            print(f"  Reset job #{job_id} to pending (no prior state).")
    else:
        keys = state_job_keys(state)
        for key in keys:
            state[key]["status"] = STATE_PENDING
            clear_runtime_fields(state[key])
        state.pop(STATE_META_KEY, None)
        print(f"  Reset all {len(keys)} jobs to pending.")
    save_state(job_path, state)


def cmd_run(job_path, dry=False):
    selector = queue_ref(job_path)
    try:
        _, state, run_context, selector = queue_context(job_path)
        jobs = load_jobs(job_path, run_context)
        stale = cleanup_stale_running(job_path, jobs, state, keep_pid=os.getpid())
        if stale:
            report_stale_running(selector, stale)
            return 1
        state = load_state(job_path)

        total = len(jobs)
        done = 0
        failed = 0
        is_root = os.geteuid() == 0
        current_job = {"key": None}

        for job in jobs:
            entry = state.get(str(job["id"]), {})
            if entry.get("status") != STATE_RUNNING:
                continue
            pid = entry.get("runner_pid")
            if entry.get("runner_host") == RUNNER_HOST and pid_is_alive(pid) and pid != os.getpid():
                print(
                    f"ERROR: job queue already running via PID {pid}. Use './jobs.sh status {selector}' or reset it explicitly.",
                    file=sys.stderr,
                )
                return 1

        clear_queue_error(state)
        save_state(job_path, state)

        def mark_interrupted(signum=None):
            key = current_job["key"]
            if key is None:
                return
            latest = load_state(job_path)
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
            save_state(job_path, latest)
            current_job["key"] = None

        def handle_signal(signum, _frame):
            mark_interrupted(signum)
            raise SystemExit(128 + signum)

        atexit.register(mark_interrupted)
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        if run_context.get("run_root"):
            print(f"Run root: {run_context['run_root']}")
        print(f"Queue:    {selector}")

        for job in jobs:
            key = str(job["id"])
            entry = state.get(key, {})
            status = entry.get("status", STATE_PENDING)
            if status == STATE_DONE:
                done += 1
                continue

            cmd = job["cmd"]
            if is_root and cmd.lstrip().startswith("sudo "):
                cmd = cmd.lstrip().removeprefix("sudo ").lstrip()

            now_str = datetime.now(timezone.utc).strftime("%H:%M:%S")
            print(f"\n{'=' * 60}", flush=True)
            print(f"  [{now_str}] Job #{job['id']}/{total}: {job['name']}", flush=True)
            print(f"  cmd: {cmd}", flush=True)
            print(f"{'=' * 60}", flush=True)

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
            save_state(job_path, state)
            current_job["key"] = key

            started = time.monotonic()
            try:
                sys.stdout.flush()
                subprocess.run(cmd, shell=True, check=True)
                elapsed = time.monotonic() - started
                state[key] = {
                    "status": STATE_DONE,
                    "elapsed_s": round(elapsed, 1),
                    "finished": datetime.now(timezone.utc).isoformat(),
                }
                done += 1
                print(f"\n  [+] Job #{job['id']} done ({elapsed:.0f}s)")
            except subprocess.CalledProcessError as exc:
                elapsed = time.monotonic() - started
                state[key] = {
                    "status": STATE_FAILED,
                    "elapsed_s": round(elapsed, 1),
                    "error": f"exit code {exc.returncode}",
                    "finished": datetime.now(timezone.utc).isoformat(),
                }
                failed += 1
                print(f"\n  [X] Job #{job['id']} FAILED (exit {exc.returncode}, {elapsed:.0f}s)")
                print(f"    Resume later:  ./jobs.sh run {selector}")
            finally:
                current_job["key"] = None
                save_state(job_path, state)

        print(f"\n{'=' * 60}")
        print(f"  Summary: {done}/{total} done, {failed} failed, {total - done - failed} skipped/pending")
        print(f"{'=' * 60}")
        return 1 if failed else 0
    except BaseException as exc:
        if isinstance(exc, SystemExit) and exc.code in (0, None):
            raise
        message = format_queue_error(exc)
        record_queue_error(job_path, message)
        print(f"ERROR: queue execution aborted: {message}", file=sys.stderr)
        raise

