"""Tests for lib/churn_common.py -- event generation and helpers."""
from lib.churn_common import (
    build_churn_events,
    build_prefix_scaling_events,
    build_link_scaling_events,
    resolve_link_scaling_sweep,
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
    assert types == {"neighbor_down", "neighbor_up"}


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
        include_target_prefix_churn=False,
    )
    types = {e["type"] for e in events}
    assert types == {"neighbor_down", "neighbor_up"}


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


def test_build_prefix_scaling_events():
    events = build_prefix_scaling_events(
        3, 10.0,
        churn_node="n0",
        window_end=60.0,
        seed=42,
        prefix_event_rate_per_prefix=0.1,
        prefix_mean_time_to_recover_s=3.0,
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
        mean_time_to_fail_s=5.0,
        link_event_mode="neighbor",
    )
    assert len(events) >= 6
    assert sum(1 for e in events if e["type"] == "neighbor_down") >= 3
    assert sum(1 for e in events if e["type"] == "neighbor_up") >= 3
    assert all(30.0 <= e["time"] <= 60.0 for e in events)
    per_link = {}
    for event in events:
        per_link.setdefault((event["src"], event["dst"]), []).append(event)
    assert len(per_link) == 3
    assert all(len(link_events) >= 2 for link_events in per_link.values())


def test_build_link_scaling_events_stops_when_window_too_short():
    events = build_link_scaling_events(
        2,
        30.0,
        all_links=[("a", "b"), ("b", "c")],
        window_end=37.0,
        seed=42,
        mean_time_to_recover_s=5.0,
        mean_time_to_fail_s=5.0,
        link_event_mode="neighbor",
    )
    assert len(events) >= 2
    assert all(30.0 <= event["time"] <= 37.0 for event in events)


def test_build_link_scaling_events_pareto_independent_per_link():
    events = build_link_scaling_events(
        2,
        30.0,
        all_links=[("a", "b"), ("b", "c")],
        window_end=60.0,
        seed=42,
        mean_time_to_recover_s=5.0,
        mean_time_to_fail_s=5.0,
        distribution="pareto",
        pareto_alpha=2.0,
        link_event_mode="neighbor",
    )
    down_times = {}
    for event in events:
        if event["type"] != "neighbor_down":
            continue
        down_times.setdefault((event["src"], event["dst"]), []).append(event["time"])
    assert len(down_times) == 2
    assert down_times[("a", "b")] != down_times[("b", "c")]


def test_build_link_scaling_events_invalid_pareto_alpha():
    try:
        build_link_scaling_events(
            1,
            30.0,
            all_links=[("a", "b")],
            window_end=60.0,
            distribution="pareto",
            pareto_alpha=1.0,
        )
    except ValueError as exc:
        assert "pareto_alpha" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid pareto_alpha")


def test_resolve_link_scaling_sweep_all_links_rate_pairs():
    link_counts, rate_pairs = resolve_link_scaling_sweep(
        {
            "link_fail_all_links": True,
            "link_mean_time_to_fail_s_values": [20.0, 10.0, 5.0],
            "link_mean_time_to_recover_s_values": [20.0, 10.0, 5.0],
        },
        total_links=12,
    )
    assert link_counts == [12]
    assert rate_pairs == [(20.0, 20.0), (10.0, 10.0), (5.0, 5.0)]


def test_topo_id_grid():
    cfg = {"topology": "grid", "grids": [3]}
    assert topo_id(cfg) == "3x3"


def test_topo_id_sprint():
    cfg = {"topology": "sprint", "grids": []}
    assert topo_id(cfg) == "sprint"


def test_default_out_dir():
    cfg = {"topology": "grid", "grids": [3],
           "prefix_counts": [], "trials": 1,
           "num_prefixes": 5}
    d = default_out_dir(cfg, "sim")
    assert "sim_churn" in d


def test_default_out_dir_neighbor_mode():
    cfg = {"topology": "grid", "grids": [3], "link_event_mode": "neighbor"}
    d = default_out_dir(cfg, "sim")
    assert d.endswith("sim_churn_3x3")
