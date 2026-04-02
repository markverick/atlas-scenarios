"""Tests for jobs.py -- matrix expansion and job loading."""
import json
import os
import pytest

# Import the internal helpers directly
import importlib
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import jobs as jobs_mod


def test_expand_matrix_no_matrix():
    job = {"name": "simple", "cmd": "echo hello"}
    result = jobs_mod._expand_matrix(job)
    assert len(result) == 1
    assert result[0]["cmd"] == "echo hello"


def test_expand_matrix_single_key():
    job = {
        "name": "run {mode}",
        "cmd": "test --mode {mode}",
        "matrix": {"mode": ["a", "b", "c"]},
    }
    result = jobs_mod._expand_matrix(job)
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
    result = jobs_mod._expand_matrix(job)
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
    result = jobs_mod._expand_matrix(job)
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

    jobs = jobs_mod._load_jobs(path)
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
    jobs = jobs_mod._load_jobs(path)
    assert len(jobs) == 1
