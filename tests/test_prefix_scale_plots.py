import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from experiments.prefix_scale.plots.prefix_scale_cli import main
from experiments.prefix_scale.plots.prefix_scale_plots import (
    _aggregate_avg_entries_by_prefix_and_table,
    _aggregate_total_entries_by_prefix_and_table,
)


RUNS_CSV = (
    "phase,trial,prefix_count,num_nodes,num_links,router_reachability_s,control_packets,control_bytes,total_packets,total_bytes\n"
    "{phase},1,0,10,12,0.205,1000,200000,1000,200000\n"
    "{phase},1,1,10,12,0.205,1100,210000,1100,210000\n"
)


ROLE_SUMMARY_HEADER = (
    "phase,trial,prefix_count,role,table_category,table_name,node_count,total_entries,avg_entries,max_entries\n"
)


def _runs_csv(phase, num_nodes=10, num_links=12, prefix_counts=(0, 1)):
    rows = [
        "phase,trial,prefix_count,num_nodes,num_links,router_reachability_s,control_packets,control_bytes,total_packets,total_bytes"
    ]
    for index, prefix_count in enumerate(prefix_counts):
        rows.append(
            f"{phase},1,{prefix_count},{num_nodes},{num_links},0.205,{1000 + 100 * index},{200000 + 10000 * index},{1000 + 100 * index},{200000 + 10000 * index}"
        )
    return "\n".join(rows) + "\n"


ONEPHASE_ROLE_ROWS = (
    "onephase,1,0,core,common,forwarder_rib,6,120,20.0,20\n"
    "onephase,1,1,core,common,forwarder_rib,6,126,21.0,21\n"
    "onephase,1,0,core,common,forwarder_fib,6,180,30.0,30\n"
    "onephase,1,1,core,common,forwarder_fib,6,192,32.0,32\n"
    "onephase,1,0,core,onephase,dv_prefix_table,6,0,0.0,0\n"
    "onephase,1,1,core,onephase,dv_prefix_table,6,6,1.0,1\n"
    "onephase,1,0,edge,common,forwarder_rib,4,72,18.0,18\n"
    "onephase,1,1,edge,common,forwarder_rib,4,76,19.0,19\n"
    "onephase,1,0,edge,common,forwarder_fib,4,120,30.0,30\n"
    "onephase,1,1,edge,common,forwarder_fib,4,128,32.0,32\n"
    "onephase,1,0,edge,onephase,dv_prefix_table,4,0,0.0,0\n"
    "onephase,1,1,edge,onephase,dv_prefix_table,4,4,1.0,1\n"
)


TWOPHASE_ROLE_ROWS = (
    "twophase,1,0,core,twophase,forwarder_pet,6,108,18.0,18\n"
    "twophase,1,1,core,twophase,forwarder_pet,6,114,19.0,19\n"
    "twophase,1,0,core,twophase,dv_prefix_egress_state,6,0,0.0,0\n"
    "twophase,1,1,core,twophase,dv_prefix_egress_state,6,6,1.0,1\n"
    "twophase,1,0,edge,twophase,forwarder_pet,4,64,16.0,16\n"
    "twophase,1,1,edge,twophase,forwarder_pet,4,68,17.0,17\n"
    "twophase,1,0,edge,twophase,dv_prefix_egress_state,4,0,0.0,0\n"
    "twophase,1,1,edge,twophase,dv_prefix_egress_state,4,4,1.0,1\n"
)


