#!/usr/bin/env python3
"""
Churn scenario — two-phase measurement in emulation (Mini-NDN).

Phase 1 (convergence): DV boot → converge → announce prefixes → stabilize.
Phase 2 (churn):       Link fail/recover + prefix withdraw/re-announce.

Supports any topology registered in lib/churn_common.KNOWN_TOPOLOGIES, as well
as arbitrary NxN grid topologies.  The topology type is selected by the JSON
config key "topology" (default: "grid").

For each topology (or grid size), runs three variants:
  1. baseline  — no prefixes (pure DV overhead under churn)
  2. two_step  — DV + PrefixSync under churn
  3. one_step  — prefixes in DV adverts under churn

Usage (needs sudo):
    sudo python3 emu/churn.py --config experiments/prefix_scale/scenarios/sprint_twostep_emu_0to50.json
"""

import argparse
import csv
import json
import os
import sys
import time
import threading

from mininet.log import setLogLevel, info

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.config import load_config, dv_config_from
from lib.pcap import parse_pcap_packets
from lib.result_adapter import parse_router_reachable_logs
from emu._helpers import (
    NETWORK,
    setup_grid, setup_conf_topo, start_tcpdump, stop_tcpdump,
    blackhole_link, restore_link,
)
from minindn.helpers import dv_util
from lib.churn_common import (
    FIELDNAMES, KNOWN_TOPOLOGIES,
    build_churn_events, build_random_churn_events,
    build_prefix_scaling_events,
    parse_packet_events_by_phase, build_result_rows,
    make_tag, auto_plot, default_out_dir, grid_churn_targets,
)
from lib.topology import grid_links, grid_nodes


def _zero_counts(*names):
    return {name: 0 for name in names}


def _init_variant_stats(tag, *, topology, mode, num_prefixes, trial):
    return {
        "tag": tag,
        "topology": topology,
        "mode": mode,
        "num_prefixes": num_prefixes,
        "trial": trial,
        "planned": _zero_counts(
            "link_down",
            "link_up",
            "prefix_withdraw",
            "prefix_announce",
        ),
        "executed": _zero_counts(
            "link_down",
            "link_up",
            "prefix_withdraw",
            "prefix_announce",
        ),
        "retried": _zero_counts(
            "prefix_withdraw",
            "prefix_announce",
            "bulk_cleanup",
        ),
        "skipped": _zero_counts(
            "prefix_withdraw",
            "prefix_announce",
            "bulk_cleanup",
        ),
        "timing_s": {},
    }


def _bump(stats, bucket, name, delta=1):
    stats[bucket][name] = stats[bucket].get(name, 0) + delta


def _write_variant_stats(out_dir, tag, stats):
    path = os.path.join(out_dir, f"churn-stats-{tag}.json")
    with open(path, "w") as f:
        json.dump(stats, f, indent=2, sort_keys=True)
    return path


