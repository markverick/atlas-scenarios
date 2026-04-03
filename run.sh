#!/bin/bash
# run.sh -- Unified runner for atlas-scenarios
#
# Usage:
#   ./run.sh setup                           Install everything from source
#   sudo ./run.sh emu demo                   3-node file transfer demo
#   sudo ./run.sh emu scalability [opts]     NxN grid scalability test
#   ./run.sh sim demo [opts]                 3-node ndndSIM demo
#   ./run.sh sim scalability [opts]          NxN grid ndndSIM scalability test
set -eo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="$REPO_DIR/deps"
NS3_DIR="$DEPS_DIR/ns-3"

# Resolve the non-root user who should own result files.
# Prefer ATLAS_USER (set by ./jobs.sh), fall back to SUDO_USER.
ATLAS_USER="${ATLAS_USER:-$SUDO_USER}"

# When running as root, ensure experiment result trees are owned by the
# real user before dispatching commands. This prevents stale root-owned
# files from blocking subsequent sim runs.
fix_results_owner() {
    if [[ $EUID -eq 0 && -n "$ATLAS_USER" ]]; then
        local result_dir
        for result_dir in "$REPO_DIR/results" "$REPO_DIR/experiments"/*/results; do
            [[ -d "$result_dir" ]] || continue
            chown -R "$ATLAS_USER:$ATLAS_USER" "$result_dir" 2>/dev/null || true
        done
    fi
}

# Put local binaries + Go in PATH
if [[ -x /usr/local/go/bin/go ]]; then
    export PATH="/usr/local/go/bin:$PATH"
fi
export PATH="$DEPS_DIR/bin:$DEPS_DIR/gopath/bin:$PATH"
export PYTHONPATH="$REPO_DIR:$PYTHONPATH"

NDND_SRC="$NS3_DIR/contrib/ndndSIM/ndnd"
GOPATH_DIR="$DEPS_DIR/gopath"

ensure_ns3_ready() {
    if [[ ! -x "$NS3_DIR/ns3" ]]; then
        echo "ERROR: ns-3 not found at $NS3_DIR"
        echo "Run ./setup.sh first"
        exit 1
    fi

    # Reconfigure each run so newly-added Go files are picked up by cmake globs.
    local ns3_cmd=(./ns3)
    if [[ $EUID -eq 0 && -n "$ATLAS_USER" ]]; then
        ns3_cmd=(sudo -u "$ATLAS_USER" env "PATH=$PATH" ./ns3)
    fi

    echo "[sim] Configuring ns-3"
    (cd "$NS3_DIR" && "${ns3_cmd[@]}" configure -d release)

    echo "[sim] Building ns-3"
    (cd "$NS3_DIR" && "${ns3_cmd[@]}" build)
}

# Locate the Go 1.25 toolchain (downloaded by setup into GOPATH).
find_go_bin() {
    local go_bin
    go_bin="$(ls "$GOPATH_DIR"/pkg/mod/golang.org/toolchain@v0.0.1-go1.25.*.linux-amd64/bin/go 2>/dev/null | sort -V | tail -1)"
    if [[ -z "$go_bin" || ! -x "$go_bin" ]]; then
        go_bin="$(command -v go)"   # fallback to system Go
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
    (cd "$NDND_SRC" && GOPATH="$GOPATH_DIR" GOFLAGS=-mod=mod "$go_bin" build -buildvcs=false -o "$out" ./cmd/ndnd/)
    # Kill any leftover ndnd processes so the binary isn't "text file busy"
    pkill -9 -x ndnd 2>/dev/null || true
    sleep 0.3
    if [[ $EUID -eq 0 ]]; then
        cp "$out" /usr/local/bin/ndnd
    else
        sudo cp "$out" /usr/local/bin/ndnd
    fi
}

# Build emu/ndnd-traffic from the same ndnd source that sim uses.
build_ndnd_traffic() {
    local go_bin
    go_bin="$(find_go_bin)"
    local out="$REPO_DIR/emu/ndnd-traffic"
    echo "[emu] Building ndnd-traffic from $NDND_SRC (go: $go_bin)"
    (cd "$NDND_SRC" && GOPATH="$GOPATH_DIR" GOFLAGS=-mod=mod "$go_bin" build -buildvcs=false -o "$out" ./cmd/traffic/)
}

usage() {
    cat <<'EOF'
Usage: ./run.sh <command> [args...]

Commands:
  setup                      Install all dependencies from source
  build                      Build all binaries (ns-3, ndnd, ndnd-traffic)
  emu [--no-build] demo      Run 3-node file transfer demo (needs sudo)
  emu [--no-build] scalability [opts]  Run NxN grid scalability test (needs sudo)
  emu [--no-build] routing [opts]      Run routing-only traffic measurement (needs sudo)
  sim [--no-build] demo [opts]         Run 3-node ndndSIM demo
  sim [--no-build] scalability [opts]  Run NxN grid ndndSIM scalability test
  sim [--no-build] routing [opts]      Run routing-only ndndSIM traffic measurement
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

case "$1" in
    setup)
        exec "$REPO_DIR/setup.sh"
        ;;
    build)
        shift
        echo "[build] Building all binaries"
        ensure_ns3_ready
        build_ndnd
        build_ndnd_traffic
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
            build_ndnd
            build_ndnd_traffic
        fi

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
            ensure_ns3_ready
        fi

        run_cmd=(python3)
        if [[ $EUID -eq 0 && -n "$ATLAS_USER" ]]; then
            run_cmd=(sudo -u "$ATLAS_USER" env "PATH=$PATH" "PYTHONPATH=$PYTHONPATH" python3)
        fi

        exec "${run_cmd[@]}" "$REPO_DIR/sim/$subcmd" --ns3-dir "$NS3_DIR" "$@"
        ;;
    both)
        shift
        [[ $# -lt 1 ]] && { echo "Usage: sudo ./run.sh both <demo|scalability> [opts]"; exit 1; }
        subcmd="$1"; shift

        # Must be run as root (emu needs sudo; sim will drop privs internally)
        [[ $EUID -ne 0 ]] && { echo "ERROR: 'both' must be run with sudo"; exit 1; }

        # ns-3 build user (drop privs for sim)
        sim_cmd=(python3)
        if [[ -n "$ATLAS_USER" ]]; then
            sim_cmd=(sudo -u "$ATLAS_USER" env "PATH=$PATH" "PYTHONPATH=$PYTHONPATH" python3)
        fi

        [[ "$subcmd" != *.py ]] && subcmd="${subcmd}.py"

        echo "=== Running emulation ==="
        cleanup_minindn
        build_ndnd
        build_ndnd_traffic
        rc=0
        python3 "$REPO_DIR/emu/$subcmd" "$@" || rc=$?
        fix_results_owner
        [[ $rc -ne 0 ]] && exit $rc

        echo "=== Running simulation ==="
        ensure_ns3_ready
        "${sim_cmd[@]}" "$REPO_DIR/sim/$subcmd" --ns3-dir "$NS3_DIR" "$@"

        ;;
    *)
        usage
        ;;
esac
