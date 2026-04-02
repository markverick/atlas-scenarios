"""Tests for lib/topology.py -- grid helpers and conf parsing."""
import os
import pytest

from lib.topology import grid_stats, grid_links, grid_nodes, conf_stats


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
