#!/usr/bin/env bash
# tests/integration/test_phases.sh
#
# Integrated smoke test for both build phases.
#
# For each phase (twophase, onephase) this script verifies:
#   1. Go transformer + CGo archive compile cleanly (go/build.sh)
#   2. C++ ns-3 + ndndSIM link against the resulting archive
#   3. A 3-node linear sim runs end-to-end:
#        - exits 0 (no crash / segfault)
#        - DV routing converges (conv_trace >= 0)
#        - At least one data packet reached the consumer (rate_trace has data rows)
#
# Usage:
#   ./tests/integration/test_phases.sh [twophase|onephase|both]
#
# Environment:
#   NS3_DIR   – path to ns-3 root (default: deps/ns-3 relative to repo)
#   J         – parallel cmake jobs (default: nproc)
#   SIM_TIME  – simulation duration in seconds (default: 15)
#   KEEP_OUT  – if set, do not delete per-phase output dirs on success
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NS3_DIR="${NS3_DIR:-$REPO_DIR/deps/ns-3}"
GO_DIR="$NS3_DIR/contrib/ndndSIM/go"
J="${J:-$(nproc)}"
SIM_TIME="${SIM_TIME:-15}"
PHASES="${1:-both}"

PASS=0
FAIL=0
ERRORS=()

# ── Colour helpers ──────────────────────────────────────────────────────────
green()  { printf '\033[1;32m%s\033[0m\n' "$*"; }
red()    { printf '\033[1;31m%s\033[0m\n' "$*"; }
blue()   { printf '\033[1;34m%s\033[0m\n' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }

# ── Assertion helpers ───────────────────────────────────────────────────────
assert_file_nonempty() {
    # $1 = path, $2 = label
    local path="$1" label="$2"
    if [[ ! -f "$path" ]]; then
        red "  FAIL [$label]: file not found: $path"
        return 1
    fi
    local lines
    lines=$(grep -c . "$path" || true)
    if [[ "$lines" -le 1 ]]; then
        red "  FAIL [$label]: file has no data rows (only header or empty): $path"
        return 1
    fi
    green "  OK   [$label]: $lines data rows"
}

assert_convergence() {
    # $1 = conv_trace path, $2 = label
    local path="$1" label="$2"
    if [[ ! -f "$path" ]]; then
        red "  FAIL [$label]: conv_trace not found: $path"
        return 1
    fi
    local val
    val=$(cat "$path")
    # python3 as float comparator: val must be >= 0
    if ! python3 -c "import sys; v=float('$val'); sys.exit(0 if v >= 0 else 1)"; then
        red "  FAIL [$label]: DV never converged (conv=$val)"
        return 1
    fi
    green "  OK   [$label]: DV converged at ${val}s"
}

assert_archive_exists() {
    local path="$1" label="$2"
    if [[ ! -f "$path" ]]; then
        red "  FAIL [$label]: archive not found: $path"
        return 1
    fi
    local size
    size=$(stat -c%s "$path")
    if [[ "$size" -lt 100000 ]]; then
        red "  FAIL [$label]: archive suspiciously small (${size} bytes): $path"
        return 1
    fi
    green "  OK   [$label]: archive ${size} bytes"
}

