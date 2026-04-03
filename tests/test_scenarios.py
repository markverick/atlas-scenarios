import os

import pytest

from jobs.conventions import discover_catalog, queue_stem, selector_from_path
from jobs.spec import build_run_context, load_job_spec, load_jobs
from lib.config import load_config


REPO_DIR = os.path.join(os.path.dirname(__file__), "..")
PREFIX_SCALE_SCENARIO_DIR = os.path.join(REPO_DIR, "experiments", "prefix_scale", "scenarios")
SCENARIO_FILES = sorted(
    os.path.join(PREFIX_SCALE_SCENARIO_DIR, name)
    for name in os.listdir(PREFIX_SCALE_SCENARIO_DIR)
    if name.endswith(".json")
)


@pytest.mark.parametrize("path", SCENARIO_FILES,
                         ids=[os.path.relpath(p, REPO_DIR) for p in SCENARIO_FILES])
def test_scenario_loads(path):
    cfg = load_config(path)
    assert isinstance(cfg, dict)
    assert "topology" in cfg
    assert cfg["trials"] >= 1
    assert cfg["window_s"] > 0


QUEUE_FILES = sorted(
    queue["path"]
    for experiment in discover_catalog(REPO_DIR)
    for queue in experiment["queues"]
)


@pytest.mark.parametrize("path", QUEUE_FILES,
                         ids=[os.path.relpath(p, REPO_DIR) for p in QUEUE_FILES])
def test_queue_file_loads(path):
    spec = load_job_spec(path)
    state = {}
    selector = spec.get("selector") or selector_from_path(path, root=REPO_DIR)
    context = build_run_context(path, spec, state, selector=selector, stem=queue_stem(path))
    jobs = load_jobs(path, context)
    assert len(jobs) > 0
    for j in jobs:
        assert "cmd" in j
        assert "name" in j
        assert "id" in j
        # No un-expanded placeholders
        assert "{" not in j["name"], f"Un-expanded placeholder in: {j['name']}"
        assert "{" not in j["cmd"], f"Un-expanded placeholder in: {j['cmd']}"
