#!/bin/bash
set -e

# Clean up any previous Mini-NDN state
python3 -c "from minindn.minindn import Minindn; Minindn.cleanUp()" 2>/dev/null || true

# If first arg is "bash", drop to a shell
if [ "$1" = "bash" ]; then
    exec bash
fi

exec python3 "$@"