# ── Per-phase test ──────────────────────────────────────────────────────────
run_phase() {
    local phase="$1"
    local out_dir="$REPO_DIR/tests/integration/out-${phase}"
    local log_dir="$out_dir/logs"
    mkdir -p "$log_dir"

    blue ""
    blue "══════════════════════════════════════════════════"
    blue "  PHASE: $phase"
    blue "══════════════════════════════════════════════════"

    local failed=0

    # ── Step 1: Go transformer + CGo archive ───────────────────────────────
    blue "  [1/3] Go build (transformer + CGo archive)"
    local archive="$GO_DIR/libndndsim-${phase}.a"
    local build_log="$log_dir/go-build.log"

    if NDND_PHASE="$phase" bash "$GO_DIR/build.sh" > "$build_log" 2>&1; then
        assert_archive_exists "$archive" "go-archive" || failed=1
    else
        red "  FAIL [go-build]: build.sh exited non-zero (see $build_log)"
        tail -30 "$build_log" | sed 's/^/    /'
        failed=1
    fi

    [[ "$failed" -eq 1 ]] && {
        ERRORS+=("[$phase] Go build failed")
        FAIL=$(( FAIL + 1 ))
        return
    }

    # ── Step 2: C++ ns-3 cmake build ──────────────────────────────────────
    blue "  [2/3] C++ cmake build (ns-3 + ndndSIM)"
    local cmake_log="$log_dir/cmake-build.log"

    if [[ "$phase" == "onephase" ]]; then
        local cmake_cache="$NS3_DIR/cmake-cache-op"
        # Configure if cache doesn't exist yet
        if [[ ! -d "$cmake_cache" ]]; then
            yellow "  cmake cache not found, configuring..."
            cmake -S "$NS3_DIR" -B "$cmake_cache" \
                -DCMAKE_BUILD_TYPE=release \
                -DNS3_EXAMPLES=ON -DNS3_TESTS=ON \
                -DNDNDSIM_PHASE=onephase \
                "-DNS3_OUTPUT_DIRECTORY=$NS3_DIR/build-op" \
                >> "$cmake_log" 2>&1
        fi
        if cmake --build "$cmake_cache" -j"$J" >> "$cmake_log" 2>&1; then
            green "  OK   [cmake-build]: ns-3 onephase linked"
        else
            red "  FAIL [cmake-build]: cmake --build failed (see $cmake_log)"
            tail -40 "$cmake_log" | sed 's/^/    /'
            ERRORS+=("[$phase] cmake build failed")
            FAIL=$(( FAIL + 1 ))
            return
        fi
    else
        # twophase: use standard ./ns3 wrapper
        if (cd "$NS3_DIR" && ./ns3 configure -d release >> "$cmake_log" 2>&1 \
                          && ./ns3 build >> "$cmake_log" 2>&1); then
            green "  OK   [cmake-build]: ns-3 twophase linked"
        else
            red "  FAIL [cmake-build]: ./ns3 build failed (see $cmake_log)"
            tail -40 "$cmake_log" | sed 's/^/    /'
            ERRORS+=("[$phase] ns-3 build failed")
            FAIL=$(( FAIL + 1 ))
            return
        fi
    fi

    # ── Step 3: end-to-end simulation ─────────────────────────────────────
    blue "  [3/3] End-to-end simulation (3-node linear, sim_time=${SIM_TIME}s)"
    local rate_csv="$out_dir/rate-trace.csv"
    local conv_file="$out_dir/conv.txt"
    local link_csv="$out_dir/link-trace.csv"
    local sim_log="$log_dir/sim.log"

    local env_vars=("NDNDSIM_NO_BUILD=1")
    if [[ "$phase" == "onephase" ]]; then
        env_vars+=( "NS3_CMAKE_CACHE=cmake-cache-op" "NS3_BUILD_OUT=build-op" )
    fi

    if env "${env_vars[@]}" python3 "$REPO_DIR/sim/demo.py" \
            --ns3-dir "$NS3_DIR" \
            --window "$SIM_TIME" \
            --out "$out_dir" \
            > "$sim_log" 2>&1; then
        green "  OK   [sim-exit]: process exited 0"
    else
        local rc=$?
        red "  FAIL [sim-exit]: process exited $rc (see $sim_log)"
        tail -40 "$sim_log" | sed 's/^/    /'
        ERRORS+=("[$phase] simulation crashed (exit $rc)")
        FAIL=$(( FAIL + 1 ))
        return
    fi

    local step_failed=0
    assert_convergence  "$conv_file" "dv-converge"  || step_failed=1
    assert_file_nonempty "$rate_csv"  "rate-trace"  || step_failed=1
    assert_file_nonempty "$link_csv"  "link-trace"  || step_failed=1

    # Print summary from sim output
    grep -E "SUCCESS|FAIL|total_pkts|convergence" "$sim_log" | sed 's/^/    /' || true

    if [[ "$step_failed" -eq 1 ]]; then
        ERRORS+=("[$phase] simulation output assertions failed")
        FAIL=$(( FAIL + 1 ))
    else
        PASS=$(( PASS + 1 ))
        # Optionally clean up on success
        [[ -z "${KEEP_OUT:-}" ]] && rm -rf "$out_dir"
    fi
}

# ── Main ────────────────────────────────────────────────────────────────────
case "$PHASES" in
    twophase) run_phase twophase ;;
    onephase) run_phase onephase ;;
    both)     run_phase twophase; run_phase onephase ;;
    *)
        echo "Usage: $0 [twophase|onephase|both]"
        exit 1
        ;;
esac

blue ""
blue "══════════════════════════════════════════════════"
blue "  RESULTS: $PASS passed, $FAIL failed"
blue "══════════════════════════════════════════════════"
if [[ ${#ERRORS[@]} -gt 0 ]]; then
    for e in "${ERRORS[@]}"; do
        red "  ✗ $e"
    done
fi

[[ "$FAIL" -eq 0 ]]
