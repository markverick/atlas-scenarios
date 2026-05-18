#!/bin/bash
# setup.sh -- Build all dependencies from source inside deps/
#
# Prerequisites (must be installed system-wide):
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

PINNED_GO_VERSION="1.24.3"
PINNED_GO_SHA256="3333f6ea53afa971e9078895eaa4ac7204a8c6b5c68c10e6bc9a33e8e391bdd8"
TWOPHASE_NDND_HASH="a841cc2"
NDNDSIM_OVERRIDES="$REPO_DIR/ndndsim-overrides"

export GOPATH="$DEPS_DIR/gopath"
PINNED_GO_DIR="$GOPATH/pkg/mod/golang.org/toolchain@v0.0.1-go${PINNED_GO_VERSION}.linux-amd64"
PINNED_GO_BIN="$PINNED_GO_DIR/bin/go"
export PATH="$PINNED_GO_DIR/bin:$BIN_DIR:$GOPATH/bin:$PATH"
export CGO_ENABLED=1
export GOTOOLCHAIN=local

info() { echo -e "\n\033[1;34m==>\033[0m \033[1m$*\033[0m"; }
ok()   { echo -e "    \033[1;32mOK\033[0m $*"; }
err()  { echo -e "    \033[1;31mFAIL\033[0m $*" >&2; }

install_pinned_go() {
    mkdir -p "$GOPATH/pkg/mod/golang.org"

    if [[ -x "$PINNED_GO_BIN" ]]; then
        local found_version
        found_version="$("$PINNED_GO_BIN" version | awk '{print $3}')"
        if [[ "$found_version" == "go$PINNED_GO_VERSION" ]]; then
            ok "Pinned Go already installed: $("$PINNED_GO_BIN" version)"
            return
        fi
        err "Unexpected Go at $PINNED_GO_BIN: $found_version"
        rm -rf "$PINNED_GO_DIR"
    fi

    info "Installing pinned Go $PINNED_GO_VERSION"
    local archive="$DEPS_DIR/go${PINNED_GO_VERSION}.linux-amd64.tar.gz"
    local url="https://go.dev/dl/go${PINNED_GO_VERSION}.linux-amd64.tar.gz"
    if [[ ! -f "$archive" ]]; then
        wget -O "$archive" "$url"
    fi

    echo "${PINNED_GO_SHA256}  ${archive}" | sha256sum -c -
    rm -rf "$PINNED_GO_DIR"
    mkdir -p "$PINNED_GO_DIR"
    tar -C "$PINNED_GO_DIR" --strip-components=1 -xzf "$archive"
    ok "Pinned Go installed: $("$PINNED_GO_BIN" version)"
}

# -- Preflight checks --
info "Checking prerequisites"
MISSING=()
for cmd in gcc g++ cmake git python3 sudo sha256sum tar; do
    command -v "$cmd" &>/dev/null || MISSING+=("$cmd")
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
    err "Missing: ${MISSING[*]}"
    exit 1
fi
ok "$(gcc --version | head -1), $(cmake --version | head -1)"

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

install_pinned_go
ok "Using Go toolchain: $("$PINNED_GO_BIN" version) at $PINNED_GO_BIN"

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
cd "$DEPS_DIR/mini-ndn"
sudo pip3 install --break-system-packages -e . 2>/dev/null \
    || sudo pip3 install -e .
ok "Mini-NDN installed"

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
    git clone https://github.com/markverick/ndndSIM.git contrib/ndndSIM
fi
if [[ -d "$NDNDSIM_OVERRIDES" ]]; then
    info "Installing ndndSIM transformer/overlay overrides"
    cp -a "$NDNDSIM_OVERRIDES"/. contrib/ndndSIM/
    ok "ndndSIM overrides installed"
fi

# Install atlas scenarios into ndndSIM examples
cp "$REPO_DIR/sim/atlas-scenario.cc"         contrib/ndndSIM/examples/ndndsim-atlas-scenario.cc
cp "$REPO_DIR/sim/atlas-churn-scenario.cc"   contrib/ndndSIM/examples/ndndsim-atlas-churn-scenario.cc
cp "$REPO_DIR/sim/atlas-multihop-scenario.cc" contrib/ndndSIM/examples/ndndsim-atlas-multihop-scenario.cc
cp "$REPO_DIR/sim/atlas-routing-scenario.cc" contrib/ndndSIM/examples/ndndsim-atlas-routing-scenario.cc
cp "$REPO_DIR/sim/atlas-prefix-scale-scenario.cc" contrib/ndndSIM/examples/ndndsim-atlas-prefix-scale-scenario.cc
if ! grep -q "ndndsim-atlas-prefix-scale-scenario" contrib/ndndSIM/examples/CMakeLists.txt; then
    cat >> contrib/ndndSIM/examples/CMakeLists.txt <<'CMAKE'

