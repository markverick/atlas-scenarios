import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sim import _helpers


def _prepare_outputs(tmp_path):
    ns3_dir = tmp_path / "ns3"
    topo = tmp_path / "topo.txt"
    rate_csv = tmp_path / "rate.csv"
    conv_file = tmp_path / "conv.txt"
    link_csv = tmp_path / "link.csv"

    ns3_dir.mkdir()
    topo.write_text("dummy topo\n")
    rate_csv.write_text("time,packets\n1,2\n")
    conv_file.write_text("-1\n")
    link_csv.write_text("ts,packets\n1,2\n")

    return ns3_dir, topo, rate_csv, conv_file, link_csv


def _stub_run(monkeypatch):
    monkeypatch.setattr(_helpers, "sync_scenario", lambda ns3_dir: None)
    monkeypatch.setattr(_helpers, "sync_routing_scenario", lambda ns3_dir: None)
    monkeypatch.setattr(_helpers, "sync_prefix_scale_scenario", lambda ns3_dir: None)
    monkeypatch.setattr(_helpers, "_build_ns3", lambda ns3_dir, cores: None)
    monkeypatch.setattr(_helpers, "_find_scenario_exe", lambda ns3_dir, target: "/bin/true")
    monkeypatch.setattr(_helpers, "_run_exe", lambda exe, run_args, run_log: None)


def test_run_scenario_requires_convergence_by_default(monkeypatch, tmp_path):
    ns3_dir, topo, rate_csv, conv_file, link_csv = _prepare_outputs(tmp_path)
    _stub_run(monkeypatch)

    with pytest.raises(RuntimeError, match="convergence=-1"):
        _helpers.run_scenario(
            str(ns3_dir),
            topo=str(topo),
            rate_trace=str(rate_csv),
            conv_trace=str(conv_file),
            link_trace=str(link_csv),
        )


def test_run_scenario_allows_unconverged_outputs_when_requested(monkeypatch, tmp_path):
    ns3_dir, topo, rate_csv, conv_file, link_csv = _prepare_outputs(tmp_path)
    _stub_run(monkeypatch)

    _helpers.run_scenario(
        str(ns3_dir),
        topo=str(topo),
        rate_trace=str(rate_csv),
        conv_trace=str(conv_file),
        link_trace=str(link_csv),
        require_convergence=False,
    )


@pytest.mark.parametrize(
    ("conv_text", "remove_file", "match"),
    [
        ("-1\n", False, "convergence=-1"),
        ("0.1234\n", True, "was not created"),
    ],
)
def test_run_routing_scenario_requires_valid_convergence_trace(monkeypatch, tmp_path,
                                                               conv_text, remove_file, match):
    ns3_dir, topo, _rate_csv, conv_file, link_csv = _prepare_outputs(tmp_path)
    _stub_run(monkeypatch)

    conv_file.write_text(conv_text)
    if remove_file:
        conv_file.unlink()

    with pytest.raises(RuntimeError, match=match):
        _helpers.run_routing_scenario(
            str(ns3_dir),
            topo=str(topo),
            conv_trace=str(conv_file),
            link_trace=str(link_csv),
        )


def test_run_prefix_scale_scenario_requires_table_trace(monkeypatch, tmp_path):
    ns3_dir, topo, _rate_csv, conv_file, link_csv = _prepare_outputs(tmp_path)
    table_csv = tmp_path / "tables.csv"
    _stub_run(monkeypatch)

    conv_file.write_text("0.123\n")

    with pytest.raises(RuntimeError, match="table_trace '.*tables.csv' was not created"):
        _helpers.run_prefix_scale_scenario(
            str(ns3_dir),
            topo=str(topo),
            edge_nodes=["e0", "e1"],
            conv_trace=str(conv_file),
            link_trace=str(link_csv),
            table_trace=str(table_csv),
        )


def test_run_prefix_scale_scenario_accepts_valid_outputs(monkeypatch, tmp_path):
    ns3_dir, topo, _rate_csv, conv_file, link_csv = _prepare_outputs(tmp_path)
    table_csv = tmp_path / "tables.csv"
    _stub_run(monkeypatch)

    conv_file.write_text("0.123\n")
    table_csv.write_text(
        "node,role,table_category,table_name,entry_count\n"
        "c0,core,common,forwarder_rib,10\n"
    )

    _helpers.run_prefix_scale_scenario(
        str(ns3_dir),
        topo=str(topo),
        edge_nodes=["e0", "e1"],
        conv_trace=str(conv_file),
        link_trace=str(link_csv),
        table_trace=str(table_csv),
    )


def test_run_prefix_scale_scenario_passes_role_specific_dv_configs(monkeypatch, tmp_path):
    ns3_dir, topo, _rate_csv, conv_file, link_csv = _prepare_outputs(tmp_path)
    table_csv = tmp_path / "tables.csv"
    captured = {}

    monkeypatch.setattr(_helpers, "sync_scenario", lambda ns3_dir: None)
    monkeypatch.setattr(_helpers, "sync_routing_scenario", lambda ns3_dir: None)
    monkeypatch.setattr(_helpers, "sync_prefix_scale_scenario", lambda ns3_dir: None)
    monkeypatch.setattr(_helpers, "_build_ns3", lambda ns3_dir, cores: None)
    monkeypatch.setattr(_helpers, "_find_scenario_exe", lambda ns3_dir, target: "/bin/true")
    monkeypatch.setattr(
        _helpers,
        "_run_exe",
        lambda exe, run_args, run_log: captured.setdefault("run_args", list(run_args)),
    )

    conv_file.write_text("0.123\n")
    table_csv.write_text(
        "node,role,table_category,table_name,entry_count\n"
        "c0,core,common,forwarder_rib,10\n"
    )

    _helpers.run_prefix_scale_scenario(
        str(ns3_dir),
        topo=str(topo),
        edge_nodes=["e0", "e1"],
        conv_trace=str(conv_file),
        link_trace=str(link_csv),
        table_trace=str(table_csv),
        dv_config={"advertise_interval": 2000},
        core_dv_config={"prefix_egre_state_replicate": False},
        edge_dv_config={"router_dead_interval": 6000},
    )

    assert captured["run_args"] == [
        f"--topo={topo}",
        "--simTime=40.0",
        "--network=/minindn",
        "--edgeNodes=e0,e1",
        "--numPrefixes=0",
        f"--convTrace={conv_file}",
        f"--linkTrace={link_csv}",
        f"--tableTrace={table_csv}",
        f"--dvConfig={json.dumps({'advertise_interval': 2000}, separators=(',', ':'))}",
        f"--coreDvConfig={json.dumps({'prefix_egre_state_replicate': False}, separators=(',', ':'))}",
        f"--edgeDvConfig={json.dumps({'router_dead_interval': 6000}, separators=(',', ':'))}",
    ]