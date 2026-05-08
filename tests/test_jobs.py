"""Tests for modular jobs runner helpers."""
import io
import json
import os
import shutil
import subprocess
import sys
import signal
from contextlib import redirect_stdout

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from jobs.conventions import InteractiveCancel, discover_active_queues, discover_catalog, queue_stem, resolve_queue_path, selector_from_path, select_queue_interactively
from jobs import cli as jobs_cli
from jobs.runner import _progress_bar, _trim_line, cmd_list, cmd_run, cmd_status
from jobs.spec import build_run_context, expand_matrix, load_job_spec, load_jobs
from jobs import state as jobs_state
from jobs.state import STATE_META_KEY, load_state, save_state, screen_exists, state_path


def test_expand_matrix_no_matrix():
    job = {"name": "simple", "cmd": "echo hello"}
    result = expand_matrix(job)
    assert len(result) == 1
    assert result[0]["cmd"] == "echo hello"


def test_expand_matrix_single_key():
    job = {
        "name": "run {mode}",
        "cmd": "test --mode {mode}",
        "matrix": {"mode": ["a", "b", "c"]},
    }
    result = expand_matrix(job)
    assert len(result) == 3
    assert result[0]["name"] == "run a"
    assert result[1]["cmd"] == "test --mode b"
    assert all("matrix" not in j for j in result)


def test_expand_matrix_cartesian_product():
    job = {
        "name": "{mode} p{n}",
        "cmd": "--mode {mode} --n {n}",
        "matrix": {"mode": ["x", "y"], "n": [1, 2, 3]},
    }
    result = expand_matrix(job)
    # sorted keys: mode, n → product is mode × n
    assert len(result) == 6
    names = [j["name"] for j in result]
    assert "x p1" in names
    assert "y p3" in names


def test_expand_matrix_preserves_other_fields():
    job = {
        "name": "j {x}",
        "cmd": "run {x}",
        "extra_field": 42,
        "matrix": {"x": ["a"]},
    }
    result = expand_matrix(job)
    assert result[0]["extra_field"] == 42


def test_load_jobs_with_matrix(tmp_path):
    data = {
        "jobs": [
            {"name": "fixed", "cmd": "echo fixed"},
            {
                "name": "gen {v}",
                "cmd": "echo {v}",
                "matrix": {"v": [1, 2]},
            },
        ]
    }
    path = os.path.join(str(tmp_path), "test.json")
    with open(path, "w") as f:
        json.dump(data, f)

    jobs = load_jobs(path)
    assert len(jobs) == 3  # 1 fixed + 2 expanded
    # IDs should be sequential 1, 2, 3
    assert [j["id"] for j in jobs] == [1, 2, 3]
    assert jobs[0]["name"] == "fixed"
    assert jobs[1]["name"] == "gen 1"
    assert jobs[2]["name"] == "gen 2"


def test_load_jobs_empty_matrix(tmp_path):
    data = {"jobs": [{"name": "a", "cmd": "echo a", "matrix": {}}]}
    path = os.path.join(str(tmp_path), "test.json")
    with open(path, "w") as f:
        json.dump(data, f)
    jobs = load_jobs(path)
    assert len(jobs) == 1


def test_load_jobs_applies_run_context(tmp_path):
    data = {
        "run_root_template": "results/demo/{timestamp}",
        "jobs": [
            {
                "name": "sim p{prefixes}",
                "cmd": "run --out {run_root}/sim --prefixes {prefixes}",
                "matrix": {"prefixes": [0, 5]},
            }
        ],
    }
    path = os.path.join(str(tmp_path), "test.json")
    with open(path, "w") as f:
        json.dump(data, f)

    jobs = load_jobs(path, {"timestamp": "20260403-120000", "run_root": "results/demo/20260403-120000"})
    assert jobs[0]["cmd"] == "run --out results/demo/20260403-120000/sim --prefixes 0"
    assert jobs[1]["name"] == "sim p5"


