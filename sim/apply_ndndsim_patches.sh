#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NS3_DIR="${1:-$REPO_DIR/deps/ns-3}"
NDNDSIM_DIR="$NS3_DIR/contrib/ndndSIM"
PATCH_FILE="$SCRIPT_DIR/patches/ndndsim-register-route-phase.patch"

if [[ ! -d "$NDNDSIM_DIR/.git" ]]; then
    echo "ERROR: ndndSIM repo not found at $NDNDSIM_DIR" >&2
    exit 1
fi

if git -C "$NDNDSIM_DIR" apply --check "$PATCH_FILE" >/dev/null 2>&1; then
    git -C "$NDNDSIM_DIR" apply "$PATCH_FILE"
    echo "[sim] Applied ndndSIM overlay patch: $(basename "$PATCH_FILE")"
elif git -C "$NDNDSIM_DIR" apply --reverse --check "$PATCH_FILE" >/dev/null 2>&1; then
    echo "[sim] ndndSIM overlay patch already applied: $(basename "$PATCH_FILE")"
else
    echo "ERROR: ndndSIM overlay patch no longer applies cleanly: $PATCH_FILE" >&2
    exit 1
fi
