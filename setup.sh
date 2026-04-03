#!/bin/bash
# setup.sh -- Build all dependencies from source inside deps/
#
# Prerequisites (must be installed system-wide):
#   - go 1.22+    (https://go.dev/dl/)
#   - gcc / g++   (11+)
#   - cmake       (3.16+)
#   - python3     + pip
#   - git
#   - sudo
#
# Everything else is cloned + built locally under deps/.

set -eo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPS_DIR="$REPO_DIR/deps"
BIN_DIR="$DEPS_DIR/bin"

# Prefer /usr/local/go if available (many systems have a newer Go there)
if [[ -x /usr/local/go/bin/go ]]; then
    export PATH="/usr/local/go/bin:$PATH"
fi

export GOPATH="$DEPS_DIR/gopath"
export PATH="$BIN_DIR:$GOPATH/bin:$PATH"
export CGO_ENABLED=1

info() { echo -e "\n\033[1;34m==>\033[0m \033[1m$*\033[0m"; }
ok()   { echo -e "    \033[1;32mOK\033[0m $*"; }
err()  { echo -e "    \033[1;31mFAIL\033[0m $*" >&2; }

# -- Preflight checks --
info "Checking prerequisites"
MISSING=()
for cmd in go gcc g++ cmake git python3 sudo; do
    command -v "$cmd" &>/dev/null || MISSING+=("$cmd")
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
    err "Missing: ${MISSING[*]}"
    exit 1
fi

GO_VER=$(go version | grep -oP '\d+\.\d+' | head -1)
if [[ "$(printf '%s\n' "1.22" "$GO_VER" | sort -V | head -1)" != "1.22" ]]; then
    err "Go >= 1.22 required (found $GO_VER)"
    exit 1
fi
ok "go $GO_VER, $(gcc --version | head -1), $(cmake --version | head -1)"

mkdir -p "$DEPS_DIR" "$BIN_DIR"

# -- 1. System packages (build deps only) --
info "Installing system build dependencies"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    build-essential cmake pkg-config \
    python3-setuptools python3-dev python3-pip \
    iproute2 iputils-ping net-tools \
    openvswitch-switch ethtool socat \
    libsqlite3-dev libssl-dev libpcap-dev \
    wget ca-certificates \
    cgroup-tools 2>/dev/null || true
ok "System packages"

# -- 2. Mininet from source --
info "Building Mininet from source"
if [[ ! -d "$DEPS_DIR/mininet" ]]; then
    git clone --depth 1 https://github.com/mininet/mininet.git "$DEPS_DIR/mininet"
fi
cd "$DEPS_DIR/mininet"
make mnexec 2>/dev/null || cc -o mnexec mnexec.c
sudo install -m 755 mnexec /usr/local/bin/
sudo pip3 install --break-system-packages . 2>/dev/null \
    || sudo pip3 install .
ok "Mininet installed"

# -- 3. Mini-NDN from source --
info "Building Mini-NDN from source"
if [[ ! -d "$DEPS_DIR/mini-ndn" ]]; then
    git clone --depth 1 https://github.com/named-data/mini-ndn.git "$DEPS_DIR/mini-ndn"
fi
# Inject NDNd integration modules into mini-ndn's package tree
cp "$REPO_DIR/minindn_ndnd/ndnd_fw.py"  "$DEPS_DIR/mini-ndn/minindn/apps/"
cp "$REPO_DIR/minindn_ndnd/ndnd_dv.py"  "$DEPS_DIR/mini-ndn/minindn/apps/"
cp "$REPO_DIR/minindn_ndnd/dv_util.py"  "$DEPS_DIR/mini-ndn/minindn/helpers/"
cd "$DEPS_DIR/mini-ndn"
sudo pip3 install --break-system-packages -e . 2>/dev/null \
    || sudo pip3 install -e .
ok "Mini-NDN installed (with NDNd modules)"

