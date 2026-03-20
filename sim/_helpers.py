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
                 link_trace=None, dv_config=None, network="/minindn"):
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
    subprocess.run(build_cmd, cwd=ns3_dir, check=True,
                   capture_output=True, env=env)

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

    cmd_str = f"{TARGET_NAME} " + " ".join(run_args)
    subprocess.run([ns3_bin, "run", cmd_str], cwd=ns3_dir, check=True)


def _file_differs(path_a, path_b):
    """Return True if two files have different contents."""
    with open(path_a, "rb") as a, open(path_b, "rb") as b:
        return a.read() != b.read()