def test_load_job_spec_requires_timestamp_in_run_root_template(tmp_path):
    data = {
        "run_root_template": "experiments/prefix_scale/results/latest",
        "jobs": [{"name": "build", "cmd": "true"}],
    }
    path = os.path.join(str(tmp_path), "test.json")
    with open(path, "w") as f:
        json.dump(data, f)

    with pytest.raises(SystemExit):
        load_job_spec(path)


def test_3x3_bothphase_queue_builds_once_then_runs_no_build():
    repo_dir = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(
        repo_dir,
        "experiments",
        "scalability",
        "queues",
        "3x3_bothphase_tables.json",
    )

    spec = load_job_spec(path)
    state = {}
    selector = spec.get("selector") or selector_from_path(path, root=repo_dir)
    context, _ = build_run_context(path, spec, state, selector=selector, stem=queue_stem(path))
    jobs = load_jobs(path, context)

    assert [job["name"] for job in jobs] == [
        "build twophase and onephase",
        "sim twophase 3x3 x3",
        "sim onephase 3x3 x3",
        "render 3x3 summary table",
    ]
    assert jobs[0]["cmd"] == "./run.sh build && ./run.sh --env onephase build"
    assert jobs[1]["cmd"].startswith("./run.sh sim --no-build scalability --allow-no-convergence")
    assert jobs[2]["cmd"].startswith("./run.sh --env onephase sim --no-build scalability --allow-no-convergence")
    assert jobs[3]["cmd"].startswith("./run.sh as-user python3 aggregate.py --grid-size 3")
    assert "tables-3x3.md" in jobs[3]["cmd"]


def test_queue_render_runs_as_user():
    repo_dir = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(
        repo_dir,
        "experiments",
        "scalability",
        "queues",
        "3x3_bothphase_tables.json",
    )

    spec = load_job_spec(path)
    assert spec["jobs"][3]["cmd"].startswith("./run.sh as-user python3 aggregate.py")


def test_core_edge_prefix_scale_queue_renders_plots_as_user():
    repo_dir = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(
        repo_dir,
        "experiments",
        "prefix_scale",
        "queues",
        "core_edge_bothphase_p0to5by1.json",
    )

    spec = load_job_spec(path)
    state = {}
    selector = spec.get("selector") or selector_from_path(path, root=repo_dir)
    context, _ = build_run_context(path, spec, state, selector=selector, stem=queue_stem(path))
    jobs = load_jobs(path, context)

    assert len(jobs) == 16
    assert jobs[0]["name"] == "build twophase and onephase"
    assert jobs[0]["cmd"] == "./run.sh build && ./run.sh --env onephase build"
    assert jobs[1]["name"].startswith("stage1 [twophase]")
    assert "--snap-export" in jobs[1]["cmd"]
    assert "--snap-import" not in jobs[1]["cmd"]
    assert "--core-disable-prefix-egress-replication" in jobs[1]["cmd"]
    assert jobs[2]["name"].startswith("stage1 [onephase]")
    assert "--snap-export" in jobs[2]["cmd"]
    assert jobs[-1]["cmd"] == f"./run.sh as-user python3 experiments/prefix_scale/plot.py --source-label sim --data {context['run_root']}"


def test_core_edge_prefix_scale_0to50_by10_queue_runs_both_phases():
    repo_dir = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(
        repo_dir,
        "experiments",
        "prefix_scale",
        "queues",
        "core_edge_bothphase_p0to50by10.json",
    )

    spec = load_job_spec(path)
    state = {}
    selector = spec.get("selector") or selector_from_path(path, root=repo_dir)
    context, _ = build_run_context(path, spec, state, selector=selector, stem=queue_stem(path))
    jobs = load_jobs(path, context)

    assert len(jobs) == 16
    assert jobs[0]["name"] == "build twophase and onephase"
    assert jobs[1]["name"].startswith("stage1 [twophase]")
    assert "--snap-export" in jobs[1]["cmd"]
    assert "--core-disable-prefix-egress-replication" in jobs[1]["cmd"]
    assert jobs[2]["name"].startswith("stage1 [onephase]")
    assert "--snap-export" in jobs[2]["cmd"]
    # all stage2 jobs have snap-import
    for job in jobs[3:-1]:
        assert "--snap-import" in job["cmd"]
    assert jobs[-1]["cmd"] == f"./run.sh as-user python3 experiments/prefix_scale/plot.py --source-label sim --data {context['run_root']}"


