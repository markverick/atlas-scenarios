"""
Shared helpers for ndndSIM simulation scenarios.

Provides ns-3 directory resolution, scenario installation,
and parameterized scenario execution.
"""

import json
import os
import re
import shutil
import subprocess
import textwrap

from lib.result_adapter import parse_conv_trace

# Default ns-3 directory: deps/ns-3 relative to this repo
DEFAULT_NS3_DIR = os.path.join(os.path.dirname(__file__), "..", "deps", "ns-3")
_REPO_DIR = os.path.join(os.path.dirname(__file__), "..")

TARGET_NAME = "ndndsim-atlas-scenario"
CC_FILENAME = f"{TARGET_NAME}.cc"

MULTIHOP_TARGET_NAME = "ndndsim-atlas-multihop-scenario"
MULTIHOP_CC_FILENAME = f"{MULTIHOP_TARGET_NAME}.cc"

ROUTING_TARGET_NAME = "ndndsim-atlas-routing-scenario"
ROUTING_CC_FILENAME = f"{ROUTING_TARGET_NAME}.cc"

PREFIX_SCALE_TARGET_NAME = "ndndsim-atlas-prefix-scale-scenario"
PREFIX_SCALE_CC_FILENAME = f"{PREFIX_SCALE_TARGET_NAME}.cc"

CHURN_TARGET_NAME = "ndndsim-atlas-churn-scenario"
CHURN_CC_FILENAME = f"{CHURN_TARGET_NAME}.cc"


def resolve_ns3_dir(ns3_dir_arg=None):
    """Return absolute path to ns-3 root, or exit on failure."""
    ns3_dir = ns3_dir_arg or os.environ.get("NS3_DIR") or DEFAULT_NS3_DIR
    ns3_dir = os.path.abspath(ns3_dir)
    ns3_bin = os.path.join(ns3_dir, "ns3")
    if not os.path.isfile(ns3_bin):
        raise SystemExit(f"ERROR: {ns3_bin} not found")
    return ns3_dir


def sync_scenario(ns3_dir):
    """Ensure atlas-scenario.cc is installed and registered in ns-3.

    Copies the C++ source from the repo into the ndndSIM examples directory
    and appends a CMakeLists.txt entry if not already present.
    Idempotent and fast -- safe to call on every run.
    """
    _sync_target(ns3_dir, "atlas-scenario.cc", TARGET_NAME, CC_FILENAME,
                 "Atlas general-purpose scenario")


def _sync_target(ns3_dir, src_basename, target_name, cc_filename, cmake_comment):
    """Install a single C++ scenario source into ndndSIM/examples and register it."""
    src = os.path.join(os.path.abspath(_REPO_DIR), "sim", src_basename)
    dst_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "examples")
    dst = os.path.join(dst_dir, cc_filename)

    # Copy .cc if missing or outdated
    if not os.path.isfile(dst) or _file_differs(src, dst):
        shutil.copy2(src, dst)
        # Ensure dest mtime is updated so cmake detects the change
        os.utime(dst, None)

    # Register in CMakeLists.txt if needed
    cmake_path = os.path.join(dst_dir, "CMakeLists.txt")
    with open(cmake_path) as f:
        cmake_text = f.read()

    # Remove stale targets from previous approach
    for stale in ("ndndsim-atlas-demo", "ndndsim-atlas-scalability"):
        pattern = rf"\n# [^\n]*\nbuild_lib_example\(\s*NAME {stale}\b.*?\)\n"
        cmake_text = re.sub(pattern, "\n", cmake_text, flags=re.DOTALL)
        stale_cc = os.path.join(dst_dir, f"{stale}.cc")
        if os.path.isfile(stale_cc):
            os.remove(stale_cc)

    if target_name not in cmake_text:
        cmake_text += textwrap.dedent(f"""
            # {cmake_comment}
            build_lib_example(
                NAME {target_name}
                SOURCE_FILES {cc_filename}
                LIBRARIES_TO_LINK
                    ${{libndndSIM}}
                    ${{libcore}}
                    ${{libnetwork}}
                    ${{libinternet}}
                    ${{libpoint-to-point}}
            )
        """)

    # Write back if anything changed
    with open(cmake_path) as f:
        current = f.read()
    if current != cmake_text:
        with open(cmake_path, "w") as f:
            f.write(cmake_text)


