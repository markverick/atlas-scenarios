"""Tests for lib/topology.py helpers."""
import os
import pytest

from lib.topology import (conf_stats, core_edge_links, core_edge_roles,
                          core_edge_stats, generate_ndnsim_core_edge_topo,
                          generate_ndnsim_rocketfuel_sample_4755_topo,
                          grid_links, grid_nodes, grid_stats,
                          parse_rocketfuel_cch_maps,
                          rocketfuel_sample_4755_path,
                          rocketfuel_sample_4755_roles,
                          rocketfuel_sample_4755_stats)


def test_grid_stats_2x2():
    nodes, links = grid_stats(2)
    assert nodes == 4
    assert links == 4


def test_grid_stats_3x3():
    nodes, links = grid_stats(3)
    assert nodes == 9
    assert links == 12


def test_grid_links_2x2():
    links = grid_links(2)
    assert len(links) == 4
    # Each link is a (src, dst) tuple
    for src, dst in links:
        assert src.startswith("n")
        assert dst.startswith("n")


def test_grid_nodes_3x3():
    nodes = grid_nodes(3)
    assert len(nodes) == 9
    assert "n0_0" in nodes
    assert "n2_2" in nodes


def test_conf_stats_sprint():
    conf = os.path.join(os.path.dirname(__file__), "..",
                        "deps", "mini-ndn", "topologies", "minindn.sprint.conf")
    if not os.path.isfile(conf):
        pytest.skip("Sprint conf not available (deps not installed)")
    nodes, links = conf_stats(conf)
    assert nodes == 52
    assert links == 84


def test_core_edge_stats():
    nodes, links = core_edge_stats()
    assert nodes == 10
    assert links == 12


def test_core_edge_roles_and_links():
    roles = core_edge_roles()
    assert roles["core"] == ["c0", "c1", "c2", "c3", "c4", "c5"]
    assert roles["edge"] == ["e0", "e1", "e2", "e3"]

    links = core_edge_links()
    assert ("e0", "c0") in links
    assert ("c0", "c3") in links


def test_generate_ndnsim_core_edge_topo(tmp_path):
    topo_path = tmp_path / "core-edge.txt"
    content = generate_ndnsim_core_edge_topo(path=str(topo_path))
    assert topo_path.read_text() == content
    assert "c0  NA" in content
    assert "e3  c5  10Mbps  1  10ms  100" in content


def test_parse_rocketfuel_cch_maps_drops_isolated_r0_nodes():
    maps_path = rocketfuel_sample_4755_path()
    if not os.path.isfile(maps_path):
        pytest.skip("Rocketfuel sample not available (deps not installed)")

    graph = parse_rocketfuel_cch_maps(maps_path)

    assert [node["uid"] for node in graph["nodes"] if not node["bb"]] == ["462"]
    assert "464" not in {node["uid"] for node in graph["nodes"]}
    assert len(graph["links"]) == 12


def test_generate_ndnsim_rocketfuel_sample_topo(tmp_path):
    maps_path = rocketfuel_sample_4755_path()
    if not os.path.isfile(maps_path):
        pytest.skip("Rocketfuel sample not available (deps not installed)")

    topo_path = tmp_path / "rocketfuel-4755.txt"
    content = generate_ndnsim_rocketfuel_sample_4755_topo(
        maps_path=maps_path,
        path=str(topo_path),
    )
    roles = rocketfuel_sample_4755_roles(maps_path)
    nodes, links = rocketfuel_sample_4755_stats(maps_path)

    assert topo_path.read_text() == content
    assert roles["edge"] == ["rf462"]
    assert nodes == 11
    assert links == 12
    assert "rf462  rf463  10Mbps  1  10ms  100" in content
    assert "rf464" not in content
