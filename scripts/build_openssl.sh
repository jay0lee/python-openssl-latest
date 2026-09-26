#!/usr/bin/env bash
set -euo pipefail

# build_openssl.sh - Builds OpenSSL matching GAM's exact compilation settings
# Usage: ./scripts/build_openssl.sh <version> <source_dir> <install_dir>

OPENSSL_VERSION="${1:-}"
SOURCE_DIR="${2:-}"
INSTALL_DIR="${3:-}"

if [[ -z "$OPENSSL_VERSION" || -z "$SOURCE_DIR" || -z "$INSTALL_DIR" ]]; then
  echo "Usage: $0 <version> <source_dir> <install_dir>" >&2
  exit 1
fi

echo "=================================================="
echo "Building OpenSSL ${OPENSSL_VERSION}"
echo "Source:  ${SOURCE_DIR}"
echo "Install: ${INSTALL_DIR}"
echo "=================================================="

RUNNER_OS="${RUNNER_OS:-$(uname -s)}"
RUNNER_ARCH="${RUNNER_ARCH:-$(uname -m)}"

# GAM Configuration options:
# Static library (-fPIC, no-shared) with modern hardened API and stripped legacy ciphers
OPENSSL_CONFIG_OPTS=(
  no-fips
  --api=3.0.0
  no-docs
  no-tls1
  no-tls1_1
  no-dtls
  no-comp
  no-srp
  no-psk
  no-nextprotoneg
  no-weak-ssl-ciphers
  no-idea
  no-seed
  no-camellia
  no-sm2
  no-sm3
  no-sm4
  no-rc2
  no-rc4
  no-rc5
  no-md2
  no-md4
  no-cast
  no-des
  no-shared
  -fPIC
  no-tests
  -O3
)

# Linux ARM64 workaround for ASM compatibility
if [[ "$RUNNER_OS" == "Linux" && ("$RUNNER_ARCH" == "ARM64" || "$RUNNER_ARCH" == "aarch64") ]]; then
  OPENSSL_CONFIG_OPTS+=(no-asm)
fi

mkdir -p "$SOURCE_DIR" "$INSTALL_DIR"

if [[ ! -f "${SOURCE_DIR}/Configure" ]]; then
  echo "Cloning OpenSSL source..."
  git clone --filter=blob:none https://github.com/openssl/openssl.git "$SOURCE_DIR"
  cd "$SOURCE_DIR"
  
  # Check if version has 'openssl-' prefix or not
  TAG_TO_CHECK="openssl-${OPENSSL_VERSION}"
  if git rev-parse "$TAG_TO_CHECK" >/dev/null 2>&1; then
    git checkout "$TAG_TO_CHECK"
  else
    git checkout "${OPENSSL_VERSION}"
  fi
else
  cd "$SOURCE_DIR"
fi

# Detect parallel jobs
if command -v nproc >/dev/null 2>&1; then
  JOBS="$(nproc)"
elif command -v sysctl >/dev/null 2>&1; then
  JOBS="$(sysctl -n hw.logicalcpu)"
else
  JOBS=2
fi

echo "Configuring OpenSSL..."
perl ./Configure --libdir=lib --prefix="${INSTALL_DIR}" "${OPENSSL_CONFIG_OPTS[@]}"

echo "Compiling OpenSSL with ${JOBS} jobs..."
make -j"${JOBS}"

echo "Installing OpenSSL software headers and libraries..."
make install_sw

# Strip binaries on Linux/macOS to reduce size
if [[ -f "${INSTALL_DIR}/bin/openssl" ]]; then
  strip "${INSTALL_DIR}/bin/openssl" || true
fi

echo "OpenSSL build completed successfully."
"${INSTALL_DIR}/bin/openssl" version -a