# Atlas prefix-scale scenario
build_lib_example(
    NAME ndndsim-atlas-prefix-scale-scenario
    SOURCE_FILES ndndsim-atlas-prefix-scale-scenario.cc
    LIBRARIES_TO_LINK
        ${libndndSIM}
        ${libcore}
        ${libnetwork}
        ${libinternet}
        ${libpoint-to-point}
)
CMAKE
fi
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
ok "ns-3 + ndndSIM built (twophase) -> $DEPS_DIR/ns-3"

# -- 5b. ns-3 onephase build (separate cmake cache, reuses same C++ source) --
info "Building ns-3 onephase cmake cache (named-data/ndnd@main@51774b8)"
cmake -S "$DEPS_DIR/ns-3" -B "$DEPS_DIR/ns-3/cmake-cache-op" \
    -DCMAKE_BUILD_TYPE=release \
    -DNS3_EXAMPLES=ON -DNS3_TESTS=ON \
    -DNDNDSIM_PHASE=onephase \
    "-DNS3_OUTPUT_DIRECTORY=$DEPS_DIR/ns-3/build-op"
cmake --build "$DEPS_DIR/ns-3/cmake-cache-op" -j$(nproc)
ok "ns-3 + ndndSIM built (onephase) -> $DEPS_DIR/ns-3/build-op"

# -- 6. NDNd binaries from local ndndSIM source --
# The daemon is built from pristine upstream ndnd at the pinned dv2 commit.
# The traffic tool is built from .transformed-ndnd because cmd/traffic/ is
# added by the overlay (it does not exist in pristine upstream ndnd).
# By the time this step runs ./ns3 build has already invoked go/build.sh, so
# .transformed-ndnd is fully prepared and its go.work is in place.
NDND_SRC_TMP="$DEPS_DIR/ndnd-daemon"
if [[ ! -d "$NDND_SRC_TMP" ]]; then
    info "Cloning NDNd daemon source"
    git clone --branch dv2 https://github.com/named-data/ndnd.git "$NDND_SRC_TMP"
fi
if ! git -C "$NDND_SRC_TMP" cat-file -e "$TWOPHASE_NDND_HASH^{commit}" 2>/dev/null; then
    info "Fetching NDNd dv2 commit $TWOPHASE_NDND_HASH"
    git -C "$NDND_SRC_TMP" fetch origin dv2
fi
NDND_SRC="$NDND_SRC_TMP"
TRANSFORMED_NDND="$DEPS_DIR/ns-3/contrib/ndndSIM/go/.transformed-ndnd-twophase"
info "Building NDNd from local source ($NDND_SRC @ $TWOPHASE_NDND_HASH)"

GO_BIN="$PINNED_GO_BIN"

NDND_BUILD_WORKTREE="$(mktemp -d)"
git -C "$NDND_SRC" worktree add --detach "$NDND_BUILD_WORKTREE" "$TWOPHASE_NDND_HASH"
(cd "$NDND_BUILD_WORKTREE" && GOPATH="$GOPATH" GOWORK=off GOFLAGS=-mod=mod "$GO_BIN" build -buildvcs=false -o "$BIN_DIR/ndnd" ./cmd/ndnd/)
git -C "$NDND_SRC" worktree remove --force "$NDND_BUILD_WORKTREE" 2>/dev/null || true
rm -rf "$NDND_BUILD_WORKTREE" 2>/dev/null || true
sudo cp "$BIN_DIR/ndnd" /usr/local/bin/
ok "NDNd daemon -> $BIN_DIR/ndnd (from pristine ndnd@$TWOPHASE_NDND_HASH)"

# The traffic tool lives in cmd/traffic/ which is added by the overlay.
# Build from .transformed-ndnd with GOWORK=off so we use the module's own go.mod.
(cd "$TRANSFORMED_NDND" && GOWORK=off GOPATH="$GOPATH" GOFLAGS=-mod=mod "$GO_BIN" build -o "$REPO_DIR/emu/ndnd-traffic" ./cmd/traffic/)
ok "emu/ndnd-traffic -> $REPO_DIR/emu/ndnd-traffic (from transformed ndnd)"

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
echo "    sudo ./jobs.sh start --fresh prefix_scale/sprint_onephase_0to50"
