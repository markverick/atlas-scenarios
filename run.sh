#!/bin/bash
# run.sh -- Unified runner for atlas-scenarios
#
# Usage:
#   ./run.sh [--env twophase|onephase] setup                Install everything from source
#   sudo ./run.sh [--env twophase|onephase] emu demo         3-node file transfer demo
#   sudo ./run.sh [--env twophase|onephase] emu scalability  NxN grid scalability test
#   ./run.sh [--env twophase|onephase] sim demo [opts]       3-node ndndSIM demo
#   ./run.sh [--env twophase|onephase] sim scalability [opts] NxN grid ndndSIM scalability test
#   ./run.sh [--env twophase|onephase] sim prefix_scale [opts] Prefix-scale table study
set -eo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="$REPO_DIR/deps"
NS3_DIR="$DEPS_DIR/ns-3"
PINNED_GO_VERSION="1.24.3"
PINNED_GO_BIN="$DEPS_DIR/gopath/pkg/mod/golang.org/toolchain@v0.0.1-go${PINNED_GO_VERSION}.linux-amd64/bin/go"

RUN_UID="$(id -u)"

# Resolve the non-root user who should own result files.
# Prefer ATLAS_USER (set by ./jobs.sh), fall back to SUDO_USER.
ATLAS_USER="${ATLAS_USER:-$SUDO_USER}"
ATLAS_OWNER_SPEC=""
if [[ -n "$ATLAS_USER" ]]; then
    atlas_group="$(id -gn "$ATLAS_USER" 2>/dev/null)" || {
        echo "ERROR: could not resolve primary group for ATLAS_USER=$ATLAS_USER" >&2
        exit 1
    }
    ATLAS_OWNER_SPEC="$ATLAS_USER:$atlas_group"
fi