def test_rocketfuel_prefix_scale_queue_runs_both_phases():
    repo_dir = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(
        repo_dir,
        "experiments",
        "prefix_scale",
        "queues",
        "rocketfuel_4755_bothphase_p0to500by100.json",
    )

    spec = load_job_spec(path)
    state = {}
    selector = spec.get("selector") or selector_from_path(path, root=repo_dir)
    context, _ = build_run_context(path, spec, state, selector=selector, stem=queue_stem(path))
    jobs = load_jobs(path, context)

    assert len(jobs) == 16
    assert jobs[0]["name"] == "build twophase and onephase"
    assert jobs[1]["name"].startswith("stage1 [twophase]")
    assert "--topology rocketfuel_4755" in jobs[1]["cmd"]
    assert "--snap-export" in jobs[1]["cmd"]
    assert "--core-disable-prefix-egress-replication" in jobs[1]["cmd"]
    assert jobs[2]["name"].startswith("stage1 [onephase]")
    assert "--topology rocketfuel_4755" in jobs[2]["cmd"]
    assert jobs[-1]["cmd"] == f"./run.sh as-user python3 experiments/prefix_scale/plot.py --source-label sim --data {context['run_root']}"


def test_large_rocketfuel_prefix_scale_queue_runs_both_phases():
    repo_dir = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(
        repo_dir,
        "experiments",
        "prefix_scale",
        "queues",
        "rocketfuel_2914_bothphase_p0to500by100.json",
    )

    spec = load_job_spec(path)
    state = {}
    selector = spec.get("selector") or selector_from_path(path, root=repo_dir)
    context, _ = build_run_context(path, spec, state, selector=selector, stem=queue_stem(path))
    jobs = load_jobs(path, context)

    assert len(jobs) == 16
    assert jobs[0]["name"] == "build twophase and onephase"
    assert jobs[1]["name"].startswith("stage1 [twophase]")
    assert "--topology rocketfuel_2914" in jobs[1]["cmd"]
    assert "--snap-export" in jobs[1]["cmd"]
    assert "--core-disable-prefix-egress-replication" in jobs[1]["cmd"]
    assert jobs[2]["name"].startswith("stage1 [onephase]")
    assert "--topology rocketfuel_2914" in jobs[2]["cmd"]
    assert jobs[-1]["cmd"] == f"./run.sh as-user python3 experiments/prefix_scale/plot.py --source-label sim --data {context['run_root']}"


def _fake_root_env(tmp_path):
    real_id = shutil.which("id")
    assert real_id is not None

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_id = fake_bin / "id"
    fake_id.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"-u\" ]; then\n"
        "  echo 0\n"
        "  exit 0\n"
        "fi\n"
        f"exec {real_id} \"$@\"\n"
    )
    fake_id.chmod(0o755)

    env = os.environ.copy()
    env.pop("ATLAS_USER", None)
    env.pop("SUDO_USER", None)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return env