def _write_svs_suppression(out_dir, tag, data):
    path = os.path.join(out_dir, f"svs-suppression-{tag}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return path


def _collect_svs_suppression_stats(hosts):
    result = {
        "nodes": {},
        "aggregate": {"enter": 0, "ok": 0, "fail": 0, "unresolved": 0},
        "errors": {},
    }
    for host in hosts:
        raw = host.cmd("ndnd dv svs-status 2>/dev/null").strip()
        if not raw:
            result["errors"][host.name] = "empty response"
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1 or end <= start:
                result["errors"][host.name] = f"invalid json: {exc}"
                continue
            try:
                payload = json.loads(raw[start:end + 1])
            except json.JSONDecodeError as inner_exc:
                result["errors"][host.name] = f"invalid json: {inner_exc}"
                continue

        suppression = payload.get("suppression", {})
        enter = int(suppression.get("enter", 0))
        ok = int(suppression.get("ok", 0))
        fail = int(suppression.get("fail", 0))
        suppression["unresolved"] = enter - ok - fail
        payload["suppression"] = suppression
        result["nodes"][host.name] = payload
        result["aggregate"]["enter"] += enter
        result["aggregate"]["ok"] += ok
        result["aggregate"]["fail"] += fail

    result["aggregate"]["unresolved"] = (
        result["aggregate"]["enter"]
        - result["aggregate"]["ok"]
        - result["aggregate"]["fail"]
    )
    return result


def _compute_svs_suppression_delta(start_snapshot, end_snapshot, *, phase, start_s, end_s):
    delta = {
        "phase": phase,
        "window": {
            "start_s": round(start_s, 6),
            "end_s": round(end_s, 6),
            "duration_s": round(end_s - start_s, 6),
        },
        "nodes": {},
        "aggregate": {"enter": 0, "ok": 0, "fail": 0, "unresolved": 0},
        "errors": {
            "start": dict(start_snapshot.get("errors", {})),
            "end": dict(end_snapshot.get("errors", {})),
        },
        "snapshots": {
            "start": start_snapshot,
            "end": end_snapshot,
        },
    }

    node_names = set(start_snapshot.get("nodes", {})) | set(end_snapshot.get("nodes", {}))
    for node_name in sorted(node_names):
        start_payload = start_snapshot.get("nodes", {}).get(node_name, {})
        end_payload = end_snapshot.get("nodes", {}).get(node_name, {})
        start_supp = start_payload.get("suppression", {})
        end_supp = end_payload.get("suppression", {})

        enter = int(end_supp.get("enter", 0)) - int(start_supp.get("enter", 0))
        ok = int(end_supp.get("ok", 0)) - int(start_supp.get("ok", 0))
        fail = int(end_supp.get("fail", 0)) - int(start_supp.get("fail", 0))

        node_payload = dict(end_payload or start_payload)
        node_payload["suppression"] = {
            "enter": enter,
            "ok": ok,
            "fail": fail,
            "unresolved": enter - ok - fail,
        }
        delta["nodes"][node_name] = node_payload
        delta["aggregate"]["enter"] += enter
        delta["aggregate"]["ok"] += ok
        delta["aggregate"]["fail"] += fail

    delta["aggregate"]["unresolved"] = (
        delta["aggregate"]["enter"]
        - delta["aggregate"]["ok"]
        - delta["aggregate"]["fail"]
    )
    return delta


# ---- Host-level prefix management (topology-agnostic) ----

def announce_prefixes(hosts, num_prefixes):
    """Announce synthetic prefixes on each host via ``ndnd put --expose``."""
    announced_hosts = []
    for host in hosts:
        host_started = False
        for j in range(num_prefixes):
            pfx = f"/data/{host.name}/pfx{j}"
            host.cmd(f'ndnd put --expose "{pfx}" < /dev/null &')
            host_started = True
        if host_started:
            announced_hosts.append(host)
    time.sleep(0.5)
    return announced_hosts


def withdraw_prefix(host, pfx):
    """Kill background ``ndnd put --expose`` for a specific prefix."""
    host.cmd(f"pkill -f 'ndnd put --expose.*{pfx}' 2>/dev/null; true")


def withdraw_all(announced_hosts, stats=None):
    """Kill all background ``ndnd put --expose`` processes per host.

    Per-prefix teardown scales poorly on Sprint prefix sweeps because each
    ``host.cmd()`` round-trip blocks on the Mininet shell. One bulk kill per
    host keeps shutdown bounded even when thousands of publishers were started.
    """
    for host in announced_hosts:
        try:
            host.cmd("pkill -f 'ndnd put --expose' 2>/dev/null; true")
        except (AssertionError, OSError):
            if stats is not None:
                _bump(stats, "retried", "bulk_cleanup")
            info(f"  CHURN: WARNING: bulk cleanup retry {host.name}\n")
            time.sleep(0.2)
            try:
                host.cmd("pkill -f 'ndnd put --expose' 2>/dev/null; true")
            except (AssertionError, OSError):
                if stats is not None:
                    _bump(stats, "skipped", "bulk_cleanup")
                info(f"  CHURN: WARNING: bulk cleanup skipped {host.name}\n")
    time.sleep(0.3)


# ---- Churn event scheduler ----

def schedule_churn_events(ndn, hosts, churn_events, dv_start, stats=None, action_lock=None):
    """Schedule churn events as timed threads (wall-clock based).

    Parameters
    ----------
    churn_events : list[dict]
        Event dicts with keys: time (absolute sim-relative), type, and
        src/dst (for link events) or node/prefix (for prefix events).
        Same format as build_churn_events() / build_random_churn_events().
    dv_start : float
        Epoch time when DV started (wall-clock reference).
    """
    host_map = {h.name: h for h in hosts}
    timers = []
    # Mininet node.cmd() is not thread-safe; serialize all churn actions.
    lock = action_lock or threading.Lock()

    for ev in churn_events:
        delay = dv_start + ev["time"] - time.time()
        if delay < 0:
            delay = 0

        etype = ev["type"]
        if etype == "link_down":
            src, dst = ev["src"], ev["dst"]
            def do_link_down(s=src, d=dst):
                info(f"  CHURN: link DOWN {s}--{d}\n")
                with lock:
                    if stats is not None:
                        _bump(stats, "executed", "link_down")
                    blackhole_link(ndn.net, s, d)
            t = threading.Timer(delay, do_link_down)

        elif etype == "link_up":
            src, dst = ev["src"], ev["dst"]
            def do_link_up(s=src, d=dst):
                info(f"  CHURN: link UP {s}--{d}\n")
                with lock:
                    if stats is not None:
                        _bump(stats, "executed", "link_up")
                    restore_link(ndn.net, s, d)
            t = threading.Timer(delay, do_link_up)

        elif etype == "prefix_withdraw":
            node_name, pfx = ev["node"], ev["prefix"]
            host = host_map[node_name]
            def do_withdraw(h=host, p=pfx, n=node_name):
                info(f"  CHURN: prefix WITHDRAW {n} {p}\n")
                with lock:
                    if stats is not None:
                        _bump(stats, "executed", "prefix_withdraw")
                    try:
                        withdraw_prefix(h, p)
                    except (AssertionError, OSError):
                        if stats is not None:
                            _bump(stats, "retried", "prefix_withdraw")
                        info(f"  CHURN: WARNING: withdraw retry {n} {p}\n")
                        time.sleep(0.2)
                        try:
                            withdraw_prefix(h, p)
                        except (AssertionError, OSError):
                            if stats is not None:
                                _bump(stats, "skipped", "prefix_withdraw")
                            info(f"  CHURN: WARNING: withdraw skipped {n} {p}\n")
            t = threading.Timer(delay, do_withdraw)

        elif etype == "prefix_announce":
            node_name, pfx = ev["node"], ev["prefix"]
            host = host_map[node_name]
            def do_announce(h=host, p=pfx, n=node_name):
                info(f"  CHURN: prefix ANNOUNCE {n} {p}\n")
                with lock:
                    if stats is not None:
                        _bump(stats, "executed", "prefix_announce")
                    try:
                        h.cmd(f'ndnd put --expose "{p}" < /dev/null &')
                    except (AssertionError, OSError):
                        if stats is not None:
                            _bump(stats, "retried", "prefix_announce")
                        info(f"  CHURN: WARNING: announce retry {n} {p}\n")
                        time.sleep(0.2)
                        try:
                            h.cmd(f'ndnd put --expose "{p}" < /dev/null &')
                        except (AssertionError, OSError):
                            if stats is not None:
                                _bump(stats, "skipped", "prefix_announce")
                            info(f"  CHURN: WARNING: announce skipped {n} {p}\n")
            t = threading.Timer(delay, do_announce)

        else:
            continue

        t.start()
        timers.append(t)

    return timers


# ---- Variant runner ----

def _run_one_variant(*, ndn_factory, topology, topo_id_str,
                     grid_size, num_nodes, num_links,
                     link_src, link_dst, churn_node,
                     trial, mode, num_prefixes, window_s,
                     dv_config, sim_time, deadline, out_dir, cfg=None,
                     all_links=None, all_nodes=None):
    """Run one variant and return a list of result dicts."""
    tag = make_tag(mode, topo_id_str, num_prefixes, trial)
    pfx_count = num_prefixes if mode != "baseline" else 0
    run_t0 = time.monotonic()
    stats = _init_variant_stats(
        tag,
        topology=topology,
        mode=mode,
        num_prefixes=pfx_count,
        trial=trial,
    )

    churn_after_conv = (cfg or {}).get("churn_after_convergence", False)
    churn_margin = (cfg or {}).get("convergence_margin_s", 10.0)
    churn_dur_cfg = (cfg or {}).get("churn_duration_s", 0.0)
    churn_duration = churn_dur_cfg if churn_dur_cfg > 0 else (sim_time / 2.0)

    info(f"\n=== {mode}: {topo_id_str} ({num_nodes} nodes), "
         f"prefixes={pfx_count}, trial {trial}"
         f"{' [churn-after-conv]' if churn_after_conv else ''} ===\n")

    dvc = dict(dv_config) if dv_config else {}
    if mode in ("one_step", "baseline"):
        dvc["one_step"] = True
    else:
        dvc.pop("one_step", None)

    t0 = time.monotonic()
    ndn, num_nodes, num_links = ndn_factory()
    cap_tag, cap_paths = start_tcpdump(ndn.net.hosts, prefix="ndnd_churn")
    dv_start = dv_util.setup(ndn, network=NETWORK, dv_config=dvc or None)
    stats["timing_s"]["setup"] = round(time.monotonic() - t0, 3)

    conv_elapsed = 0.0
    t0 = time.monotonic()
    try:
        conv_elapsed = dv_util.converge(ndn.net.hosts, deadline=deadline,
                                        network=NETWORK, start=dv_start)
    except Exception:
        pass
    stats["timing_s"]["converge_wait"] = round(time.monotonic() - t0, 3)

    # Announce synthetic prefixes
    announced = []
    if pfx_count > 0:
        t0 = time.monotonic()
        announced = announce_prefixes(ndn.net.hosts, pfx_count)
        stats["timing_s"]["initial_prefix_announce"] = round(time.monotonic() - t0, 3)
    else:
        stats["timing_s"]["initial_prefix_announce"] = 0.0

    # Determine phase boundary and event timing
    if churn_after_conv:
        # Churn starts right after convergence + margin (relative to dv_start)
        phase2_start_rel = conv_elapsed + churn_margin
        info(f"  Churn phase starts at t={phase2_start_rel:.2f}s "
             f"(conv={conv_elapsed:.2f}s + margin={churn_margin}s)\n")

        # Events with relative offsets from 0
        evt_start = 0.0
        evt_end = churn_duration
    else:
        p2_cfg = (cfg or {}).get("phase2_start_s", 0.0)
        churn_dur_cfg_val = (cfg or {}).get("churn_duration_s", 0.0)
        if p2_cfg > 0 and churn_dur_cfg_val > 0:
            phase2_start_rel = p2_cfg
            evt_start = p2_cfg
            evt_end = p2_cfg + churn_dur_cfg_val
        else:
            phase2_start_rel = sim_time / 2.0
            evt_start = phase2_start_rel
            evt_end = sim_time

    # Build and schedule churn events
    churn_mode_str = (cfg or {}).get("churn_mode", "fixed")
    if churn_mode_str == "prefix_scaling":
        churn_events = build_prefix_scaling_events(
            pfx_count, evt_start,
            per_prefix_rate=cfg.get("per_prefix_rate", 0.1),
            churn_node=churn_node,
            window_end=evt_end,
            seed=cfg.get("churn_seed", 42),
            recovery_delay=cfg.get("churn_recovery_delay", 3.0),
            all_nodes=all_nodes)
    elif churn_mode_str == "random":
        churn_events = build_random_churn_events(
            pfx_count, evt_start,
            link_src=link_src, link_dst=link_dst, churn_node=churn_node,
            window_end=evt_end,
            seed=cfg.get("churn_seed", 42),
            num_cycles=cfg.get("churn_num_cycles", 3),
            interval=cfg.get("churn_interval", 5.0),
            recovery_delay=cfg.get("churn_recovery_delay", 3.0),
            all_links=all_links,
            all_nodes=all_nodes,
            prefix_churn_rate=cfg.get("churn_prefix_rate", 0.0))
    else:
        churn_events = build_churn_events(
            pfx_count, evt_start,
            link_src=link_src, link_dst=link_dst, churn_node=churn_node)

    for ev in churn_events:
        etype = ev["type"]
        if etype in stats["planned"]:
            _bump(stats, "planned", etype)

    if churn_after_conv:
        # Shift relative offsets to absolute times for the wall-clock scheduler
        churn_events_abs = []
        for ev in churn_events:
            ev_abs = dict(ev)
            ev_abs["time"] = ev["time"] + phase2_start_rel
            churn_events_abs.append(ev_abs)
        scheduled_events = churn_events_abs
    else:
        scheduled_events = churn_events

    action_lock = threading.Lock()
    timers = schedule_churn_events(
        ndn,
        ndn.net.hosts,
        scheduled_events,
        dv_start,
        stats,
        action_lock=action_lock,
    )

    # Write event log CSV (for plot markers) — use absolute times
    evt_csv = os.path.join(out_dir, f"event-log-{tag}.csv")
    with open(evt_csv, "w", newline="") as ef:
        ew = csv.writer(ef)
        ew.writerow(["Time", "Event", "Details"])
        for ev in scheduled_events:
            if ev["type"] in ("link_down", "link_up"):
                details = f"{ev['src']}--{ev['dst']}"
            else:
                details = f"{ev['node']} {ev['prefix']}"
            ew.writerow([ev["time"], ev["type"], details])

    # Query suppression counters immediately before the churn phase begins.
    phase_start_wall = dv_start + phase2_start_rel
    pre_phase_deadline = max(dv_start, phase_start_wall - 0.01)
    now = time.time()
    if now < pre_phase_deadline:
        time.sleep(pre_phase_deadline - now)
    t0 = time.monotonic()
    with action_lock:
        suppression_start = _collect_svs_suppression_stats(ndn.net.hosts)
    stats["timing_s"]["svs_status_query_start"] = round(time.monotonic() - t0, 3)

    # Wait for observation window
    if churn_after_conv:
        # Wait until convergence + margin + churn_duration
        window_end = dv_start + phase2_start_rel + churn_duration
    else:
        window_end = dv_start + sim_time
    now = time.time()
    t0 = time.monotonic()
    if now < window_end:
        time.sleep(window_end - now)
    stats["timing_s"]["observation_wait"] = round(time.monotonic() - t0, 3)

    for t in timers:
        t.cancel()

    t0 = time.monotonic()
    with action_lock:
        suppression_end = _collect_svs_suppression_stats(ndn.net.hosts)
    stats["timing_s"]["svs_status_query_end"] = round(time.monotonic() - t0, 3)

    stop_tcpdump(ndn.net.hosts, cap_tag, prefix="ndnd_churn")

    # Parse per-packet events
    t0 = time.monotonic()
    pkt_events = parse_pcap_packets(cap_paths.values(), time_origin=dv_start)
    stats["timing_s"]["pcap_parse"] = round(time.monotonic() - t0, 3)

    # Save per-packet CSV
    pkt_csv = os.path.join(out_dir, f"packet-trace-{tag}.csv")
    t0 = time.monotonic()
    with open(pkt_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Time", "Category", "Bytes"])
        for t_s, cat, b in pkt_events:
            w.writerow([f"{t_s:.6f}", cat, b])
    stats["timing_s"]["packet_csv_write"] = round(time.monotonic() - t0, 3)

    # Split traffic by phase using actual boundary
    phases = parse_packet_events_by_phase(pkt_events, phase2_start_rel)

    # Convergence from DV logs
    dv_log_paths = [
        os.path.join(h.params['params']['homeDir'], 'log', 'dv.log')
        for h in ndn.net.hosts
    ]
    t0 = time.monotonic()
    conv_time = parse_router_reachable_logs(dv_log_paths, num_nodes=num_nodes)
    stats["timing_s"]["convergence_log_parse"] = round(time.monotonic() - t0, 3)

    suppression = _compute_svs_suppression_delta(
        suppression_start,
        suppression_end,
        phase="churn",
        start_s=phase2_start_rel,
        end_s=window_end - dv_start,
    )

    rows = build_result_rows(
        phases,
        topology=topology,
        grid_size=grid_size,
        num_nodes=num_nodes,
        num_links=num_links,
        trial=trial,
        mode=mode,
        num_prefixes=pfx_count,
        window_s=window_s,
        phase2_start=phase2_start_rel,
        convergence_s=conv_time,
    )

    t0 = time.monotonic()
    try:
        if announced:
            withdraw_all(announced, stats)
    finally:
        try:
            ndn.stop()
        except (AssertionError, OSError):
            info("  CHURN: WARNING: ndn.stop() incomplete; continuing with saved results\n")
    stats["timing_s"]["cleanup"] = round(time.monotonic() - t0, 3)
    stats["timing_s"]["total"] = round(time.monotonic() - run_t0, 3)

    suppress_path = _write_svs_suppression(out_dir, tag, suppression)
    stats_path = _write_variant_stats(out_dir, tag, stats)
    info(
        "  CHURN: stats "
        f"planned(a={stats['planned']['prefix_announce']},w={stats['planned']['prefix_withdraw']}) "
        f"retried(a={stats['retried']['prefix_announce']},w={stats['retried']['prefix_withdraw']},c={stats['retried']['bulk_cleanup']}) "
        f"skipped(a={stats['skipped']['prefix_announce']},w={stats['skipped']['prefix_withdraw']},c={stats['skipped']['bulk_cleanup']}) "
        f"timing(total={stats['timing_s']['total']:.1f}s, obs={stats['timing_s']['observation_wait']:.1f}s, "
        f"parse={stats['timing_s']['pcap_parse']:.1f}s, cleanup={stats['timing_s']['cleanup']:.1f}s)\n"
    )
    info(f"  CHURN: wrote stats {stats_path}\n")
    info(f"  CHURN: wrote suppression {suppress_path}\n")

    return rows


# ---- Topology dispatchers ----

def _run_grid(cfg, dv_config, out_dir, writer, f):
    """Run churn experiments over one or more NxN grid topologies."""
    from lib.topology import grid_stats

    num_prefixes = cfg.get("num_prefixes", 10)
    churn_dur_cfg = cfg.get("churn_duration_s", 0.0)
    p2_cfg = cfg.get("phase2_start_s", 0.0)
    if p2_cfg > 0 and churn_dur_cfg > 0:
        sim_time = p2_cfg + churn_dur_cfg
    else:
        sim_time = cfg["window_s"]
    delay_ms = cfg["delay_ms"]
    bw_mbps = cfg["bandwidth_mbps"]
    cores = cfg["cores"]
    trials = cfg["trials"]

    prefix_counts = cfg.get("prefix_counts", [])
    if not prefix_counts:
        prefix_counts = [num_prefixes]
    sweeping = len(prefix_counts) > 1

    modes = cfg.get("modes", []) or ["baseline", "two_step", "one_step"]

    for grid_size in cfg["grids"]:
        link_src, link_dst, churn_node = grid_churn_targets(grid_size)
        num_nodes, num_links = grid_stats(grid_size)
        all_links_list = grid_links(grid_size)
        all_nodes_list = grid_nodes(grid_size)

        def ndn_factory(gs=grid_size):
            return setup_grid(gs, delay_ms, bw_mbps, cores)

        for trial in range(1, trials + 1):
            baseline_done = False
            for pfx_count in prefix_counts:
                for mode in modes:
                    if sweeping and mode == "baseline" and baseline_done:
                        continue
                    rows = _run_one_variant(
                        ndn_factory=ndn_factory,
                        topology="grid",
                        topo_id_str=f"{grid_size}x{grid_size}",
                        grid_size=grid_size,
                        num_nodes=num_nodes,
                        num_links=num_links,
                        link_src=link_src,
                        link_dst=link_dst,
                        churn_node=churn_node,
                        trial=trial,
                        mode=mode,
                        num_prefixes=pfx_count,
                        window_s=sim_time,
                        dv_config=dv_config,
                        sim_time=sim_time,
                        deadline=120,
                        out_dir=out_dir,
                        cfg=cfg,
                        all_links=all_links_list,
                        all_nodes=all_nodes_list,
                    )
                    _write_rows(writer, f, rows)
                    if mode == "baseline":
                        baseline_done = True


def _run_conf(cfg, dv_config, out_dir, writer, f, topo_name):
    """Run churn experiments on a conf-based topology (Sprint, etc.)."""
    from lib.topology import conf_stats, parse_minindn_conf

    info_entry = KNOWN_TOPOLOGIES[topo_name]
    conf_path = os.path.abspath(info_entry["conf_path"])
    link_src, link_dst = info_entry["churn_link"]
    churn_node = info_entry["churn_node"]

    conf_nodes, conf_links = parse_minindn_conf(conf_path)
    all_links_list = [(s, d) for s, d, _ in conf_links]
    all_nodes_list = conf_nodes

    num_prefixes = cfg.get("num_prefixes", 5)
    churn_dur_cfg = cfg.get("churn_duration_s", 0.0)
    p2_cfg = cfg.get("phase2_start_s", 0.0)
    if p2_cfg > 0 and churn_dur_cfg > 0:
        sim_time = p2_cfg + churn_dur_cfg
    else:
        sim_time = cfg["window_s"]
    delay_ms = cfg["delay_ms"]
    bw_mbps = cfg["bandwidth_mbps"]
    cores = cfg["cores"]
    trials = cfg["trials"]

    num_nodes, num_links = conf_stats(conf_path)
    info(f"{topo_name} topology: {num_nodes} nodes, {num_links} links\n")

    prefix_counts = cfg.get("prefix_counts", [])
    if not prefix_counts:
        prefix_counts = [num_prefixes]
    sweeping = len(prefix_counts) > 1

    modes = cfg.get("modes", []) or ["baseline", "two_step", "one_step"]

    def ndn_factory():
        return setup_conf_topo(conf_path, delay_ms, bw_mbps, cores)

    for trial in range(1, trials + 1):
        baseline_done = False
        for pfx_count in prefix_counts:
            for mode in modes:
                # When sweeping prefix counts, baseline (0 prefixes)
                # is identical for every count — run it only once.
                if sweeping and mode == "baseline" and baseline_done:
                    continue
                rows = _run_one_variant(
                    ndn_factory=ndn_factory,
                    topology=topo_name,
                    topo_id_str=topo_name,
                    grid_size=0,
                    num_nodes=num_nodes,
                    num_links=num_links,
                    link_src=link_src,
                    link_dst=link_dst,
                    churn_node=churn_node,
                    trial=trial,
                    mode=mode,
                    num_prefixes=pfx_count,
                    window_s=sim_time,
                    dv_config=dv_config,
                    sim_time=sim_time,
                    deadline=300,
                    out_dir=out_dir,
                    cfg=cfg,
                    all_links=all_links_list,
                    all_nodes=all_nodes_list,
                )
                _write_rows(writer, f, rows)
                if mode == "baseline":
                    baseline_done = True


def _write_rows(writer, f, rows):
    for row in rows:
        writer.writerow(row)
        f.flush()
        print(f"  [{row['phase']}] dv={row['dv_advert_bytes']}B"
              f"  pfx={row['pfxsync_bytes']}B"
              f"  total={row['total_routing_bytes']}B")


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(
        description="Emu: churn scenario — two-phase routing traffic measurement")
    parser.add_argument("--config", required=True,
                        help="JSON scenario config file")
    parser.add_argument("--out", default=None,
                        help="Output directory (auto-derived from config)")
    parser.add_argument("--mode", default=None,
                        help="Run only this mode (baseline/two_step/one_step)")
    parser.add_argument("--prefixes", type=int, default=None,
                        help="Run only this prefix count")
    parser.add_argument("--append", action="store_true",
                        help="Append to CSV instead of overwriting")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]

    cfg = load_config(args.config)
    if args.mode is not None:
        cfg["modes"] = [args.mode]
    if args.prefixes is not None:
        cfg["prefix_counts"] = [args.prefixes]
    dv_config = dv_config_from(cfg)

    topo_name = cfg.get("topology", "grid")

    if args.out is None:
        args.out = default_out_dir(cfg, "emu")
    out_dir = args.out
    os.makedirs(out_dir, exist_ok=True)

    out_csv = os.path.join(out_dir, "churn.csv")
    csv_mode = "a" if args.append and os.path.exists(out_csv) else "w"
    with open(out_csv, csv_mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if csv_mode == "w":
            writer.writeheader()
            f.flush()

        if topo_name == "grid":
            _run_grid(cfg, dv_config, out_dir, writer, f)
        elif topo_name in KNOWN_TOPOLOGIES:
            _run_conf(cfg, dv_config, out_dir, writer, f, topo_name)
        else:
            print(f"Unknown topology '{topo_name}'. "
                  f"Known: grid, {', '.join(KNOWN_TOPOLOGIES)}")
            sys.exit(1)

    print(f"\nResults written to {out_csv}")

    # Auto-generate plots and summary (auto-detects sibling sim dir)
    plot_kind = "prefix_scale" if cfg.get("churn_mode") == "prefix_scaling" else "churn"
    auto_plot(out_dir, emu_dir=out_dir, plot_kind=plot_kind)


if __name__ == "__main__":
    setLogLevel("info")
    main()
