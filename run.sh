#!/bin/bash
# run.sh -- Unified runner for atlas-scenarios
#
# Usage:
#   ./run.sh setup                           Install everything from source
#   sudo ./run.sh emu demo                   3-node file transfer demo
#   sudo ./run.sh emu scalability [opts]     NxN grid scalability test
#   ./run.sh sim demo [opts]                 3-node ndndSIM demo
#   ./run.sh sim scalability [opts]          NxN grid ndndSIM scalability test
#   ./run.sh plot [opts]                     Generate comparison plots

set -eo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="$REPO_DIR/deps"
NS3_DIR="$DEPS_DIR/ns-3"

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
    # This is fast and avoids stale build confusion.
    echo "[sim] Configuring ns-3"
    if [[ $EUID -eq 0 && -n "$SUDO_USER" ]]; then
        (cd "$NS3_DIR" && sudo -u "$SUDO_USER" env "PATH=$PATH" ./ns3 configure -d release)
    else
        (cd "$NS3_DIR" && ./ns3 configure -d release)
    fi

    echo "[sim] Building ns-3"
    if [[ $EUID -eq 0 && -n "$SUDO_USER" ]]; then
        (cd "$NS3_DIR" && sudo -u "$SUDO_USER" env "PATH=$PATH" ./ns3 build)
    else
        (cd "$NS3_DIR" && ./ns3 build)
    fi
}

# Build emu/ndnd-traffic from the same ndnd source that sim uses.
# This ensures identical Go library code on both sides.
build_ndnd_traffic() {
    local out="$REPO_DIR/emu/ndnd-traffic"
    # Find Go 1.25 toolchain (downloaded by setup into GOPATH)
    local go_bin
    go_bin="$(ls "$GOPATH_DIR"/pkg/mod/golang.org/toolchain@v0.0.1-go1.25.*.linux-amd64/bin/go 2>/dev/null | sort -V | tail -1)"
    if [[ -z "$go_bin" || ! -x "$go_bin" ]]; then
        go_bin="$(command -v go)"   # fallback to system Go
    fi
    echo "Building emu/ndnd-traffic from $NDND_SRC (go: $go_bin)"
    (cd "$NDND_SRC" && GOPATH="$GOPATH_DIR" GOFLAGS=-mod=mod "$go_bin" build -o "$out" ./cmd/traffic/)
}

usage() {
    cat <<'EOF'
Usage: ./run.sh <command> [args...]

Commands:
  setup                      Install all dependencies from source
  emu demo                   Run 3-node file transfer demo (needs sudo)
  emu scalability [opts]     Run NxN grid scalability test (needs sudo)
  sim demo [opts]            Run 3-node ndndSIM demo
  sim scalability [opts]     Run NxN grid ndndSIM scalability test
  plot [opts]                Generate comparison plots from CSV results

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

Plot options (plot):
  --emu results/emu/scalability.csv
  --sim results/sim/scalability.csv
  --out results/plots

Examples:
  ./setup.sh
  sudo ./run.sh emu demo
  sudo ./run.sh emu scalability --grids 2 3 4 --trials 1
  ./run.sh sim demo
  ./run.sh sim scalability --grids 2 3 4
  ./run.sh plot
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
    emu)
        shift
        [[ $# -lt 1 ]] && { echo "Usage: ./run.sh emu <demo|scalability> [opts]"; exit 1; }
        subcmd="$1"; shift
        cleanup_minindn
        build_ndnd_traffic
        case "$subcmd" in
            demo)
                python3 "$REPO_DIR/emu/demo.py" "$@"
                ;;
            scalability)
                python3 "$REPO_DIR/emu/scalability.py" "$@"
                ;;
            *)
                python3 "$REPO_DIR/emu/$subcmd" "$@"
                ;;
        esac
        rc=$?
        # Fix ownership of results created by sudo
        if [[ -d "$REPO_DIR/results" && -n "$SUDO_USER" ]]; then
            chown -R "$SUDO_USER:$SUDO_USER" "$REPO_DIR/results"
        fi
        exit $rc
        ;;
    sim)
        shift
        [[ $# -lt 1 ]] && { echo "Usage: ./run.sh sim <demo|scalability> [opts]"; exit 1; }
        subcmd="$1"; shift

        ensure_ns3_ready

        # ns-3 refuses to build as root; drop to the invoking user if under sudo
        run_cmd=(python3)
        if [[ $EUID -eq 0 && -n "$SUDO_USER" ]]; then
            run_cmd=(sudo -u "$SUDO_USER" env "PATH=$PATH" "PYTHONPATH=$PYTHONPATH" python3)
        fi

        case "$subcmd" in
            demo)
                exec "${run_cmd[@]}" "$REPO_DIR/sim/demo.py" --ns3-dir "$NS3_DIR" "$@"
                ;;
            scalability)
                exec "${run_cmd[@]}" "$REPO_DIR/sim/scalability.py" --ns3-dir "$NS3_DIR" "$@"
                ;;
            *)
                exec "${run_cmd[@]}" "$REPO_DIR/sim/$subcmd" --ns3-dir "$NS3_DIR" "$@"
                ;;
        esac
        ;;
    plot)
        shift
        exec python3 "$REPO_DIR/plot.py" "$@"
        ;;
    both)
        shift
        [[ $# -lt 1 ]] && { echo "Usage: sudo ./run.sh both <demo|scalability> [opts]"; exit 1; }
        subcmd="$1"; shift

        # Must be run as root (emu needs sudo; sim will drop privs internally)
        [[ $EUID -ne 0 ]] && { echo "ERROR: 'both' must be run with sudo"; exit 1; }

        # ns-3 build user (drop privs for sim)
        sim_cmd=(python3)
        if [[ -n "$SUDO_USER" ]]; then
            sim_cmd=(sudo -u "$SUDO_USER" env "PATH=$PATH" "PYTHONPATH=$PYTHONPATH" python3)
        fi

        echo "=== Running emulation ==="
        cleanup_minindn
        build_ndnd_traffic
        python3 "$REPO_DIR/emu/${subcmd}.py" "$@"
        if [[ -d "$REPO_DIR/results" && -n "$SUDO_USER" ]]; then
            chown -R "$SUDO_USER:$SUDO_USER" "$REPO_DIR/results"
        fi

        echo "=== Running simulation ==="
        ensure_ns3_ready
        "${sim_cmd[@]}" "$REPO_DIR/sim/${subcmd}.py" --ns3-dir "$NS3_DIR" "$@"

        echo "=== Plotting ==="
        python3 "$REPO_DIR/plot.py"
        ;;
    *)
        usage
        ;;
esac
