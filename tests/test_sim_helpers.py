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