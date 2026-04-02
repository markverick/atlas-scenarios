"""Tests for lib/config.py -- load_config, dv_config_from."""
import json
import os
import tempfile
import pytest

from lib.config import load_config, dv_config_from


def _write_cfg(tmp_path, data):
    p = os.path.join(tmp_path, "cfg.json")
    with open(p, "w") as f:
        json.dump(data, f)
    return p


def test_load_defaults(tmp_path):
    path = _write_cfg(str(tmp_path), {})
    cfg = load_config(path)
    assert cfg["topology"] == "grid"
    assert cfg["trials"] == 1
    assert cfg["window_s"] == 60.0
    assert cfg["modes"] == []


def test_load_overrides(tmp_path):
    path = _write_cfg(str(tmp_path), {
        "topology": "sprint",
        "trials": 3,
        "window_s": 120.0,
        "modes": ["baseline"],
    })
    cfg = load_config(path)
    assert cfg["topology"] == "sprint"
    assert cfg["trials"] == 3
    assert cfg["window_s"] == 120.0
    assert cfg["modes"] == ["baseline"]


def test_int_promoted_to_float(tmp_path):
    path = _write_cfg(str(tmp_path), {"window_s": 300})
    cfg = load_config(path)
    assert cfg["window_s"] == 300.0
    assert isinstance(cfg["window_s"], float)


def test_type_mismatch_raises(tmp_path):
    path = _write_cfg(str(tmp_path), {"trials": "not_a_number"})
    with pytest.raises(ValueError, match="trials"):
        load_config(path)


def test_dv_config_none_by_default(tmp_path):
    path = _write_cfg(str(tmp_path), {})
    cfg = load_config(path)
    assert dv_config_from(cfg) is None


def test_dv_config_with_overrides(tmp_path):
    path = _write_cfg(str(tmp_path), {
        "advertise_interval": 5000,
        "router_dead_interval": 30000,
        "prefix_sync_delay": 2000,
    })
    cfg = load_config(path)
    dv = dv_config_from(cfg)
    assert dv["advertise_interval"] == 5000
    assert dv["router_dead_interval"] == 30000
    assert dv["prefix_sync_delay"] == 2000
    assert "one_step" not in dv