LINK_TRACE_HEADER = (
    "Time,DvAdvert_Pkts,DvAdvert_Bytes,PrefixSync_Pkts,PrefixSync_Bytes,Mgmt_Pkts,Mgmt_Bytes,"
    "UserInterest_Pkts,UserInterest_Bytes,UserData_Pkts,UserData_Bytes,Other_Pkts,Other_Bytes\n"
)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_core_edge_plot_cli_generates_plots(tmp_path):
    data_dir = tmp_path / "core_edge"
    onephase_dir = data_dir / "onephase"
    twophase_dir = data_dir / "twophase"

    _write(onephase_dir / "runs.csv", _runs_csv("onephase"))
    _write(twophase_dir / "runs.csv", _runs_csv("twophase"))
    _write(onephase_dir / "role_table_summary.csv", ROLE_SUMMARY_HEADER + ONEPHASE_ROLE_ROWS)
    _write(twophase_dir / "role_table_summary.csv", ROLE_SUMMARY_HEADER + TWOPHASE_ROLE_ROWS)
    _write(
        onephase_dir / "link-trace-onephase-p0-t1.csv",
        LINK_TRACE_HEADER + "0.05,100,10000,40,4000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        onephase_dir / "link-trace-onephase-p1-t1.csv",
        LINK_TRACE_HEADER + "0.05,110,11000,50,5000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        twophase_dir / "link-trace-twophase-p0-t1.csv",
        LINK_TRACE_HEADER + "0.05,120,12000,70,7000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        twophase_dir / "link-trace-twophase-p1-t1.csv",
        LINK_TRACE_HEADER + "0.05,130,13000,80,8000,0,0,0,0,0,0,0,0\n",
    )

    assert main(["--data", str(data_dir)]) == 0

    plot_dir = data_dir / "plots"
    assert (plot_dir / "core_edge_topology.png").exists()
    assert (plot_dir / "core_edge_run_comparison.png").exists()
    assert (plot_dir / "core_edge_control_breakdown.png").exists()
    assert (plot_dir / "core_edge_prefix_state_by_role.png").exists()
    assert (plot_dir / "core_edge_forwarding_delta_by_role.png").exists()
    assert (plot_dir / "core_edge_table_average_by_role.png").exists()
    assert (plot_dir / "core_edge_table_average_by_role_reduced.png").exists()
    assert (plot_dir / "core_edge_table_stack_comparison.png").exists()
    assert (plot_dir / "core_edge_table_stack_comparison_reduced.png").exists()

    summary_path = data_dir / "summary.md"
    assert summary_path.exists()
    summary_text = summary_path.read_text()
    assert "# Core/Edge Prefix-Scale Summary" in summary_text
    assert "plots/core_edge_topology.png" in summary_text
    assert "plots/core_edge_run_comparison.png" in summary_text
    assert "plots/core_edge_table_average_by_role.png" in summary_text
    assert "plots/core_edge_table_average_by_role_reduced.png" in summary_text
    assert "plots/core_edge_table_stack_comparison.png" in summary_text
    assert "plots/core_edge_table_stack_comparison_reduced.png" in summary_text
    assert "Prefix-to-router mappings by role" in summary_text
    assert "network-wide prefix-to-router mappings" in summary_text
    assert "local forwarding state growth" in summary_text
    assert "Hidden tables: Forwarder RIB, DV neighbors, DV RIB, and one-phase prefix-to-router mappings." in summary_text
    assert "forwarder FIB growth" in summary_text
    assert "forwarder RIB growth" not in summary_text


def test_role_table_aggregations_average_across_trials():
    rows = [
        {
            "trial": "1",
            "prefix_count": "100",
            "role": "core",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "total_entries": "60",
            "avg_entries": "10",
        },
        {
            "trial": "1",
            "prefix_count": "100",
            "role": "edge",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "total_entries": "30",
            "avg_entries": "7.5",
        },
        {
            "trial": "2",
            "prefix_count": "100",
            "role": "core",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "total_entries": "72",
            "avg_entries": "12",
        },
        {
            "trial": "2",
            "prefix_count": "100",
            "role": "edge",
            "table_category": "common",
            "table_name": "forwarder_rib",
            "total_entries": "34",
            "avg_entries": "8.5",
        },
    ]

    totals = _aggregate_total_entries_by_prefix_and_table(rows)
    assert totals[("common", "forwarder_rib")][100] == 98.0

    core_avg = _aggregate_avg_entries_by_prefix_and_table(rows, role="core")
    edge_avg = _aggregate_avg_entries_by_prefix_and_table(rows, role="edge")
    assert core_avg[("common", "forwarder_rib")][100] == 11.0
    assert edge_avg[("common", "forwarder_rib")][100] == 8.0