def run_scenario(ns3_dir, *, topo, rate_trace, sim_time=60.0,
                 consumer=None, producer=None, prefix="/ndn/test",
                 frequency=10.0, cores=0, conv_trace=None,
                 link_trace=None, dv_config=None, network="/minindn",
                 run_log=None, require_convergence=True):
    """Build ns-3 and run the atlas scenario with the given parameters.

    Args:
        ns3_dir:    Absolute path to ns-3 root.
        topo:       Topology file path (relative to ns3_dir or absolute).
        rate_trace: Output rate-trace CSV path (absolute).
        sim_time:   Simulation duration in seconds.
        consumer:   Consumer node name (None -> first node in topology).
        producer:   Producer node name (None -> last node in topology).
        prefix:     NDN name prefix.
        frequency:  Consumer Interest frequency in Hz.
        cores:      Parallel build cores (0 = all available).
        conv_trace: Output convergence time file path (absolute).
        link_trace: Output link traffic CSV path (absolute).
        dv_config:  Dict of DV config overrides (JSON keys from Go config).
        run_log:    Optional path to capture scenario stdout/stderr logs.
        require_convergence: Whether conv_trace must report a non-negative value.
    """
    sync_scenario(ns3_dir)
    _build_ns3(ns3_dir, cores)

    if not os.path.isabs(topo):
        topo = os.path.join(ns3_dir, topo)
    topo = os.path.abspath(topo)

    run_args = [
        f"--topo={topo}",
        f"--rateTrace={rate_trace}",
        f"--simTime={sim_time}",
        f"--prefix={prefix}",
        f"--frequency={frequency}",
        f"--network={network}",
    ]
    if consumer:
        run_args.append(f"--consumer={consumer}")
    if producer:
        run_args.append(f"--producer={producer}")
    if conv_trace:
        run_args.append(f"--convTrace={conv_trace}")
    if link_trace:
        run_args.append(f"--linkTrace={link_trace}")
    if dv_config:
        run_args.append(f"--dvConfig={json.dumps(dv_config, separators=(',', ':'))}")

    _run_exe(_find_scenario_exe(ns3_dir, "ndndsim-atlas-scenario"),
             run_args, run_log)

    # --- Validate outputs -- a silent empty file is a hidden failure ---------
    errors = []

    # rate_trace must have at least one data row (not just the header)
    if os.path.isfile(rate_trace):
        with open(rate_trace) as f:
            lines = [l for l in f if l.strip()]
        if len(lines) <= 1:
            errors.append(
                f"rate_trace '{rate_trace}' has no data rows (only header or empty) -- "
                "simulation likely produced no traffic at all"
            )
    else:
        errors.append(f"rate_trace '{rate_trace}' was not created by the simulation")

    # conv_trace must contain a non-negative convergence value when required
    if conv_trace:
        if os.path.isfile(conv_trace):
            try:
                val = parse_conv_trace(conv_trace)
                if val < 0 and require_convergence:
                    errors.append(
                        f"conv_trace '{conv_trace}' reports convergence=-1 -- "
                        "DV routing never converged during the simulation"
                    )
            except (ValueError, OSError) as exc:
                errors.append(f"conv_trace '{conv_trace}' is unreadable: {exc}")
        else:
            errors.append(f"conv_trace '{conv_trace}' was not created by the simulation")

    # link_trace must have at least one data row
    if link_trace:
        if os.path.isfile(link_trace):
            with open(link_trace) as f:
                lines = [l for l in f if l.strip()]
            if len(lines) <= 1:
                errors.append(
                    f"link_trace '{link_trace}' has no data rows -- "
                    "no packets were traced on any link"
                )
        else:
            errors.append(f"link_trace '{link_trace}' was not created by the simulation")

    if errors:
        raise RuntimeError(
            "Simulation completed but produced invalid output:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def _file_differs(path_a, path_b):
    """Return True if two files have different contents."""
    with open(path_a, "rb") as a, open(path_b, "rb") as b:
        return a.read() != b.read()


def _walk_go_sources(root):
    """Yield absolute paths of all non-test .go files under root."""
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(".go") and not name.endswith("_test.go"):
                yield os.path.join(dirpath, name)


def _build_ns3(ns3_dir, cores=0):
    """Build ns-3 with Go on PATH and check Go source freshness.

    When the NS3_CMAKE_CACHE environment variable is set, cmake is invoked
    directly against that cache directory (for the onephase build and any
    other alternate build directories).  Otherwise the standard ``./ns3 build``
    wrapper is used.

    NS3_BUILD_OUT (default: "build") controls which output directory to check
    for staleness.
    """
    env = os.environ.copy()
    go_dir = "/usr/local/go/bin"
    if os.path.isfile(os.path.join(go_dir, "go")) and go_dir not in env.get("PATH", ""):
        env["PATH"] = go_dir + ":" + env.get("PATH", "")

    # Allow callers (e.g. the integration test) to skip the build step when
    # they have already built explicitly in a prior stage.
    if os.environ.get("NDNDSIM_NO_BUILD"):
        return

    cmake_cache = os.environ.get("NS3_CMAKE_CACHE", "")
    if cmake_cache:
        # Direct cmake build for alternate configurations (e.g. onephase).
        cmake_cache_path = os.path.join(ns3_dir, cmake_cache)
        build_cmd = ["cmake", "--build", cmake_cache_path]
        if cores > 0:
            build_cmd += ["--parallel", str(cores)]
    else:
        # Standard ns3 build (default twophase).
        ns3_bin = os.path.join(ns3_dir, "ns3")
        build_cmd = [ns3_bin, "build"]
        if cores > 0:
            build_cmd += ["-j", str(cores)]
    subprocess.run(build_cmd, cwd=ns3_dir, check=True, env=env)

    build_out = os.environ.get("NS3_BUILD_OUT", "build")
    so_path = os.path.join(ns3_dir, build_out, "lib", "libns3.47-ndndSIM.so")
    ndnd_sim_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "ndnd", "sim")
    if os.path.isfile(so_path) and os.path.isdir(ndnd_sim_dir):
        so_mtime = os.path.getmtime(so_path)
        stale = [
            f for f in _walk_go_sources(ndnd_sim_dir)
            if os.path.getmtime(f) > so_mtime
        ]
        if stale:
            rel = [os.path.relpath(f, ns3_dir) for f in stale]
            raise RuntimeError(
                "Go source files are newer than the built shared library -- "
                "cmake dependency tracking missed them. "
                "Re-run cmake configure then build again.\n"
                "Stale sources:\n" + "\n".join(f"  {r}" for r in rel)
            )


