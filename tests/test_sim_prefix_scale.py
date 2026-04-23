import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sim.prefix_scale import parse_table_trace, summarize_role_table_metrics


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