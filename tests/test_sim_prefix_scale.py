import os
import sys

from types import SimpleNamespace
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import pytest


from sim.prefix_scale import (cli_role_dv_overrides, default_prefix_counts,
                              effective_role_dv_configs, parse_dv_config_json,
                              parse_table_trace, summarize_role_table_metrics)


def test_parse_table_trace(tmp_path):
    trace = tmp_path / "tables.csv"
    trace.write_text(
        "node,role,table_category,table_name,entry_count\n"
        "c0,core,common,forwarder_rib,8\n"
        "e0,edge,onephase,dv_prefix_table,2\n"
    )

    rows = parse_table_trace(trace)

    assert rows == [
        {
            "node": "c0",
            "role": "core",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "entry_count": 8,
        },
        {
            "node": "e0",
            "role": "edge",
            "table_category": "onephase",
            "table_name": "dv_prefix_table",
            "entry_count": 2,
        },
    ]


def test_summarize_role_table_metrics():
    rows = [
        {
            "node": "c0",
            "role": "core",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "entry_count": 10,
        },
        {
            "node": "c1",
            "role": "core",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "entry_count": 14,
        },
        {
            "node": "e0",
            "role": "edge",
            "table_category": "twophase",
            "table_name": "forwarder_pet",
            "entry_count": 3,
        },
    ]

    summary = summarize_role_table_metrics(rows)

    assert summary == [
        {
            "role": "core",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "node_count": 2,
            "total_entries": 24,
            "avg_entries": 12.0,
            "max_entries": 14,
        },
        {
            "role": "edge",
            "table_category": "twophase",
            "table_name": "forwarder_pet",
            "node_count": 1,
            "total_entries": 3,
            "avg_entries": 3.0,
            "max_entries": 3,
        },
    ]


def test_default_prefix_counts_for_rocketfuel_sample():
    assert default_prefix_counts("rocketfuel_4755") == [0, 100, 200, 300, 400, 500]


def test_default_prefix_counts_for_large_rocketfuel_topology():
    assert default_prefix_counts("rocketfuel_2914") == [0, 100, 200, 300, 400, 500]


def test_parse_dv_config_json_requires_object():
    with pytest.raises(ValueError, match="must decode to a JSON object"):
        parse_dv_config_json("[]", field_name="--core-dv-config-json")


def test_cli_role_dv_overrides_applies_core_prefix_replication_flag():
    args = SimpleNamespace(
        core_dv_config_json='{"router_dead_interval":6000}',
        edge_dv_config_json="",
        core_disable_prefix_egress_replication=True,
        edge_disable_prefix_egress_replication=False,
    )

    core_dv_config, edge_dv_config = cli_role_dv_overrides(args)

    assert core_dv_config == {
        "router_dead_interval": 6000,
        "prefix_egre_state_replicate": False,
    }
    assert edge_dv_config is None


def test_effective_role_dv_configs_merges_shared_and_role_specific_values():
    shared_dv_config, core_dv_config, edge_dv_config = effective_role_dv_configs(
        {"advertise_interval": 2000},
        {"prefix_egre_state_replicate": False},
        None,
    )

    assert shared_dv_config is None
    assert core_dv_config == {
        "advertise_interval": 2000,
        "prefix_egre_state_replicate": False,
    }
    assert edge_dv_config == {"advertise_interval": 2000}