def _find_scenario_exe(ns3_dir, target_substr):
    """Find the built ns-3 scenario executable containing target_substr.

    Respects the NS3_BUILD_OUT environment variable (default: "build") so that
    alternate build directories (e.g. "build-op" for the onephase environment)
    are searched correctly.
    """
    build_out = os.environ.get("NS3_BUILD_OUT", "build")
    build_dir = os.path.join(ns3_dir, build_out)
    # ns-3 cmake produces executables named "ns3.<ver>-<name>" with no suffix.
    # Exclude the "-default" suffix variant which is a stale artifact from
    # pre-phase-split builds.
    candidates = []
    for root, _dirs, files in os.walk(os.path.join(build_dir, "contrib/ndndSIM")):
        for f in files:
            if f.startswith("ns3.") and target_substr in f and not f.endswith("-default"):
                candidates.append(os.path.join(root, f))

    if not candidates:
        # Fall back to any match (including -default) if no non-default binary exists.
        for root, _dirs, files in os.walk(os.path.join(build_dir, "contrib/ndndSIM")):
            for f in files:
                if f.startswith("ns3.") and target_substr in f:
                    candidates.append(os.path.join(root, f))

    if not candidates:
        raise RuntimeError(
            f"{target_substr} executable not found in {build_dir}/contrib/ndndSIM/"
        )

    if len(candidates) > 1:
        raise RuntimeError(
            f"Ambiguous {target_substr} executables found (expected exactly one): "
            + ", ".join(candidates)
        )

    return candidates[0]


def _run_exe(exe, run_args, run_log=None):
    """Run a scenario executable, optionally capturing output to a log file."""
    if run_log:
        os.makedirs(os.path.dirname(os.path.abspath(run_log)), exist_ok=True)
        with open(run_log, "w") as lf:
            subprocess.run([exe] + run_args, check=True, stdout=lf, stderr=lf)
    else:
        subprocess.run([exe] + run_args, check=True, capture_output=False)