# -- 4. Python plotting deps --
info "Installing Python plotting dependencies"
pip3 install --break-system-packages --user matplotlib numpy 2>/dev/null \
    || pip3 install --user matplotlib numpy
ok "matplotlib, numpy"

# -- 5. ns-3 (tag ns-3.47) + ndndSIM --
info "Building ns-3 (tag ns-3.47) + ndndSIM"
if [[ ! -d "$DEPS_DIR/ns-3" ]]; then
    git clone --branch ns-3.47 --depth 1 \
        https://gitlab.com/nsnam/ns-3-dev.git "$DEPS_DIR/ns-3"
fi
cd "$DEPS_DIR/ns-3"
mkdir -p contrib
if [[ ! -d contrib/ndndSIM ]]; then
    cd contrib
    git clone https://github.com/markverick/ndndSIM.git ndndSIM
    cd ndndSIM
    git submodule update --init
    cd ../..
fi
# Install atlas scenario into ndndSIM examples
cp "$REPO_DIR/sim/atlas-scenario.cc" contrib/ndndSIM/examples/ndndsim-atlas-scenario.cc
if ! grep -q "ndndsim-atlas-scenario" contrib/ndndSIM/examples/CMakeLists.txt; then
    cat >> contrib/ndndSIM/examples/CMakeLists.txt <<'CMAKE'

# Atlas general-purpose scenario
build_lib_example(
    NAME ndndsim-atlas-scenario
    SOURCE_FILES ndndsim-atlas-scenario.cc
    LIBRARIES_TO_LINK
        ${libndndSIM}
        ${libcore}
        ${libnetwork}
        ${libinternet}
        ${libpoint-to-point}
)
CMAKE
fi
./ns3 configure --enable-examples --enable-tests
./ns3 build
ok "ns-3 + ndndSIM built -> $DEPS_DIR/ns-3"

# -- 6. NDNd binaries from local ndndSIM source --
# Build from the same Go source that the ns-3 sim links against,
# so emu and sim use identical NDN library code.
NDND_SRC="$DEPS_DIR/ns-3/contrib/ndndSIM/ndnd"
info "Building NDNd from local source ($NDND_SRC)"

# Find Go toolchain that satisfies go.mod (1.25+); auto-downloaded into GOPATH
GO_BIN="$(ls "$GOPATH"/pkg/mod/golang.org/toolchain@v0.0.1-go1.25.*.linux-amd64/bin/go 2>/dev/null | sort -V | tail -1)"
if [[ -z "$GO_BIN" || ! -x "$GO_BIN" ]]; then
    # First run: let system Go trigger the toolchain download
    GO_BIN="$(command -v go)"
fi

(cd "$NDND_SRC" && GOPATH="$GOPATH" GOFLAGS=-mod=mod "$GO_BIN" build -o "$BIN_DIR/ndnd" ./cmd/ndnd/)
sudo cp "$BIN_DIR/ndnd" /usr/local/bin/
ok "NDNd daemon -> $BIN_DIR/ndnd (from ndndSIM source)"

# Also build emu traffic tool (identical Go library as sim)
(cd "$NDND_SRC" && GOPATH="$GOPATH" GOFLAGS=-mod=mod "$GO_BIN" build -o "$REPO_DIR/emu/ndnd-traffic" ./cmd/traffic/)
ok "emu/ndnd-traffic -> $REPO_DIR/emu/ndnd-traffic"

# -- Done --
info "Setup complete!"
echo ""
echo "  Binaries:  $BIN_DIR/ndnd"
echo "  Mini-NDN:  $DEPS_DIR/mini-ndn"
echo "  ns-3:      $DEPS_DIR/ns-3"
echo ""
echo "  Next steps:"
echo "    sudo ./run.sh emu demo"
echo "    sudo ./run.sh emu scalability --grids 2 3"
echo "    ./run.sh sim --grids 2 3"
echo "    sudo ./jobs.sh start --fresh prefix_scale/sprint_twostep_0to50"
