"""Tests for modular jobs runner helpers."""
import io
import json
import os
import sys
from contextlib import redirect_stdout

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from jobs.conventions import discover_active_queues, discover_catalog, resolve_queue_path, selector_from_path
from jobs import cli as jobs_cli
from jobs.runner import _progress_bar, _trim_line, cmd_list, cmd_run, cmd_status
from jobs.spec import expand_matrix, load_job_spec, load_jobs
from jobs.state import STATE_META_KEY, load_state, save_state


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
        "mode": "two_step",
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
            "mode": "two_step",
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
    monkeypatch.setattr(jobs_cli, "resolve_queue_path", lambda _queue, prefer_active=False: str(queue_path))
    monkeypatch.setattr(jobs_cli, "selector_from_path", lambda _path: "prefix_scale/sprint")
    monkeypatch.setattr(jobs_cli, "prompt_yes_no", lambda prompt, default=False: True)
    monkeypatch.setattr(jobs_cli, "prompt_float", lambda prompt, default: 2.5)
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
        "interval_s": 2.5,
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
        lambda _queue, prefer_active=False: captured.update({"prefer_active": prefer_active}) or str(queue_path),
    )
    monkeypatch.setattr(jobs_cli, "selector_from_path", lambda _path: "prefix_scale/sprint")
    monkeypatch.setattr(jobs_cli, "prompt_yes_no", lambda prompt, default=False: False)
    monkeypatch.setattr(
        jobs_cli,
        "cmd_status",
        lambda job_path, watch=False, interval_s=1.0: captured.update({"job_path": job_path, "watch": watch}),
    )

    assert jobs_cli.main([]) == 0
    assert captured["prefer_active"] is True
    assert captured["job_path"] == str(queue_path)
    assert captured["watch"] is False