def test_run_sh_as_user_requires_target_user_when_running_as_root(tmp_path):
    env = _fake_root_env(tmp_path)
    result = subprocess.run(
        [
            "./run.sh",
            "as-user",
            "python3",
            "-c",
            "print('unexpected-success')",
        ],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ATLAS_USER or SUDO_USER must be set" in result.stderr


def test_run_sh_build_requires_target_user_when_running_as_root(tmp_path):
    env = _fake_root_env(tmp_path)
    result = subprocess.run(
        ["./run.sh", "build"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ATLAS_USER or SUDO_USER must be set" in result.stderr


def test_discover_job_catalog_for_experiment_selector(tmp_path):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_scenarios_dir = tmp_path / "experiments" / "prefix_scale" / "scenarios"
    exp_jobs_dir.mkdir(parents=True)
    exp_scenarios_dir.mkdir(parents=True)
    (exp_scenarios_dir / "demo.json").write_text("{}")
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({
        "experiment": "prefix_scale",
        "topology": "sprint",
        "mode": "one_phase",
        "description": "Sprint queue",
        "jobs": [{"name": "build", "cmd": "true"}],
    }))

    catalog = discover_catalog(str(tmp_path))
    assert len(catalog) == 1
    assert catalog[0]["experiment"] == "prefix_scale"
    assert catalog[0]["queues"][0]["selector"] == "prefix_scale/sprint"
    assert catalog[0]["scenarios"] == ["demo.json"]


def test_selector_from_path_uses_fixed_convention():
    path = "/home/test/atlas-scenarios/experiments/prefix_scale/queues/sprint.json"
    assert selector_from_path(path, root="/home/test/atlas-scenarios") == "prefix_scale/sprint"


def test_resolve_queue_path_by_selector(tmp_path):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({"jobs": [{"cmd": "true"}]}))

    resolved = resolve_queue_path("prefix_scale/sprint", root=str(tmp_path))
    assert resolved == str(queue_path.resolve())


def test_discover_active_queues_filters_running(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    active_path = exp_jobs_dir / "active.json"
    idle_path = exp_jobs_dir / "idle.json"
    active_path.write_text(json.dumps({"jobs": [{"name": "build", "cmd": "true"}]}))
    idle_path.write_text(json.dumps({"jobs": [{"name": "build", "cmd": "true"}]}))

    save_state(str(active_path), {
        "1": {"status": "running"},
        STATE_META_KEY: {"run_context": {"run_root": "results/demo/active"}},
    })
    save_state(str(idle_path), {
        "1": {"status": "done"},
        STATE_META_KEY: {"run_context": {"run_root": "results/demo/idle"}},
    })

    monkeypatch.setattr("jobs.conventions.screen_exists", lambda _name: False)
    active = discover_active_queues(str(tmp_path))

    assert len(active) == 1
    assert active[0]["selector"] == "prefix_scale/active"
    assert active[0]["counts"]["running"] == 1
    assert active[0]["run_root"] == "results/demo/active"


def test_screen_exists_checks_root_owned_sessions_with_sudo(monkeypatch):
    calls = []

    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(command, capture_output=False, text=False):
        calls.append(command)
        if command == ["screen", "-ls"]:
            return Result("No Sockets found.\n")
        if command == ["sudo", "-n", "screen", "-ls"]:
            return Result("\t1234.demo-abcdef12\t(Detached)\n")
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(jobs_state.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(jobs_state.shutil, "which", lambda tool: "/usr/bin/sudo" if tool == "sudo" else None)
    monkeypatch.setattr(jobs_state.subprocess, "run", fake_run)

    assert screen_exists("demo-abcdef12") is True
    assert calls == [["screen", "-ls"], ["sudo", "-n", "screen", "-ls"]]


def test_resolve_queue_path_prefers_active_when_requested(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "active.json"
    queue_path.write_text(json.dumps({"jobs": [{"name": "build", "cmd": "true"}]}))

    monkeypatch.setattr(
        "jobs.conventions.discover_active_queues",
        lambda root=None: [{"path": str(queue_path.resolve()), "selector": "prefix_scale/active", "counts": {}}],
    )
    monkeypatch.setattr(
        "jobs.conventions.select_active_queue_interactively",
        lambda active: active[0]["path"],
    )

    resolved = resolve_queue_path(None, root=str(tmp_path), prefer_active=True)
    assert resolved == str(queue_path.resolve())


def test_resolve_queue_path_active_only_filters_stale_running(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    stale_path = exp_jobs_dir / "stale.json"
    live_path = exp_jobs_dir / "live.json"
    stale_path.write_text(json.dumps({"jobs": [{"name": "build", "cmd": "true"}]}))
    live_path.write_text(json.dumps({"jobs": [{"name": "build", "cmd": "true"}]}))

    monkeypatch.setattr(
        "jobs.conventions.discover_active_queues",
        lambda root=None: [
            {
                "path": str(stale_path.resolve()),
                "selector": "prefix_scale/stale",
                "counts": {"running": 1, "done": 0, "pending": 0, "failed": 0},
                "has_screen": False,
            },
            {
                "path": str(live_path.resolve()),
                "selector": "prefix_scale/live",
                "counts": {"running": 1, "done": 0, "pending": 0, "failed": 0},
                "has_screen": True,
            },
        ],
    )
    monkeypatch.setattr(
        "jobs.conventions.select_active_queue_interactively",
        lambda active: active[0]["path"],
    )

    resolved = resolve_queue_path(None, root=str(tmp_path), prefer_active=True, active_only=True)
    assert resolved == str(live_path.resolve())


def test_cmd_run_records_queue_bootstrap_failure(tmp_path, monkeypatch, capsys):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({"selector": "prefix_scale/sprint", "jobs": [{"name": "build", "cmd": "true"}]}))

    def explode(*_args, **_kwargs):
        raise RuntimeError("signal hook failed")

    monkeypatch.setattr("jobs.runner.queue_ref", lambda _path: "prefix_scale/sprint")
    monkeypatch.setattr("jobs.runner.signal.signal", explode)

    with pytest.raises(RuntimeError, match="signal hook failed"):
        cmd_run(str(queue_path))

    captured = capsys.readouterr()
    assert "ERROR: queue execution aborted: RuntimeError: signal hook failed" in captured.err

    state = load_state(str(queue_path))
    meta = state[STATE_META_KEY]
    assert meta["queue_error"] == "RuntimeError: signal hook failed"
    assert "queue_error_at" in meta

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        cmd_status(str(queue_path))
    status_output = stdout.getvalue()
    assert "Queue error: RuntimeError: signal hook failed" in status_output


def test_cmd_run_clears_stale_queue_error_on_retry(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({"selector": "prefix_scale/sprint", "jobs": [{"name": "build", "cmd": "true"}]}))

    state = {
        STATE_META_KEY: {
            "selector": "prefix_scale/sprint",
            "queue_error": "RuntimeError: old failure",
            "queue_error_at": "2026-04-03T09:25:50+00:00",
        }
    }
    save_state(str(queue_path), state)

    monkeypatch.setattr("jobs.runner.queue_ref", lambda _path: "prefix_scale/sprint")
    assert cmd_run(str(queue_path), dry=True) == 0

    updated = load_state(str(queue_path))
    meta = updated[STATE_META_KEY]
    assert "queue_error" not in meta
    assert "queue_error_at" not in meta


def test_cmd_run_preserves_interrupt_state_when_signal_arrives_mid_job(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({
        "selector": "prefix_scale/sprint",
        "jobs": [{"name": "build", "cmd": "true"}],
    }))

    handlers = {}

    monkeypatch.setattr("jobs.runner.queue_ref", lambda _path: "prefix_scale/sprint")
    monkeypatch.setattr("jobs.runner.atexit.register", lambda _fn: None)

    def fake_signal(signum, handler):
        handlers[signum] = handler

    def fake_run(*_args, **_kwargs):
        handlers[signal.SIGINT](signal.SIGINT, None)

    monkeypatch.setattr("jobs.runner.signal.signal", fake_signal)
    monkeypatch.setattr("jobs.runner.subprocess.run", fake_run)

    with pytest.raises(SystemExit, match="130"):
        cmd_run(str(queue_path))

    state = load_state(str(queue_path))
    assert state["1"]["status"] == jobs_state.STATE_FAILED
    assert state["1"]["error"] == "interrupted by signal 2"
    assert state["1"]["interrupted"] is True


def test_load_state_retries_on_transient_invalid_json(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({"jobs": [{"name": "build", "cmd": "true"}]}))

    save_state(str(queue_path), {"1": {"status": "running"}})
    path = state_path(str(queue_path))
    real_open = open
    state = {"calls": 0}

    def flaky_open(file, *args, **kwargs):
        if os.path.abspath(file) == os.path.abspath(path) and state["calls"] == 0:
            state["calls"] += 1
            return io.StringIO("")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)

    loaded = load_state(str(queue_path))
    assert loaded["1"]["status"] == "running"


def test_cleanup_stale_running_does_not_overwrite_newer_done_state(tmp_path):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({"jobs": [{"name": "build", "cmd": "true"}]}))

    stale_snapshot = {
        "1": {
            "status": "running",
            "runner_pid": 12345,
            "runner_host": jobs_state.RUNNER_HOST,
            "runner_mode": "direct",
        }
    }
    save_state(str(queue_path), {"1": {"status": "done", "elapsed_s": 2.0}})

    stale = jobs_state.cleanup_stale_running(
        str(queue_path),
        [{"id": 1, "name": "build"}],
        stale_snapshot,
    )

    assert stale == []
    loaded = load_state(str(queue_path))
    assert loaded["1"]["status"] == "done"


def test_cmd_status_watch_refreshes_output(tmp_path):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({
        "selector": "prefix_scale/sprint",
        "jobs": [{"name": "build", "cmd": "true"}],
    }))

    stdout = io.StringIO()
    cmd_status(str(queue_path), watch=True, interval_s=0.01, output=stdout, _max_updates=2)

    status_output = stdout.getvalue()
    assert status_output.count("Queue:    prefix_scale/sprint") == 2
    assert "Refreshing every 0.01s. Press Ctrl-C to stop." in status_output


def test_trim_line_shortens_with_ellipsis():
    assert _trim_line("abcdefgh", 5) == "ab..."
    assert _trim_line("abc", 5) == "abc"
    assert _trim_line("abc", 2) == "ab"


def test_progress_bar_scales_with_completion():
    assert _progress_bar(0, 4, width=8) == "--------"
    assert _progress_bar(2, 4, width=8) == "####----"
    assert _progress_bar(4, 4, width=8) == "########"


def test_cmd_list_running_only_prints_active(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "jobs.runner.discover_active_queues",
        lambda: [{
            "selector": "prefix_scale/sprint",
            "topology": "sprint",
            "mode": "one_phase",
            "counts": {"running": 1, "done": 3, "pending": 20, "failed": 0},
            "run_root": "experiments/prefix_scale/results/sprint/latest",
        }],
    )
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        cmd_list(running_only=True)
    output = stdout.getvalue()
    assert "Running queues" in output
    assert "prefix_scale/sprint" in output
    assert "running=1 done=3 pending=20 failed=0" in output


def test_select_queue_interactively_shows_short_names_and_description(monkeypatch):
    catalog = [
        {
            "experiment": "prefix_scale",
            "path": "/tmp/experiments/prefix_scale",
            "scenarios": ["demo.json"],
            "queues": [
                {
                    "path": "/tmp/experiments/prefix_scale/queues/3x3_prefix_churn_compare_1prefix_test.json",
                    "selector": "prefix_scale/3x3_prefix_churn_compare_1prefix_test",
                    "name": "3x3_prefix_churn_compare_1prefix_test",
                    "description": "3x3 grid prefix-churn comparison test run for sim and emu with one prefix, comparing baseline vs one_phase",
                    "topology": "grid",
                    "mode": "mixed",
                },
                {
                    "path": "/tmp/experiments/prefix_scale/queues/3x3_onephase_1prefix_test.json",
                    "selector": "prefix_scale/3x3_onephase_1prefix_test",
                    "name": "3x3_onephase_1prefix_test",
                    "description": "3x3 grid one-phase single-prefix test run for sim and emu",
                    "topology": "grid",
                    "mode": "one_phase",
                },
            ],
        }
    ]

    answers = iter(["1", "2"])
    monkeypatch.setattr("jobs.conventions.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    stdout = io.StringIO()
    with redirect_stdout(stdout):
        selected = select_queue_interactively(catalog)

    output = stdout.getvalue()
    assert selected == "/tmp/experiments/prefix_scale/queues/3x3_onephase_1prefix_test.json"
    assert "prefix_scale/3x3_onephase_1prefix_test" not in output
    assert "1. 3x3_prefix_churn_compare_1prefix_test" in output
    assert "2. 3x3_onephase_1prefix_test" in output
    assert "3x3 grid prefix-churn comparison test run for sim and emu with one prefix, comparing baseline vs one_phase" in output
    assert "topology=grid  mode=one_phase" in output


def test_interactive_status_can_enable_watch(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({
        "selector": "prefix_scale/sprint",
        "jobs": [{"name": "build", "cmd": "true"}],
    }))

    captured = {}

    monkeypatch.setattr(jobs_cli, "select_command_interactively", lambda: "status")
    monkeypatch.setattr(jobs_cli, "resolve_queue_path", lambda _queue, prefer_active=False, active_only=False: str(queue_path))
    monkeypatch.setattr(jobs_cli, "selector_from_path", lambda _path: "prefix_scale/sprint")
    monkeypatch.setattr(
        jobs_cli,
        "cmd_status",
        lambda job_path, watch=False, interval_s=1.0: captured.update({
            "job_path": job_path,
            "watch": watch,
            "interval_s": interval_s,
        }),
    )

    assert jobs_cli.main([]) == 0
    assert captured == {
        "job_path": str(queue_path),
        "watch": True,
        "interval_s": 1.0,
    }


def test_interactive_status_prefers_active_queue(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({
        "selector": "prefix_scale/sprint",
        "jobs": [{"name": "build", "cmd": "true"}],
    }))

    captured = {}
    monkeypatch.setattr(jobs_cli, "select_command_interactively", lambda: "status")
    monkeypatch.setattr(
        jobs_cli,
        "resolve_queue_path",
        lambda _queue, prefer_active=False, active_only=False: captured.update({
            "prefer_active": prefer_active,
            "active_only": active_only,
        }) or str(queue_path),
    )
    monkeypatch.setattr(jobs_cli, "selector_from_path", lambda _path: "prefix_scale/sprint")
    monkeypatch.setattr(
        jobs_cli,
        "cmd_status",
        lambda job_path, watch=False, interval_s=1.0: captured.update({"job_path": job_path, "watch": watch}),
    )

    assert jobs_cli.main([]) == 0
    assert captured["prefer_active"] is True
    assert captured["job_path"] == str(queue_path)
    assert captured["watch"] is True


def test_interactive_start_defaults_to_watching_status(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({
        "selector": "prefix_scale/sprint",
        "jobs": [{"name": "build", "cmd": "true"}],
    }))

    captured = {}
    monkeypatch.setattr(jobs_cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(jobs_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(jobs_cli, "select_command_interactively", lambda: "start")
    monkeypatch.setattr(jobs_cli, "resolve_queue_path", lambda _queue, prefer_active=False, active_only=False: str(queue_path))
    monkeypatch.setattr(jobs_cli, "selector_from_path", lambda _path: "prefix_scale/sprint")
    monkeypatch.setattr(
        jobs_cli,
        "cmd_start",
        lambda job_path, dry=False, fresh=False: captured.update({
            "job_path": job_path,
            "dry": dry,
            "fresh": fresh,
        }),
    )
    monkeypatch.setattr(
        jobs_cli,
        "cmd_status",
        lambda job_path, watch=False, interval_s=1.0: captured.update({
            "status_job_path": job_path,
            "watch": watch,
            "interval_s": interval_s,
        }),
    )

    assert jobs_cli.main([]) == 0
    assert captured["job_path"] == str(queue_path)
    assert captured["fresh"] is True
    assert captured["status_job_path"] == str(queue_path)
    assert captured["watch"] is True
    assert captured["interval_s"] == 1.0


def test_interactive_stop_prefers_active_queue_only(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({
        "selector": "prefix_scale/sprint",
        "jobs": [{"name": "build", "cmd": "true"}],
    }))

    captured = {}
    monkeypatch.setattr(jobs_cli, "select_command_interactively", lambda: "stop")
    monkeypatch.setattr(
        jobs_cli,
        "resolve_queue_path",
        lambda _queue, prefer_active=False, active_only=False: captured.update({
            "prefer_active": prefer_active,
            "active_only": active_only,
        }) or str(queue_path),
    )
    monkeypatch.setattr(jobs_cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(jobs_cli, "selector_from_path", lambda _path: "prefix_scale/sprint")
    monkeypatch.setattr(jobs_cli, "cmd_stop", lambda job_path: captured.update({"job_path": job_path}))

    assert jobs_cli.main([]) == 0
    assert captured["prefer_active"] is True
    assert captured["active_only"] is True
    assert captured["job_path"] == str(queue_path)


def test_interactive_ctrl_c_exits_quietly(monkeypatch, capsys):
    monkeypatch.setattr(jobs_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(KeyboardInterrupt()))

    assert jobs_cli.main([]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""


def test_resolve_queue_path_active_only_without_running_raises_cancel(tmp_path):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({"jobs": [{"name": "build", "cmd": "true"}]}))

    stdin = sys.stdin
    old_isatty = stdin.isatty
    stdin.isatty = lambda: True
    with pytest.raises(InteractiveCancel):
        resolve_queue_path(None, root=str(tmp_path), prefer_active=True, active_only=True)
    stdin.isatty = old_isatty


def test_start_command_line_watch_status_flag_skips_prompt_and_watches(tmp_path, monkeypatch):
    exp_jobs_dir = tmp_path / "experiments" / "prefix_scale" / "queues"
    exp_jobs_dir.mkdir(parents=True)
    queue_path = exp_jobs_dir / "sprint.json"
    queue_path.write_text(json.dumps({
        "selector": "prefix_scale/sprint",
        "jobs": [{"name": "build", "cmd": "true"}],
    }))

    captured = {}
    monkeypatch.setattr(jobs_cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(jobs_cli, "resolve_queue_path", lambda _queue, prefer_active=False, active_only=False: str(queue_path))
    monkeypatch.setattr(
        jobs_cli,
        "cmd_start",
        lambda job_path, dry=False, fresh=False: captured.update({
            "job_path": job_path,
            "dry": dry,
            "fresh": fresh,
        }),
    )
    monkeypatch.setattr(
        jobs_cli,
        "cmd_status",
        lambda job_path, watch=False, interval_s=1.0: captured.update({
            "status_job_path": job_path,
            "watch": watch,
            "interval_s": interval_s,
        }),
    )
    monkeypatch.setattr(
        jobs_cli,
        "prompt_yes_no",
        lambda prompt, default=False: (_ for _ in ()).throw(AssertionError("prompt should not be called")),
    )

    assert jobs_cli.main(["start", "prefix_scale/sprint", "--watch-status"]) == 0
    assert captured["job_path"] == str(queue_path)
    assert captured["status_job_path"] == str(queue_path)
    assert captured["watch"] is True