def sync_multihop_scenario(ns3_dir):
    """Ensure atlas-multihop-scenario.cc is installed and registered in ns-3."""
    _sync_target(ns3_dir, "atlas-multihop-scenario.cc",
                 MULTIHOP_TARGET_NAME, MULTIHOP_CC_FILENAME,
                 "Atlas multi-hop DV routing changes scenario")


def run_multihop_scenario(ns3_dir, *, topo, results_file, rate_trace,
                          prefix="/app/data", network="/minindn",
                          consumer="a", producer="d",
                          link_down_src="b", link_down_dst="c",
                          sim_time=90.0, dv_config=None,
                          cores=0, run_log=None):
    """Build ns-3 and run the multihop scenario.

    Args:
        ns3_dir:      Absolute path to ns-3 root.
        topo:         Topology file path (relative to ns3_dir or absolute).
        results_file: Output JSON results path (absolute).
        rate_trace:   Output rate-trace CSV path (absolute).
        prefix:       App prefix to test.
        network:      DV network prefix.
        consumer:     Consumer node name.
        producer:     Producer node name.
        link_down_src:  Source node of link to fail.
        link_down_dst:  Destination node of link to fail.
        sim_time:     Total simulation time in seconds.
        dv_config:    Dict of DV config overrides.
        cores:        Parallel build cores (0 = all).
        run_log:      Optional path to capture stdout/stderr.
    """
    sync_scenario(ns3_dir)
    sync_multihop_scenario(ns3_dir)
    _build_ns3(ns3_dir, cores)

    if not os.path.isabs(topo):
        topo = os.path.join(ns3_dir, topo)
    topo = os.path.abspath(topo)

    run_args = [
        f"--topo={topo}",
        f"--resultsFile={results_file}",
        f"--rateTrace={rate_trace}",
        f"--prefix={prefix}",
        f"--network={network}",
        f"--consumer={consumer}",
        f"--producer={producer}",
        f"--linkDownSrc={link_down_src}",
        f"--linkDownDst={link_down_dst}",
        f"--simTime={sim_time}",
    ]
    if dv_config:
        run_args.append(f"--dvConfig={json.dumps(dv_config, separators=(',', ':'))}")

    _run_exe(_find_scenario_exe(ns3_dir, "ndndsim-atlas-multihop-scenario"),
             run_args, run_log)

    # Validate results file was created
    if not os.path.isfile(results_file):
        raise RuntimeError(
            f"Results file '{results_file}' was not created by the simulation"
        )


def sync_routing_scenario(ns3_dir):
    """Ensure atlas-routing-scenario.cc is installed and registered in ns-3."""
    _sync_target(ns3_dir, "atlas-routing-scenario.cc",
                 ROUTING_TARGET_NAME, ROUTING_CC_FILENAME,
                 "Atlas routing-only scenario (no app traffic)")


def sync_prefix_scale_scenario(ns3_dir):
    """Ensure atlas-prefix-scale-scenario.cc is installed and registered in ns-3."""
    _sync_target(ns3_dir, "atlas-prefix-scale-scenario.cc",
                 PREFIX_SCALE_TARGET_NAME, PREFIX_SCALE_CC_FILENAME,
                 "Atlas core-edge prefix-scale scenario")