# When running as root, ensure experiment result trees are owned by the
# real user before dispatching commands. This prevents stale root-owned
# files from blocking subsequent sim runs.
fix_results_owner() {
    if [[ "$RUN_UID" -eq 0 && -n "$ATLAS_OWNER_SPEC" ]]; then
        local result_dir
        for result_dir in "$REPO_DIR/results" "$REPO_DIR/experiments"/*/results; do
            [[ -d "$result_dir" ]] || continue
            chown -R "$ATLAS_OWNER_SPEC" "$result_dir"
        done
    fi
}

require_atlas_user() {
    if [[ "$RUN_UID" -eq 0 && -z "$ATLAS_USER" ]]; then
        echo "ERROR: ATLAS_USER or SUDO_USER must be set when running this command under sudo" >&2
        exit 1
    fi
}

run_as_atlas_user() {
    require_atlas_user
    if [[ "$RUN_UID" -eq 0 && -n "$ATLAS_USER" ]]; then
        sudo -u "$ATLAS_USER" env "PATH=$PATH" "PYTHONPATH=$PYTHONPATH" "$@"
    else
        "$@"
    fi
}

build_sim_run_cmd() {
    SIM_RUN_CMD=(python3)
    require_atlas_user
    if [[ "$RUN_UID" -eq 0 && -n "$ATLAS_USER" ]]; then
        SIM_RUN_CMD=(sudo -u "$ATLAS_USER" env "PATH=$PATH" "PYTHONPATH=$PYTHONPATH" "NS3_CMAKE_CACHE=$NS3_CMAKE_CACHE" "NS3_BUILD_OUT=$NS3_BUILD_OUT" "NDNDSIM_NO_BUILD=${NDNDSIM_NO_BUILD:-}" python3)
    fi
}

# Put local binaries + the setup-pinned Go toolchain in PATH.
if [[ -x "$PINNED_GO_BIN" ]]; then
    export PATH="$(dirname "$PINNED_GO_BIN"):$DEPS_DIR/bin:$DEPS_DIR/gopath/bin:$PATH"
    export GOTOOLCHAIN=local
else
    export PATH="$DEPS_DIR/bin:$DEPS_DIR/gopath/bin:$PATH"
fi
export PYTHONPATH="$REPO_DIR:$PYTHONPATH"

NDND_SRC="$DEPS_DIR/ndnd-daemon"
GOPATH_DIR="$DEPS_DIR/gopath"

ensure_ns3_ready() {
    local phase="${1:-twophase}"
    if [[ ! -x "$NS3_DIR/ns3" ]]; then
        echo "ERROR: ns-3 not found at $NS3_DIR"
        echo "Run ./setup.sh first"
        exit 1
    fi

    # Sync scenario .cc files from sim/ into ns-3 examples before building,
    # so cmake always compiles the latest sources.
    python3 -c "
import sys
sys.path.insert(0, '$REPO_DIR')
from sim._helpers import sync_scenario, sync_prefix_scale_scenario, sync_multihop_scenario, sync_routing_scenario, sync_churn_scenario
import os
ns3_dir = '$NS3_DIR'
sync_scenario(ns3_dir)
sync_prefix_scale_scenario(ns3_dir)
sync_multihop_scenario(ns3_dir)
sync_routing_scenario(ns3_dir)
sync_churn_scenario(ns3_dir)
"

    if [[ "$phase" == "onephase" ]]; then
        local cmake_cache="$NS3_DIR/cmake-cache-op"
        local build_out="$NS3_DIR/build-op"
        echo "[sim] Configuring ns-3 (onephase)"
        run_as_atlas_user cmake -S "$NS3_DIR" -B "$cmake_cache" \
            -DCMAKE_BUILD_TYPE=release \
            -DNS3_EXAMPLES=ON -DNS3_TESTS=ON \
            -DNDNDSIM_PHASE=onephase \
            "-DNS3_OUTPUT_DIRECTORY=$build_out"
        echo "[sim] Building ns-3 (onephase)"
        run_as_atlas_user cmake --build "$cmake_cache" -j$(nproc)
    else
        local cmake_cache="$NS3_DIR/cmake-cache"
        local build_out="$NS3_DIR/build"
        echo "[sim] Configuring ns-3 (twophase)"
        run_as_atlas_user cmake -S "$NS3_DIR" -B "$cmake_cache" \
            -DCMAKE_BUILD_TYPE=release \
            -DNS3_EXAMPLES=ON -DNS3_TESTS=ON \
            -DNDNDSIM_PHASE=twophase \
            "-DNS3_OUTPUT_DIRECTORY=$build_out"
        echo "[sim] Building ns-3 (twophase)"
        run_as_atlas_user cmake --build "$cmake_cache" -j$(nproc)
    fi
}

# Locate the Go 1.24 toolchain (downloaded by setup into GOPATH).
find_go_bin() {
    local go_bin="$PINNED_GO_BIN"
    if [[ ! -x "$go_bin" ]]; then
        go_bin="$(ls "$GOPATH_DIR"/pkg/mod/golang.org/toolchain@v0.0.1-go1.24.*.linux-amd64/bin/go 2>/dev/null | sort -V | tail -1)"
    fi
    if [[ -z "$go_bin" || ! -x "$go_bin" ]]; then
        echo "ERROR: pinned Go $PINNED_GO_VERSION not found. Run ./setup.sh first." >&2
        return 1
    fi
    echo "$go_bin"
}

# Build the ndnd daemon from the same Go source that ndndSIM uses.
# Called automatically before every emu run so the binary can never be stale.
build_ndnd() {
    local go_bin
    go_bin="$(find_go_bin)"
    local out="$DEPS_DIR/bin/ndnd"
    echo "[emu] Building ndnd daemon from $NDND_SRC (go: $go_bin)"
    mkdir -p "$DEPS_DIR/bin"
    (cd "$NDND_SRC" && run_as_atlas_user env "GOPATH=$GOPATH_DIR" "GOFLAGS=-mod=mod" "$go_bin" build -buildvcs=false -o "$out" ./cmd/ndnd/)
    # Kill any leftover ndnd processes so the binary isn't "text file busy"
    # Retry until file is free (processes may respawn if emulation is still running)
    for _ in $(seq 1 30); do
        pkill -9 -x ndnd 2>/dev/null || true
        sleep 0.3
        if ! lsof /usr/local/bin/ndnd 2>/dev/null | grep -q .; then
            break
        fi
    done
    if [[ "$RUN_UID" -eq 0 ]]; then
        cp "$out" /usr/local/bin/ndnd
    else
        sudo cp "$out" /usr/local/bin/ndnd
    fi
}

# Build the onephase ndnd daemon from the pristine ndnd@main@51774b8 commit
# using a temporary git worktree.  Installs to /usr/local/bin/ndnd-onephase.
build_ndnd_onephase() {
    local go_bin
    go_bin="$(find_go_bin)"
    local hash="51774b8"
    local out="$DEPS_DIR/bin/ndnd-onephase"
    local work_dir
    # Create the temp dir as atlas user so git worktree entries are also
    # atlas-owned.  Running git as root creates root-owned worktree metadata
    # and blocks atlas user from creating subsequent worktrees (needed by the
    # sim build.sh).
    work_dir="$(run_as_atlas_user mktemp -d)"
    echo "[emu] Building ndnd-onephase daemon from $NDND_SRC at $hash (go: $go_bin)"
    mkdir -p "$DEPS_DIR/bin"
    run_as_atlas_user git -C "$NDND_SRC" worktree add --detach "$work_dir" "$hash"
    (cd "$work_dir" && run_as_atlas_user env "GOWORK=off" "GOPATH=$GOPATH_DIR" "GOFLAGS=-mod=mod" "$go_bin" build -buildvcs=false -o "$out" ./cmd/ndnd/)
    run_as_atlas_user git -C "$NDND_SRC" worktree remove --force "$work_dir" 2>/dev/null || true
    run_as_atlas_user rm -rf "$work_dir" 2>/dev/null || true
    pkill -9 -x ndnd-onephase 2>/dev/null || true
    for _ in $(seq 1 20); do
        lsof /usr/local/bin/ndnd-onephase 2>/dev/null | grep -q . || break
        sleep 0.5
    done
    if [[ "$RUN_UID" -eq 0 ]]; then
        cp "$out" /usr/local/bin/ndnd-onephase
    else
        sudo cp "$out" /usr/local/bin/ndnd-onephase
    fi
}

# Build emu/ndnd-traffic from .transformed-ndnd-<phase> (cmd/traffic/ is added
# by the overlay and does not exist in pristine upstream ndnd).
build_ndnd_traffic() {
    local phase="${1:-twophase}"
    local go_bin
    go_bin="$(find_go_bin)"
    local src="$NS3_DIR/contrib/ndndSIM/go/.transformed-ndnd-${phase}"
    local out="$REPO_DIR/emu/ndnd-traffic"
    echo "[emu] Building ndnd-traffic from $src (go: $go_bin)"
    (cd "$src" && run_as_atlas_user env "GOWORK=off" "GOPATH=$GOPATH_DIR" "GOFLAGS=-mod=mod" "$go_bin" build -buildvcs=false -o "$out" ./cmd/traffic/)
}

usage() {
    cat <<'EOF'
Usage: ./run.sh <command> [args...]

Commands:
  setup                      Install all dependencies from source
    as-user <cmd...>           Run a command as the real user when invoked under sudo
  build                      Build all binaries (ns-3, ndnd, ndnd-traffic)
  emu [--no-build] demo      Run 3-node file transfer demo (needs sudo)
  emu [--no-build] scalability [opts]  Run NxN grid scalability test (needs sudo)
  emu [--no-build] routing [opts]      Run routing-only traffic measurement (needs sudo)
  emu [--no-build] prefix_scale [opts] Run core/edge prefix-scale study (needs sudo)
  sim [--no-build] demo [opts]         Run 3-node ndndSIM demo
  sim [--no-build] scalability [opts]  Run NxN grid ndndSIM scalability test
  sim [--no-build] routing [opts]      Run routing-only ndndSIM traffic measurement
    sim [--no-build] prefix_scale [opts] Run prefix-scale table study
Emulation options (emu scalability):
  --grids 2 3 4 5            Grid sizes to test
  --trials 1                 Repetitions per grid size
  --delay 10ms               Per-link delay
  --bw 10                    Per-link bandwidth (Mbps)
  --cores N                  CPU cores per Mininet node (0 = no limit)
  --out results/emu          Output directory

Simulation options (sim scalability):
  --grids 2 3 4 5            Grid sizes to test
  --delay 10                 Per-link delay (ms)
  --sim-time 60              Simulation duration (s)
  --cores N                  Parallel build cores (0 = all)
  --out results/sim          Output directory

Simulation options (sim demo):
  --delay 10                 Per-link delay (ms)
  --sim-time 20              Simulation duration (s)
  --cores N                  Parallel build cores (0 = all)
  --out results/sim          Output directory

Examples:
  ./setup.sh
  sudo ./run.sh emu demo
  sudo ./run.sh emu scalability --grids 2 3 4 --trials 1
  ./run.sh sim demo
  ./run.sh sim scalability --grids 2 3 4
EOF
    exit 1
}

cleanup_minindn() {
    python3 -c "from minindn.minindn import Minindn; Minindn.cleanUp()" 2>/dev/null || true
}

[[ $# -lt 1 ]] && usage

# Global flag: --env twophase|onephase  (default: twophase)
ENV_PHASE="twophase"
if [[ "$1" == "--env" ]]; then
    ENV_PHASE="${2:?--env requires twophase or onephase}"
    shift 2
fi
[[ $# -lt 1 ]] && usage

case "$1" in
    setup)
        exec "$REPO_DIR/setup.sh"
        ;;
    as-user)
        shift
        [[ $# -lt 1 ]] && { echo "Usage: ./run.sh as-user <cmd...>"; exit 1; }
        run_as_atlas_user "$@"
        exit $?
        ;;
    build)
        shift
        echo "[build] Building all binaries (env: $ENV_PHASE)"
        ensure_ns3_ready "$ENV_PHASE"
        build_ndnd
        build_ndnd_onephase
        build_ndnd_traffic "$ENV_PHASE"
        fix_results_owner
        echo "[build] Done"
        exit 0
        ;;
    emu)
        shift
        no_build=false
        [[ "$1" == "--no-build" ]] && { no_build=true; shift; }
        [[ $# -lt 1 ]] && { echo "Usage: ./run.sh emu [--no-build] <subcmd> [opts]"; exit 1; }
        subcmd="$1"; shift
        [[ "$subcmd" != *.py ]] && subcmd="${subcmd}.py"
        cleanup_minindn
        if ! $no_build; then
            if [[ "$ENV_PHASE" == "onephase" ]]; then
                build_ndnd_onephase
            else
                build_ndnd
            fi
            build_ndnd_traffic "$ENV_PHASE"
        fi
        export NDND_PHASE="$ENV_PHASE"
        export NDND_SRC="$NDND_SRC"

        rc=0
        python3 "$REPO_DIR/emu/$subcmd" "$@" || rc=$?

        fix_results_owner
        exit $rc
        ;;
    sim)
        shift
        no_build=false
        [[ "$1" == "--no-build" ]] && { no_build=true; shift; }
        [[ $# -lt 1 ]] && { echo "Usage: ./run.sh sim [--no-build] <subcmd> [opts]"; exit 1; }
        subcmd="$1"; shift
        [[ "$subcmd" != *.py ]] && subcmd="${subcmd}.py"

        fix_results_owner
        if ! $no_build; then
            ensure_ns3_ready "$ENV_PHASE"
        fi

        if [[ "$ENV_PHASE" == "onephase" ]]; then
            export NS3_CMAKE_CACHE="cmake-cache-op"
            export NS3_BUILD_OUT="build-op"
        else
            export NS3_CMAKE_CACHE="cmake-cache"
            export NS3_BUILD_OUT="build"
        fi

        if $no_build; then
            export NDNDSIM_NO_BUILD=1
        else
            unset NDNDSIM_NO_BUILD
        fi

        build_sim_run_cmd
        exec "${SIM_RUN_CMD[@]}" "$REPO_DIR/sim/$subcmd" --ns3-dir "$NS3_DIR" "$@"
        ;;
    both)
        shift
        [[ $# -lt 1 ]] && { echo "Usage: sudo ./run.sh both <demo|scalability> [opts]"; exit 1; }
        subcmd="$1"; shift

        # Must be run as root (emu needs sudo; sim will drop privs internally)
        [[ "$RUN_UID" -ne 0 ]] && { echo "ERROR: 'both' must be run with sudo"; exit 1; }

        [[ "$subcmd" != *.py ]] && subcmd="${subcmd}.py"

        echo "=== Running emulation ==="
        cleanup_minindn
        build_ndnd
        build_ndnd_traffic "$ENV_PHASE"
        rc=0
        python3 "$REPO_DIR/emu/$subcmd" "$@" || rc=$?
        fix_results_owner
        [[ $rc -ne 0 ]] && exit $rc

        echo "=== Running simulation ==="
        ensure_ns3_ready "$ENV_PHASE"
        if [[ "$ENV_PHASE" == "onephase" ]]; then
            export NS3_CMAKE_CACHE="cmake-cache-op"
            export NS3_BUILD_OUT="build-op"
        else
            export NS3_CMAKE_CACHE="cmake-cache"
            export NS3_BUILD_OUT="build"
        fi
        export NDNDSIM_NO_BUILD=1
        build_sim_run_cmd
        "${SIM_RUN_CMD[@]}" "$REPO_DIR/sim/$subcmd" --ns3-dir "$NS3_DIR" "$@"

        ;;
    *)
        usage
        ;;
esac