def test_rocketfuel_plot_cli_generates_topology_and_summary(tmp_path):
    data_dir = tmp_path / "rocketfuel_4755"
    onephase_dir = data_dir / "onephase"
    twophase_dir = data_dir / "twophase"

    metadata = '{\n  "topology": "rocketfuel_4755"\n}\n'
    rocketfuel_onephase_rows = (
        "onephase,1,0,core,common,forwarder_rib,10,200,20.0,20\n"
        "onephase,1,100,core,common,forwarder_rib,10,300,30.0,30\n"
        "onephase,1,0,core,common,forwarder_fib,10,250,25.0,25\n"
        "onephase,1,100,core,common,forwarder_fib,10,350,35.0,35\n"
        "onephase,1,0,core,onephase,dv_prefix_table,10,0,0.0,0\n"
        "onephase,1,100,core,onephase,dv_prefix_table,10,1000,100.0,100\n"
        "onephase,1,0,edge,common,forwarder_rib,1,20,20.0,20\n"
        "onephase,1,100,edge,common,forwarder_rib,1,120,120.0,120\n"
        "onephase,1,0,edge,common,forwarder_fib,1,25,25.0,25\n"
        "onephase,1,100,edge,common,forwarder_fib,1,125,125.0,125\n"
        "onephase,1,0,edge,onephase,dv_prefix_table,1,0,0.0,0\n"
        "onephase,1,100,edge,onephase,dv_prefix_table,1,100,100.0,100\n"
    )
    rocketfuel_twophase_rows = (
        "twophase,1,0,core,twophase,forwarder_pet,10,180,18.0,18\n"
        "twophase,1,100,core,twophase,forwarder_pet,10,1180,118.0,118\n"
        "twophase,1,0,core,twophase,dv_prefix_egress_state,10,0,0.0,0\n"
        "twophase,1,100,core,twophase,dv_prefix_egress_state,10,1000,100.0,100\n"
        "twophase,1,0,edge,twophase,forwarder_pet,1,18,18.0,18\n"
        "twophase,1,100,edge,twophase,forwarder_pet,1,118,118.0,118\n"
        "twophase,1,0,edge,twophase,dv_prefix_egress_state,1,0,0.0,0\n"
        "twophase,1,100,edge,twophase,dv_prefix_egress_state,1,100,100.0,100\n"
    )

    _write(onephase_dir / "metadata.json", metadata)
    _write(twophase_dir / "metadata.json", metadata)
    _write(onephase_dir / "runs.csv", _runs_csv("onephase", num_nodes=11, num_links=12, prefix_counts=(0, 100)))
    _write(twophase_dir / "runs.csv", _runs_csv("twophase", num_nodes=11, num_links=12, prefix_counts=(0, 100)))
    _write(onephase_dir / "role_table_summary.csv", ROLE_SUMMARY_HEADER + rocketfuel_onephase_rows)
    _write(twophase_dir / "role_table_summary.csv", ROLE_SUMMARY_HEADER + rocketfuel_twophase_rows)
    _write(
        onephase_dir / "link-trace-onephase-p0-t1.csv",
        LINK_TRACE_HEADER + "0.05,100,10000,10,1000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        onephase_dir / "link-trace-onephase-p100-t1.csv",
        LINK_TRACE_HEADER + "0.05,110,11000,20,2000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        twophase_dir / "link-trace-twophase-p0-t1.csv",
        LINK_TRACE_HEADER + "0.05,120,12000,30,3000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        twophase_dir / "link-trace-twophase-p100-t1.csv",
        LINK_TRACE_HEADER + "0.05,130,13000,40,4000,0,0,0,0,0,0,0,0\n",
    )

    assert main(["--data", str(data_dir)]) == 0

    plot_dir = data_dir / "plots"
    assert (plot_dir / "rocketfuel_4755_topology.png").exists()
    assert (plot_dir / "rocketfuel_4755_run_comparison.png").exists()
    assert (plot_dir / "rocketfuel_4755_control_breakdown.png").exists()
    assert (plot_dir / "rocketfuel_4755_prefix_state_by_role.png").exists()
    assert (plot_dir / "rocketfuel_4755_forwarding_delta_by_role.png").exists()
    assert (plot_dir / "rocketfuel_4755_table_average_by_role.png").exists()
    assert (plot_dir / "rocketfuel_4755_table_average_by_role_reduced.png").exists()
    assert (plot_dir / "rocketfuel_4755_table_stack_comparison.png").exists()
    assert (plot_dir / "rocketfuel_4755_table_stack_comparison_reduced.png").exists()

    summary_path = data_dir / "summary.md"
    assert summary_path.exists()
    summary_text = summary_path.read_text()
    assert "# Rocketfuel 4755 Prefix-Scale Summary" in summary_text
    assert "plots/rocketfuel_4755_topology.png" in summary_text
    assert "plots/rocketfuel_4755_run_comparison.png" in summary_text
    assert "plots/rocketfuel_4755_table_average_by_role.png" in summary_text
    assert "plots/rocketfuel_4755_table_average_by_role_reduced.png" in summary_text
    assert "plots/rocketfuel_4755_table_stack_comparison.png" in summary_text
    assert "plots/rocketfuel_4755_table_stack_comparison_reduced.png" in summary_text


