import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from sim import scalability


class _DummyWriter:
    def __init__(self, path):
        self.path = path
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def write(self, result):
        self.rows.append(result)


def _stub_scalability_driver(monkeypatch, tmp_path):
    ns3_dir = tmp_path / "ns3"
    ns3_dir.mkdir()
    calls = []

    monkeypatch.setattr(scalability, "resolve_ns3_dir", lambda _: str(ns3_dir))
    monkeypatch.setattr(scalability, "generate_ndnsim_topo", lambda *args, **kwargs: None)
    monkeypatch.setattr(scalability, "grid_stats", lambda size: (size * size, 2 * size * (size - 1)))
    monkeypatch.setattr(
        scalability,
        "run_scenario",
        lambda ns3_dir, **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        scalability,
        "sim_trial_result",
        lambda *args, **kwargs: SimpleNamespace(
            convergence_s=-1,
            total_packets=0,
            total_bytes=0,
            dv_bytes=0,
        ),
    )
    monkeypatch.setattr(scalability, "ResultWriter", _DummyWriter)
    return calls, ns3_dir


def test_scalability_requires_convergence_by_default(monkeypatch, tmp_path):
    calls, ns3_dir = _stub_scalability_driver(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scalability.py",
            "--ns3-dir",
            str(ns3_dir),
            "--grids",
            "3",
            "--trials",
            "1",
            "--out",
            str(tmp_path / "out"),
        ],
    )

    scalability.main()

    assert calls[0]["require_convergence"] is True


def test_scalability_can_allow_missing_convergence(monkeypatch, tmp_path):
    calls, ns3_dir = _stub_scalability_driver(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scalability.py",
            "--ns3-dir",
            str(ns3_dir),
            "--grids",
            "3",
            "--trials",
            "1",
            "--allow-no-convergence",
            "--out",
            str(tmp_path / "out"),
        ],
    )

    scalability.main()

    assert calls[0]["require_convergence"] is False