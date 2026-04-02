"""Validate all scenario JSON files load without errors."""
import glob
import os
import pytest

from lib.config import load_config


SCENARIO_DIR = os.path.join(os.path.dirname(__file__), "..", "scenarios")

SCENARIO_FILES = sorted(glob.glob(os.path.join(SCENARIO_DIR, "*.json")))


# Some scenarios (e.g. multihop.json) use a non-standard inline topology;
# load_config expects topology to be a string.  Filter those out.
_STANDARD_SCENARIOS = [p for p in SCENARIO_FILES
                       if os.path.basename(p) not in ("multihop.json",)]


@pytest.mark.parametrize("path", _STANDARD_SCENARIOS,
                         ids=[os.path.basename(p) for p in _STANDARD_SCENARIOS])
def test_scenario_loads(path):
    cfg = load_config(path)
    assert isinstance(cfg, dict)
    assert "topology" in cfg
    assert cfg["trials"] >= 1
    assert cfg["window_s"] > 0


JOB_DIR = os.path.join(os.path.dirname(__file__), "..")
JOB_FILES = sorted(f for f in glob.glob(os.path.join(JOB_DIR, "jobs*.json"))
                   if not f.endswith(".state.json"))


@pytest.mark.parametrize("path", JOB_FILES,
                         ids=[os.path.basename(p) for p in JOB_FILES])
def test_job_file_loads(path):
    import sys
    sys.path.insert(0, JOB_DIR)
    import jobs as jobs_mod
    jobs = jobs_mod._load_jobs(path)
    assert len(jobs) > 0
    for j in jobs:
        assert "cmd" in j
        assert "name" in j
        assert "id" in j
        # No un-expanded placeholders
        assert "{" not in j["name"], f"Un-expanded placeholder in: {j['name']}"
        assert "{" not in j["cmd"], f"Un-expanded placeholder in: {j['cmd']}"
