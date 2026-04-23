import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from experiments.prefix_scale.plots.prefix_scale_cli import main


RUNS_CSV = (
    "phase,trial,prefix_count,num_nodes,num_links,router_reachability_s,control_packets,control_bytes,total_packets,total_bytes\n"
    "{phase},1,0,10,12,0.205,1000,200000,1000,200000\n"
    "{phase},1,1,10,12,0.205,1100,210000,1100,210000\n"
)


ROLE_SUMMARY_HEADER = (
    "phase,trial,prefix_count,role,table_category,table_name,node_count,total_entries,avg_entries,max_entries\n"
)


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

    _write(onephase_dir / "runs.csv", RUNS_CSV.format(phase="onephase"))
    _write(twophase_dir / "runs.csv", RUNS_CSV.format(phase="twophase"))
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
    assert (plot_dir / "core_edge_table_stack_comparison.png").exists()

    summary_path = data_dir / "summary.md"
    assert summary_path.exists()
    summary_text = summary_path.read_text()
    assert "# Core/Edge Prefix-Scale Summary" in summary_text
    assert "plots/core_edge_topology.png" in summary_text
    assert "plots/core_edge_run_comparison.png" in summary_text
    assert "plots/core_edge_table_stack_comparison.png" in summary_text