def test_large_rocketfuel_plot_cli_generates_topology_and_summary(tmp_path):
    data_dir = tmp_path / "rocketfuel_2914"
    onephase_dir = data_dir / "onephase"
    twophase_dir = data_dir / "twophase"

    metadata = '{\n  "topology": "rocketfuel_2914"\n}\n'
    rocketfuel_onephase_rows = (
        "onephase,1,0,core,common,forwarder_rib,453,9060,20.0,20\n"
        "onephase,1,100,core,common,forwarder_rib,453,13590,30.0,30\n"
        "onephase,1,0,core,common,forwarder_fib,453,11325,25.0,25\n"
        "onephase,1,100,core,common,forwarder_fib,453,15855,35.0,35\n"
        "onephase,1,0,core,onephase,dv_prefix_table,453,0,0.0,0\n"
        "onephase,1,100,core,onephase,dv_prefix_table,453,45300,100.0,100\n"
        "onephase,1,0,edge,common,forwarder_rib,507,10140,20.0,20\n"
        "onephase,1,100,edge,common,forwarder_rib,507,60840,120.0,120\n"
        "onephase,1,0,edge,common,forwarder_fib,507,12675,25.0,25\n"
        "onephase,1,100,edge,common,forwarder_fib,507,63375,125.0,125\n"
        "onephase,1,0,edge,onephase,dv_prefix_table,507,0,0.0,0\n"
        "onephase,1,100,edge,onephase,dv_prefix_table,507,50700,100.0,100\n"
    )
    rocketfuel_twophase_rows = (
        "twophase,1,0,core,twophase,forwarder_pet,453,8154,18.0,18\n"
        "twophase,1,100,core,twophase,forwarder_pet,453,53454,118.0,118\n"
        "twophase,1,0,core,twophase,dv_prefix_egress_state,453,0,0.0,0\n"
        "twophase,1,100,core,twophase,dv_prefix_egress_state,453,45300,100.0,100\n"
        "twophase,1,0,edge,twophase,forwarder_pet,507,9126,18.0,18\n"
        "twophase,1,100,edge,twophase,forwarder_pet,507,59826,118.0,118\n"
        "twophase,1,0,edge,twophase,dv_prefix_egress_state,507,0,0.0,0\n"
        "twophase,1,100,edge,twophase,dv_prefix_egress_state,507,50700,100.0,100\n"
    )

    _write(onephase_dir / "metadata.json", metadata)
    _write(twophase_dir / "metadata.json", metadata)
    _write(onephase_dir / "runs.csv", _runs_csv("onephase", num_nodes=960, num_links=1558, prefix_counts=(0, 100)))
    _write(twophase_dir / "runs.csv", _runs_csv("twophase", num_nodes=960, num_links=1558, prefix_counts=(0, 100)))
    _write(onephase_dir / "role_table_summary.csv", ROLE_SUMMARY_HEADER + rocketfuel_onephase_rows)
    _write(twophase_dir / "role_table_summary.csv", ROLE_SUMMARY_HEADER + rocketfuel_twophase_rows)
    _write(
        onephase_dir / "link-trace-onephase-p0-t1.csv",
        LINK_TRACE_HEADER + "0.05,100,10000,10,1000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        onephase_dir / "link-trace-onephase-p100-t1.csv",
        LINK_TRACE_HEADER + "0.05,110,11000,20,2000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        twophase_dir / "link-trace-twophase-p0-t1.csv",
        LINK_TRACE_HEADER + "0.05,120,12000,30,3000,0,0,0,0,0,0,0,0\n",
    )
    _write(
        twophase_dir / "link-trace-twophase-p100-t1.csv",
        LINK_TRACE_HEADER + "0.05,130,13000,40,4000,0,0,0,0,0,0,0,0\n",
    )

    assert main(["--data", str(data_dir)]) == 0

    plot_dir = data_dir / "plots"
    assert (plot_dir / "rocketfuel_2914_topology.png").exists()
    assert (plot_dir / "rocketfuel_2914_run_comparison.png").exists()
    assert (plot_dir / "rocketfuel_2914_control_breakdown.png").exists()
    assert (plot_dir / "rocketfuel_2914_prefix_state_by_role.png").exists()
    assert (plot_dir / "rocketfuel_2914_forwarding_delta_by_role.png").exists()
    assert (plot_dir / "rocketfuel_2914_table_average_by_role.png").exists()
    assert (plot_dir / "rocketfuel_2914_table_average_by_role_reduced.png").exists()
    assert (plot_dir / "rocketfuel_2914_table_stack_comparison.png").exists()
    assert (plot_dir / "rocketfuel_2914_table_stack_comparison_reduced.png").exists()

    summary_path = data_dir / "summary.md"
    assert summary_path.exists()
    summary_text = summary_path.read_text()
    assert "# Rocketfuel 2914 Prefix-Scale Summary" in summary_text
    assert "largest connected `r0` component" in summary_text
    assert "plots/rocketfuel_2914_topology.png" in summary_text
    assert "plots/rocketfuel_2914_table_average_by_role.png" in summary_text
    assert "plots/rocketfuel_2914_table_average_by_role_reduced.png" in summary_text
    assert "plots/rocketfuel_2914_table_stack_comparison_reduced.png" in summary_text