def run_routing_scenario(ns3_dir, *, topo, sim_time=30.0, cores=0,
                         conv_trace=None, link_trace=None, packet_trace=None,
                         dv_config=None, network="/minindn",
                         num_prefixes=0,
                         run_log=None):
    """Build ns-3 and run the routing-only scenario (no app traffic)."""
    sync_scenario(ns3_dir)
    sync_routing_scenario(ns3_dir)
    _build_ns3(ns3_dir, cores)

    if not os.path.isabs(topo):
        topo = os.path.join(ns3_dir, topo)
    topo = os.path.abspath(topo)

    run_args = [
        f"--topo={topo}",
        f"--simTime={sim_time}",
        f"--network={network}",
    ]
    if conv_trace:
        run_args.append(f"--convTrace={conv_trace}")
    if link_trace:
        run_args.append(f"--linkTrace={link_trace}")
    if packet_trace:
        run_args.append(f"--packetTrace={packet_trace}")
    if dv_config:
        run_args.append(f"--dvConfig={json.dumps(dv_config, separators=(',', ':'))}")
    if num_prefixes > 0:
        run_args.append(f"--numPrefixes={num_prefixes}")

    _run_exe(_find_scenario_exe(ns3_dir, "ndndsim-atlas-routing-scenario"),
             run_args, run_log)

    errors = []

    if conv_trace:
        if not os.path.isfile(conv_trace):
            errors.append(f"conv_trace '{conv_trace}' was not created by the simulation")
        else:
            try:
                val = parse_conv_trace(conv_trace)
                if val < 0:
                    errors.append(
                        f"conv_trace '{conv_trace}' reports convergence=-1 -- "
                        "DV routing never converged during the simulation"
                    )
            except (ValueError, OSError) as exc:
                errors.append(f"conv_trace '{conv_trace}' is unreadable: {exc}")

    if link_trace:
        if not os.path.isfile(link_trace):
            errors.append(f"link_trace '{link_trace}' was not created by the simulation")
        else:
            with open(link_trace) as f:
                lines = [l for l in f if l.strip()]
            if len(lines) <= 1:
                errors.append(
                    f"link_trace '{link_trace}' has no data rows -- "
                    "no packets were traced on any link"
                )

    if errors:
        raise RuntimeError(
            "Routing simulation completed but produced invalid output:\n"
            + "\n".join(f"  - {error}" for error in errors)
        )


def run_prefix_scale_scenario(ns3_dir, *, topo, edge_nodes, sim_time=40.0,
                              cores=0, conv_trace=None, link_trace=None,
                              table_trace=None, drop_trace=None, dv_config=None,
                              core_dv_config=None, edge_dv_config=None,
                              network="/minindn", num_prefixes=0,
                              stable_window=None,
                              announce_gap_ms=0.0,
                              run_log=None):
    """Build ns-3 and run the generic prefix-scale table scenario.

    Args:
        stable_window:  Stability window in seconds for the event-driven prefix
                        convergence checker.  Must be >= 2 * DV adv_interval to avoid
                        stopping during inter-advertisement gaps.
        announce_gap_ms: Gap in milliseconds between successive edge-node prefix
                        announcements.  0 (default) = all nodes announce at once.
    """
    if not edge_nodes:
        raise ValueError("edge_nodes must not be empty")

    sync_prefix_scale_scenario(ns3_dir)
    _build_ns3(ns3_dir, cores)

    if not os.path.isabs(topo):
        topo = os.path.join(ns3_dir, topo)
    topo = os.path.abspath(topo)

    run_args = [
        f"--topo={topo}",
        f"--simTime={sim_time}",
        f"--network={network}",
        f"--edgeNodes={','.join(edge_nodes)}",
        f"--numPrefixes={num_prefixes}",
    ]
    if conv_trace:
        run_args.append(f"--convTrace={conv_trace}")
    if link_trace:
        run_args.append(f"--linkTrace={link_trace}")
    if table_trace:
        run_args.append(f"--tableTrace={table_trace}")
    if drop_trace:
        run_args.append(f"--dropTrace={drop_trace}")
    if dv_config:
        run_args.append(f"--dvConfig={json.dumps(dv_config, separators=(',', ':'))}")
    if core_dv_config:
        run_args.append(
            f"--coreDvConfig={json.dumps(core_dv_config, separators=(',', ':'))}"
        )
    if edge_dv_config:
        run_args.append(
            f"--edgeDvConfig={json.dumps(edge_dv_config, separators=(',', ':'))}"
        )
    if stable_window is not None:
        run_args.append(f"--stableWindow={stable_window}")
    if announce_gap_ms:
        run_args.append(f"--announceGap={announce_gap_ms}")

    _run_exe(_find_scenario_exe(ns3_dir, PREFIX_SCALE_TARGET_NAME),
             run_args, run_log)

    errors = []

    if conv_trace:
        if not os.path.isfile(conv_trace):
            errors.append(f"conv_trace '{conv_trace}' was not created by the simulation")
        else:
            try:
                val = parse_conv_trace(conv_trace)
                if val < 0:
                    errors.append(
                        f"conv_trace '{conv_trace}' reports convergence=-1 -- "
                        "DV routing never converged during the simulation"
                    )
            except (ValueError, OSError) as exc:
                errors.append(f"conv_trace '{conv_trace}' is unreadable: {exc}")

    if link_trace:
        if not os.path.isfile(link_trace):
            errors.append(f"link_trace '{link_trace}' was not created by the simulation")
        else:
            with open(link_trace) as f:
                lines = [l for l in f if l.strip()]
            if len(lines) <= 1:
                errors.append(
                    f"link_trace '{link_trace}' has no data rows -- "
                    "no packets were traced on any link"
                )

    if table_trace:
        if not os.path.isfile(table_trace):
            errors.append(f"table_trace '{table_trace}' was not created by the simulation")
        else:
            with open(table_trace) as f:
                lines = [l for l in f if l.strip()]
            if len(lines) <= 1:
                errors.append(
                    f"table_trace '{table_trace}' has no data rows -- "
                    "per-node table metrics were not recorded"
                )

    if errors:
        raise RuntimeError(
            "Prefix-scale simulation completed but produced invalid output:\n"
            + "\n".join(f"  - {error}" for error in errors)
        )


