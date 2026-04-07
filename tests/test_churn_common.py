"""Tests for lib/churn_common.py -- event generation and helpers."""
from lib.churn_common import (
    build_churn_events,
    build_random_churn_events,
    build_prefix_scaling_events,
    build_link_scaling_events,
    grid_churn_targets,
    topo_id,
    default_out_dir,
)


def test_grid_churn_targets():
    src, dst, node = grid_churn_targets(3)
    assert src == "n0_0"
    assert dst == "n0_1"
    assert node == "n0_0"


def test_grid_churn_targets_too_small():
    src, dst, node = grid_churn_targets(1)
    assert src is None


def test_build_churn_events_no_prefixes():
    events = build_churn_events(0, 30.0,
                                link_src="a", link_dst="b", churn_node="a")
    assert len(events) == 2
    types = {e["type"] for e in events}
    assert types == {"link_down", "link_up"}


def test_build_churn_events_with_prefixes():
    events = build_churn_events(5, 30.0,
                                link_src="a", link_dst="b", churn_node="a")
    assert len(events) == 4
    types = [e["type"] for e in events]
    assert "prefix_withdraw" in types
    assert "prefix_announce" in types


def test_build_churn_events_without_prefix_churn():
    events = build_churn_events(
        5,
        30.0,
        link_src="a",
        link_dst="b",
        churn_node="a",
        include_prefix_churn=False,
    )
    types = {e["type"] for e in events}
    assert types == {"link_down", "link_up"}


def test_build_churn_events_timing():
    events = build_churn_events(1, 100.0,
                                link_src="x", link_dst="y", churn_node="x")
    times = sorted(e["time"] for e in events)
    assert times[0] == 100.1   # link_down
    assert times[-1] == 107.0  # prefix_announce
    # All events after phase2_start
    assert all(t >= 100.0 for t in times)


def test_build_churn_events_neighbor_mode():
    events = build_churn_events(
        1,
        30.0,
        link_src="a",
        link_dst="b",
        churn_node="a",
        link_event_mode="neighbor",
    )
    types = [e["type"] for e in events]
    assert "neighbor_down" in types
    assert "neighbor_up" in types
    assert "link_down" not in types
    assert "link_up" not in types


def test_build_random_churn_deterministic():
    e1 = build_random_churn_events(
        5, 30.0, link_src="a", link_dst="b", churn_node="a",
        window_end=60.0, seed=42, num_cycles=3)
    e2 = build_random_churn_events(
        5, 30.0, link_src="a", link_dst="b", churn_node="a",
        window_end=60.0, seed=42, num_cycles=3)
    assert len(e1) == len(e2)
    for a, b in zip(e1, e2):
        assert a["time"] == b["time"]
        assert a["type"] == b["type"]


def test_build_random_churn_without_prefix_churn():
    events = build_random_churn_events(
        5, 30.0, link_src="a", link_dst="b", churn_node="a",
        window_end=60.0, seed=42, num_cycles=2, include_prefix_churn=False)
    assert {e["type"] for e in events} <= {"link_down", "link_up"}


def test_build_random_churn_different_seeds():
    e1 = build_random_churn_events(
        5, 30.0, link_src="a", link_dst="b", churn_node="a",
        window_end=60.0, seed=1)
    e2 = build_random_churn_events(
        5, 30.0, link_src="a", link_dst="b", churn_node="a",
        window_end=60.0, seed=2)
    # Different seeds should (almost certainly) produce different events
    times1 = [e["time"] for e in e1]
    times2 = [e["time"] for e in e2]
    assert times1 != times2


def test_build_prefix_scaling_events():
    events = build_prefix_scaling_events(
        3, 10.0,
        churn_node="n0",
        window_end=60.0,
        seed=42,
        per_prefix_rate=0.1,
        recovery_delay=3.0,
    )
    assert len(events) > 0
    types = {e["type"] for e in events}
    assert types <= {"prefix_withdraw", "prefix_announce"}
    # All events should be timed in [10, 60]
    for e in events:
        assert 10.0 <= e["time"] <= 60.0


def test_build_link_scaling_events_count_and_types():
    events = build_link_scaling_events(
        3,
        30.0,
        all_links=[("a", "b"), ("b", "c"), ("c", "d"), ("d", "e")],
        window_end=60.0,
        seed=42,
        link_event_mode="neighbor",
    )
    assert len(events) == 6
    assert sum(1 for e in events if e["type"] == "neighbor_down") == 3
    assert sum(1 for e in events if e["type"] == "neighbor_up") == 3
    assert all(30.0 <= e["time"] <= 60.0 for e in events)


def test_topo_id_grid():
    cfg = {"topology": "grid", "grids": [3]}
    assert topo_id(cfg) == "3x3"


def test_topo_id_sprint():
    cfg = {"topology": "sprint", "grids": []}
    assert topo_id(cfg) == "sprint"


def test_default_out_dir():
    cfg = {"topology": "grid", "grids": [3],
           "churn_mode": "fixed", "prefix_counts": [], "trials": 1,
           "num_prefixes": 5}
    d = default_out_dir(cfg, "sim")
    assert "sim_churn" in d


def test_default_out_dir_neighbor_mode():
    cfg = {"topology": "grid", "grids": [3], "link_event_mode": "neighbor"}
    d = default_out_dir(cfg, "sim")
    assert d.endswith("sim_churn_neighbor_3x3")
