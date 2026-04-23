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


def _stub_driver(monkeypatch, tmp_path, *, scenario):
    ns3_dir = tmp_path / "ns3"
    ns3_dir.mkdir()
    calls = []

    monkeypatch.setattr(scalability, "resolve_ns3_dir", lambda _: str(ns3_dir))
    monkeypatch.setattr(scalability, "generate_ndnsim_topo", lambda *args, **kwargs: None)
    monkeypatch.setattr(scalability, "grid_stats", lambda size: (size * size, 2 * size * (size - 1)))
    if scenario == "routing":
        monkeypatch.setattr(
            scalability,
            "run_routing_scenario",
            lambda ns3_dir, **kwargs: calls.append(kwargs),
        )
        monkeypatch.setattr(scalability, "parse_conv_trace", lambda _: 0.1234)
        monkeypatch.setattr(
            scalability,
            "parse_link_trace",
            lambda _: dict(
                total_packets=10,
                total_bytes=20,
                control_packets=3,
                control_bytes=4,
                user_packets=0,
                user_bytes=0,
            ),
        )
        monkeypatch.setattr(scalability, "TrialResult", lambda **kwargs: SimpleNamespace(**kwargs))
    else:
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
                control_bytes=0,
            ),
        )
    monkeypatch.setattr(scalability, "ResultWriter", _DummyWriter)
    return calls, ns3_dir


def test_scalability_requires_convergence_by_default(monkeypatch, tmp_path):
    calls, ns3_dir = _stub_driver(monkeypatch, tmp_path, scenario="scalability")
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
    calls, ns3_dir = _stub_driver(monkeypatch, tmp_path, scenario="scalability")
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


def test_routing_mode_uses_routing_runner(monkeypatch, tmp_path):
    calls, ns3_dir = _stub_driver(monkeypatch, tmp_path, scenario="routing")
    scalability.main(
        [
            "--ns3-dir",
            str(ns3_dir),
            "--grids",
            "3",
            "--trials",
            "1",
            "--out",
            str(tmp_path / "out"),
        ],
        routing=True,
    )

    assert calls[0]["sim_time"] == 30.0
    assert calls[0]["packet_trace"].endswith("packet-trace-routing-3x3-t1.csv")