def sync_churn_scenario(ns3_dir):
    """Ensure atlas-churn-scenario.cc is installed and registered in ns-3."""
    _sync_target(ns3_dir, "atlas-churn-scenario.cc",
                 CHURN_TARGET_NAME, CHURN_CC_FILENAME,
                 "Atlas two-phase churn scenario")


def run_churn_scenario(ns3_dir, *, topo, sim_time=60.0, cores=0,
                       conv_trace=None, link_trace=None, packet_trace=None,
                       event_log=None, churn_start_trace=None,
                       suppress_trace=None,
                       suppress_phase_start=None,
                       dv_config=None, network="/minindn",
                       num_prefixes=0, churn_events=None,
                       churn_after_convergence=False, churn_margin=10.0,
                       churn_duration=0.0,
                       run_log=None):
    """Build ns-3 and run the churn scenario.

    Args:
        churn_events: list of dicts, each with keys: time, type, and
                      type-specific fields (src/dst for link events,
                      node/prefix for prefix events).
        churn_after_convergence: if True, churn events are deferred until
            DV convergence + churn_margin seconds.  Event times are
            treated as relative offsets from the churn start.
        churn_margin: seconds to wait after convergence before churn.
        churn_duration: churn phase length in seconds.  When > 0 and
            churn_after_convergence is True, the sim stops dynamically
            at convergence + margin + duration instead of at sim_time.
        churn_start_trace: output file path for the actual churn start time.
    """
    sync_scenario(ns3_dir)
    sync_routing_scenario(ns3_dir)
    sync_churn_scenario(ns3_dir)
    _build_ns3(ns3_dir, cores)

    if not os.path.isabs(topo):
        topo = os.path.join(ns3_dir, topo)
    topo = os.path.abspath(topo)

    run_args = [
        f"--topo={topo}",
        f"--simTime={sim_time}",
        f"--network={network}",
    ]
    if conv_trace:
        run_args.append(f"--convTrace={conv_trace}")
    if link_trace:
        run_args.append(f"--linkTrace={link_trace}")
    if packet_trace:
        run_args.append(f"--packetTrace={packet_trace}")
    if event_log:
        run_args.append(f"--eventLog={event_log}")
    if churn_start_trace:
        run_args.append(f"--churnStartTrace={churn_start_trace}")
    if suppress_trace:
        run_args.append(f"--suppressTrace={suppress_trace}")
    if suppress_phase_start is not None:
        run_args.append(f"--suppressPhaseStart={suppress_phase_start}")
    if dv_config:
        run_args.append(f"--dvConfig={json.dumps(dv_config, separators=(',', ':'))}")
    if num_prefixes > 0:
        run_args.append(f"--numPrefixes={num_prefixes}")
    if churn_events:
        run_args.append(f"--churnEvents={json.dumps(churn_events, separators=(',', ':'))}")
    if churn_after_convergence:
        run_args.append("--churnAfterConvergence=true")
        run_args.append(f"--churnMargin={churn_margin}")
        if churn_duration > 0:
            run_args.append(f"--churnDuration={churn_duration}")

    _run_exe(_find_scenario_exe(ns3_dir, "ndndsim-atlas-churn-scenario"),
             run_args, run_log)
