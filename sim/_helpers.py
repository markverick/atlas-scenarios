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

# Default ns-3 directory: deps/ns-3 relative to this repo
DEFAULT_NS3_DIR = os.path.join(os.path.dirname(__file__), "..", "deps", "ns-3")
_REPO_DIR = os.path.join(os.path.dirname(__file__), "..")

TARGET_NAME = "ndndsim-atlas-scenario"
CC_FILENAME = f"{TARGET_NAME}.cc"


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
    Idempotent and fast — safe to call on every run.
    """
    src = os.path.join(os.path.abspath(_REPO_DIR), "sim", "atlas-scenario.cc")
    dst_dir = os.path.join(ns3_dir, "contrib", "ndndSIM", "examples")
    dst = os.path.join(dst_dir, CC_FILENAME)

    # Copy .cc if missing or outdated
    if not os.path.isfile(dst) or _file_differs(src, dst):
        shutil.copy2(src, dst)

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

    if TARGET_NAME not in cmake_text:
        cmake_text += textwrap.dedent(f"""
            # Atlas general-purpose scenario
            build_lib_example(
                NAME {TARGET_NAME}
                SOURCE_FILES {CC_FILENAME}
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
                 run_log=None):
    """Build ns-3 and run the atlas scenario with the given parameters.

    Args:
        ns3_dir:    Absolute path to ns-3 root.
        topo:       Topology file path (relative to ns3_dir or absolute).
        rate_trace: Output rate-trace CSV path (absolute).
        sim_time:   Simulation duration in seconds.
        consumer:   Consumer node name (None → first node in topology).
        producer:   Producer node name (None → last node in topology).
        prefix:     NDN name prefix.
        frequency:  Consumer Interest frequency in Hz.
        cores:      Parallel build cores (0 = all available).
        conv_trace: Output convergence time file path (absolute).
        link_trace: Output link traffic CSV path (absolute).
        dv_config:  Dict of DV config overrides (JSON keys from Go config).
        run_log:    Optional path to capture scenario stdout/stderr logs.
    """
    sync_scenario(ns3_dir)

    # Ensure Go 1.24+ is in PATH for the CGo build step
    env = os.environ.copy()
    go_dir = "/usr/local/go/bin"
    if os.path.isfile(os.path.join(go_dir, "go")) and go_dir not in env.get("PATH", ""):
        env["PATH"] = go_dir + ":" + env.get("PATH", "")

    ns3_bin = os.path.join(ns3_dir, "ns3")
    build_cmd = [ns3_bin, "build"]
    if cores > 0:
        build_cmd += ["-j", str(cores)]
    subprocess.run(build_cmd, cwd=ns3_dir, check=True, env=env)

    # ── Freshness check: fail loudly if Go sources are newer than the built artifact ──
    # cmake's GLOB_RECURSE is evaluated at configure time, not build time. If you add
    # a new .go file without re-running cmake configure, the archive won't be rebuilt.
    # This check catches that and any other cmake dependency-tracking gap.
    so_path = os.path.join(ns3_dir, "build", "lib", "libns3.47-ndndSIM.so")
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
                "Go source files are newer than the built shared library — "
                "cmake dependency tracking missed them. "
                "Re-run cmake configure (./ns3 configure) then build again.\n"
                "Stale sources:\n" + "\n".join(f"  {r}" for r in rel)
            )

    # Resolve topo path: if not absolute, make it relative to ns3_dir
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

    # Find and run the scenario executable directly (not through ns3 wrapper)
    # The binary is built as ns3.47-ndndsim-atlas-scenario-default
    scenario_exe = None
    build_dir = os.path.join(ns3_dir, "build")
    for root, dirs, files in os.walk(os.path.join(build_dir, "contrib/ndndSIM")):
        for f in files:
            if f.startswith("ns3.") and "ndndsim-atlas-scenario" in f and f.endswith("-default"):
                scenario_exe = os.path.join(root, f)
                break
        if scenario_exe:
            break

    if not scenario_exe:
        raise RuntimeError(
            f"ndndsim-atlas-scenario executable not found in {build_dir}/contrib/ndndSIM/"
        )

    if run_log:
        os.makedirs(os.path.dirname(os.path.abspath(run_log)), exist_ok=True)
        with open(run_log, "w") as lf:
            subprocess.run([scenario_exe] + run_args, check=True,
                           stdout=lf, stderr=lf)
    else:
        subprocess.run([scenario_exe] + run_args, check=True, capture_output=False)

    # ── Validate outputs — a silent empty file is a hidden failure ────────────
    errors = []

    # rate_trace must have at least one data row (not just the header)
    if os.path.isfile(rate_trace):
        with open(rate_trace) as f:
            lines = [l for l in f if l.strip()]
        if len(lines) <= 1:
            errors.append(
                f"rate_trace '{rate_trace}' has no data rows (only header or empty) — "
                "simulation likely produced no traffic at all"
            )
    else:
        errors.append(f"rate_trace '{rate_trace}' was not created by the simulation")

    # conv_trace must contain a non-negative float (DV must converge)
    if conv_trace:
        if os.path.isfile(conv_trace):
            try:
                val = float(open(conv_trace).read().strip())
                if val < 0:
                    errors.append(
                        f"conv_trace '{conv_trace}' reports convergence=-1 — "
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
                    f"link_trace '{link_trace}' has no data rows — "
                    "no packets were traced on any link"
                )
        else:
            errors.append(f"link_trace '{link_trace}' was not created by the simulation")

    if errors:
        raise RuntimeError(
            "Simulation completed but produced invalid output:\n"
            + "\n".join(f"  • {e}" for e in errors)
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
