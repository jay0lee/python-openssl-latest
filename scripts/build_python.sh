#!/usr/bin/env bash
set -euo pipefail

# build_python.sh - Builds CPython matching GAM's exact compilation settings
# Usage: ./scripts/build_python.sh <python_version> <openssl_version> <openssl_install_dir> <python_source_dir> <python_install_dir>

PYTHON_VERSION="${1:-}"
OPENSSL_VERSION="${2:-}"
OPENSSL_INSTALL_DIR="${3:-}"
SOURCE_DIR="${4:-}"
INSTALL_DIR="${5:-}"

if [[ -z "$PYTHON_VERSION" || -z "$OPENSSL_VERSION" || -z "$OPENSSL_INSTALL_DIR" || -z "$SOURCE_DIR" || -z "$INSTALL_DIR" ]]; then
  echo "Usage: $0 <python_version> <openssl_version> <openssl_install_dir> <source_dir> <install_dir>" >&2
  exit 1
fi

echo "=================================================="
echo "Building Python ${PYTHON_VERSION} with OpenSSL ${OPENSSL_VERSION}"
echo "OpenSSL Install: ${OPENSSL_INSTALL_DIR}"
echo "Python Source:   ${SOURCE_DIR}"
echo "Python Install:  ${INSTALL_DIR}"
echo "=================================================="

RUNNER_OS="${RUNNER_OS:-$(uname -s)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

mkdir -p "$SOURCE_DIR" "$INSTALL_DIR"

if [[ ! -f "${SOURCE_DIR}/configure" ]]; then
  echo "Cloning CPython source..."
  git clone --filter=blob:none https://github.com/python/cpython.git "$SOURCE_DIR"
  cd "$SOURCE_DIR"
  TAG_TO_CHECK="v${PYTHON_VERSION}"
  if git rev-parse "$TAG_TO_CHECK" >/dev/null 2>&1; then
    git checkout "$TAG_TO_CHECK"
  else
    git checkout "${PYTHON_VERSION}"
  fi
else
  cd "$SOURCE_DIR"
fi

# Apply GAM patch for Python 3.14 + OpenSSL 4.0 if building 3.14 with OpenSSL 4.x
MAJOR_PY="$(echo "$PYTHON_VERSION" | cut -d. -f1)"
MINOR_PY="$(echo "$PYTHON_VERSION" | cut -d. -f2)"
MAJOR_OSSL="$(echo "$OPENSSL_VERSION" | cut -d. -f1)"

if [[ "$MAJOR_PY" -eq 3 && "$MINOR_PY" -eq 14 && "$MAJOR_OSSL" -ge 4 ]]; then
  PATCH_FILE="${REPO_ROOT}/patches/py314-ossl4.diff"
  if [[ -f "$PATCH_FILE" ]]; then
    echo "Applying Python 3.14 + OpenSSL 4 compatibility patch: ${PATCH_FILE}"
    patch -p1 -N < "$PATCH_FILE" || true
  fi
fi

# Detect parallel jobs
if command -v nproc >/dev/null 2>&1; then
  JOBS="$(nproc)"
elif command -v sysctl >/dev/null 2>&1; then
  JOBS="$(sysctl -n hw.logicalcpu)"
else
  JOBS=2
fi

# Relocatable RPATH settings:
# Ensures libpython and extensions find relative libraries without needing hardcoded paths
if [[ "$RUNNER_OS" == "Darwin" || "$RUNNER_OS" == "macOS" ]]; then
  export CFLAGS="-O3 -pipe"
  export LDFLAGS="-Wl,-dead_strip -Wl,-rpath,@executable_path/../lib"
elif [[ "$RUNNER_OS" == "Linux" ]]; then
  export CFLAGS="-O3 -pipe"
  export LDFLAGS="-Wl,--strip-all -Wl,-rpath,'\$\$ORIGIN/../lib'"
fi

echo "Configuring Python..."
./configure \
  --with-openssl="${OPENSSL_INSTALL_DIR}" \
  --prefix="${INSTALL_DIR}" \
  --enable-shared \
  --with-ensurepip=upgrade \
  --enable-optimizations \
  --with-lto \
  --disable-test-modules \
  --without-doc-strings || {
    echo "Configure failed. Showing config.log:"
    cat config.log
    exit 1
  }

echo "Compiling Python with ${JOBS} jobs..."
make -j"${JOBS}"

echo "Installing Python..."
make altinstall
make bininstall

# Ensure convenient python/python3 and pip/pip3 symlinks
cd "${INSTALL_DIR}/bin"
if [[ ! -e python && -e python3 ]]; then
  ln -sf python3 python
fi
if [[ ! -e pip && -e pip3 ]]; then
  ln -sf pip3 pip
fi

# Strip binary to reduce package size
strip python3 || true

# On macOS, fix dylib install name and executable references to use @rpath for full relocatability
if [[ "$RUNNER_OS" == "Darwin" || "$RUNNER_OS" == "macOS" ]]; then
  MAJOR_MINOR="${MAJOR_PY}.${MINOR_PY}"
  DYLIB_NAME="libpython${MAJOR_MINOR}.dylib"
  if [[ -f "${INSTALL_DIR}/lib/${DYLIB_NAME}" ]]; then
    install_name_tool -id "@rpath/${DYLIB_NAME}" "${INSTALL_DIR}/lib/${DYLIB_NAME}" || true
    install_name_tool -change "${INSTALL_DIR}/lib/${DYLIB_NAME}" "@rpath/${DYLIB_NAME}" "${INSTALL_DIR}/bin/python3" || true
    install_name_tool -change "${INSTALL_DIR}/lib/${DYLIB_NAME}" "@rpath/${DYLIB_NAME}" "${INSTALL_DIR}/bin/python${MAJOR_MINOR}" || true
  fi
fi

echo "Python compilation and installation completed successfully."
