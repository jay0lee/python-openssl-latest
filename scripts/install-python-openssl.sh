#!/usr/bin/env bash
# ==============================================================================
# install-python-openssl.sh
#
# Detects current OS/platform (macOS / Linux, x86_64 / arm64) and installs the
# latest pre-compiled Python and OpenSSL release from jay0lee/python-openssl-latest
# into ~/bin for the current user.
#
# Automatically updates .bashrc, .zshrc, or .bash_profile to export PATH.
# ==============================================================================

set -euo pipefail

REPO="${REPO:-jay0lee/python-openssl-latest}"
INSTALL_BASE="${INSTALL_BASE:-$HOME/bin}"

# --- Terminal styling ---
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  BOLD="\033[1m"
  GREEN="\033[32m"
  CYAN="\033[36m"
  YELLOW="\033[33m"
  RED="\033[31m"
  RESET="\033[0m"
else
  BOLD="" GREEN="" CYAN="" YELLOW="" RED="" RESET=""
fi

echo -e "${BOLD}${CYAN}=== Python & OpenSSL Installer ===${RESET}"

# ------------------------------------------------------------------------------
# 1. Dependency Checks
# ------------------------------------------------------------------------------
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  echo -e "${RED}Error: Neither 'curl' nor 'wget' was found. Please install one to proceed.${RESET}" >&2
  exit 1
fi

if ! command -v tar >/dev/null 2>&1; then
  echo -e "${RED}Error: 'tar' utility is required to extract release bundles.${RESET}" >&2
  exit 1
fi

# ------------------------------------------------------------------------------
# 2. OS & Architecture Detection
# ------------------------------------------------------------------------------
RAW_OS="$(uname -s)"
case "$RAW_OS" in
  Darwin)
    OS_FAMILY="macos"
    ;;
  Linux)
    OS_FAMILY="linux"
    ;;
  *)
    echo -e "${RED}Error: Unsupported operating system '${RAW_OS}'. This script supports macOS and Linux.${RESET}" >&2
    exit 1
    ;;
esac

RAW_ARCH="$(uname -m)"
case "$RAW_ARCH" in
  x86_64|amd64)
    TARGET_ARCH="x64"
    ;;
  arm64|aarch64)
    TARGET_ARCH="arm64"
    ;;
  *)
    echo -e "${RED}Error: Unsupported architecture '${RAW_ARCH}'. Supported architectures are x86_64 and arm64.${RESET}" >&2
    exit 1
    ;;
esac

PREFERRED_LABEL=""
if [ "$OS_FAMILY" = "macos" ]; then
  MACOS_VER="$(sw_vers -productVersion 2>/dev/null | cut -d. -f1 || echo "")"
  if [ -n "$MACOS_VER" ]; then
    if [ "$TARGET_ARCH" = "x64" ]; then
      PREFERRED_LABEL="macos-${MACOS_VER}-intel"
    else
      PREFERRED_LABEL="macos-${MACOS_VER}"
    fi
  fi
  echo -e "Platform detected: ${GREEN}macOS (v${MACOS_VER:-unknown}, ${RAW_ARCH})${RESET}"
else
  LINUX_DISTRO="Linux"
  if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    LINUX_DISTRO="${NAME:-Linux} ${VERSION_ID:-}"
    if [ -n "${VERSION_ID:-}" ]; then
      if [ "$TARGET_ARCH" = "arm64" ]; then
        PREFERRED_LABEL="ubuntu-${VERSION_ID}-arm"
      else
        PREFERRED_LABEL="ubuntu-${VERSION_ID}"
      fi
    fi
  fi
  echo -e "Platform detected: ${GREEN}${LINUX_DISTRO} (${RAW_ARCH})${RESET}"
fi

# ------------------------------------------------------------------------------
# 3. Query Latest GitHub Release & Asset
# ------------------------------------------------------------------------------
echo -e "Fetching latest release metadata from ${CYAN}${REPO}${RESET}..."

AUTH_HEADER=()
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
fi

API_URL="https://api.github.com/repos/${REPO}/releases/latest"
if command -v curl >/dev/null 2>&1; then
  RELEASE_JSON="$(curl -fsSL "${AUTH_HEADER[@]}" "$API_URL" || true)"
else
  WGET_AUTH=()
  [ -n "${GITHUB_TOKEN:-}" ] && WGET_AUTH=(--header="Authorization: Bearer ${GITHUB_TOKEN}")
  RELEASE_JSON="$(wget -qO- "${WGET_AUTH[@]}" "$API_URL" || true)"
fi

if [ -z "$RELEASE_JSON" ]; then
  echo -e "${RED}Error: Failed to fetch release details from GitHub API ($API_URL).${RESET}" >&2
  exit 1
fi

# Select best matching asset (.tar.xz / .tar.gz)
ASSET_INFO=""
if command -v python3 >/dev/null 2>&1; then
  ASSET_INFO="$(python3 -c '
import sys, json

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(1)

assets = data.get("assets", [])
os_family = sys.argv[1].lower()
arch = sys.argv[2].lower()
pref_label = sys.argv[3].lower() if len(sys.argv) > 3 else ""

candidates = [a for a in assets if a.get("name", "").endswith((".tar.xz", ".tar.gz"))]

selected = None
# 1. Preferred runner label + architecture match
if pref_label:
    for a in candidates:
        n = a["name"].lower()
        if pref_label in n and arch in n:
            selected = a
            break

# 2. OS family token + architecture match
if not selected:
    family_tokens = ["macos", "darwin"] if os_family == "macos" else ["ubuntu", "linux", "debian"]
    for a in candidates:
        n = a["name"].lower()
        if arch in n and any(tok in n for tok in family_tokens):
            selected = a
            break

# 3. Architecture match fallback
if not selected:
    for a in candidates:
        if arch in a["name"].lower():
            selected = a
            break

if selected:
    print(f"{selected[\"name\"]}\t{selected[\"browser_download_url\"]}\t{data.get(\"tag_name\", \"\")}")
else:
    sys.exit(2)
' "$OS_FAMILY" "$TARGET_ARCH" "$PREFERRED_LABEL" <<< "$RELEASE_JSON" || true)"
fi

# Portable awk/grep fallback if python3 is not yet installed
if [ -z "$ASSET_INFO" ]; then
  TAG_NAME="$(echo "$RELEASE_JSON" | grep -m1 '"tag_name":' | cut -d'"' -f4 || echo "latest")"
  ASSET_NAME="$(echo "$RELEASE_JSON" | grep '"name":' | grep -E '\.tar\.(xz|gz)' | grep -i "$OS_FAMILY" | grep -i "$TARGET_ARCH" | head -n1 | cut -d'"' -f4 || true)"
  if [ -z "$ASSET_NAME" ]; then
    ASSET_NAME="$(echo "$RELEASE_JSON" | grep '"name":' | grep -E '\.tar\.(xz|gz)' | grep -i "$TARGET_ARCH" | head -n1 | cut -d'"' -f4 || true)"
  fi
  if [ -n "$ASSET_NAME" ]; then
    ASSET_URL="https://github.com/${REPO}/releases/download/${TAG_NAME}/${ASSET_NAME}"
    ASSET_INFO="${ASSET_NAME}	${ASSET_URL}	${TAG_NAME}"
  fi
fi

if [ -z "$ASSET_INFO" ]; then
  echo -e "${RED}Error: Could not find a compatible pre-compiled archive for ${OS_FAMILY} (${TARGET_ARCH}) in release.${RESET}" >&2
  exit 1
fi

ASSET_NAME="$(echo "$ASSET_INFO" | cut -f1)"
DOWNLOAD_URL="$(echo "$ASSET_INFO" | cut -f2)"
TAG_NAME="$(echo "$ASSET_INFO" | cut -f3)"

echo -e "Selected release: ${GREEN}${TAG_NAME}${RESET}"
echo -e "Selected package: ${GREEN}${ASSET_NAME}${RESET}"

# ------------------------------------------------------------------------------
# 4. Download and Verify
# ------------------------------------------------------------------------------
TMP_DIR="$(mktemp -d 2>/dev/null || mktemp -d -t 'py_ssl_install')"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

ARCHIVE_PATH="${TMP_DIR}/${ASSET_NAME}"
echo -e "Downloading bundle..."
if command -v curl >/dev/null 2>&1; then
  curl -fL --progress-bar -o "$ARCHIVE_PATH" "$DOWNLOAD_URL"
else
  wget -q --show-progress -O "$ARCHIVE_PATH" "$DOWNLOAD_URL"
fi

# Checksum verification (if .sha256 sidecar is published)
SHA_URL="${DOWNLOAD_URL}.sha256"
SHA_FILE="${ARCHIVE_PATH}.sha256"
if curl -fsSL -o "$SHA_FILE" "$SHA_URL" 2>/dev/null || wget -qO "$SHA_FILE" "$SHA_URL" 2>/dev/null; then
  echo "Verifying SHA256 checksum..."
  EXPECTED_SHA="$(awk '{print $1}' "$SHA_FILE" | head -n1)"
  if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_SHA="$(sha256sum "$ARCHIVE_PATH" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    ACTUAL_SHA="$(shasum -a 256 "$ARCHIVE_PATH" | awk '{print $1}')"
  elif command -v python3 >/dev/null 2>&1; then
    ACTUAL_SHA="$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$ARCHIVE_PATH")"
  else
    ACTUAL_SHA=""
  fi

  if [ -n "$ACTUAL_SHA" ]; then
    if [ "$EXPECTED_SHA" = "$ACTUAL_SHA" ]; then
      echo -e "${GREEN}Checksum verified successfully.${RESET}"
    else
      echo -e "${RED}Error: SHA256 checksum mismatch!${RESET}" >&2
      echo -e "Expected: $EXPECTED_SHA" >&2
      echo -e "Actual:   $ACTUAL_SHA" >&2
      exit 1
    fi
  fi
fi

# Extract into staging area
STAGE_DIR="${TMP_DIR}/extracted"
mkdir -p "$STAGE_DIR"
echo "Extracting archive..."
tar -xf "$ARCHIVE_PATH" -C "$STAGE_DIR"

# ------------------------------------------------------------------------------
# 5. Install into ~/bin
# ------------------------------------------------------------------------------
mkdir -p "$INSTALL_BASE"
echo -e "Installing into ${CYAN}${INSTALL_BASE}${RESET}..."

if [ -d "${STAGE_DIR}/python" ]; then
  rm -rf "${INSTALL_BASE}/python"
  mv "${STAGE_DIR}/python" "${INSTALL_BASE}/python"
fi

if [ -d "${STAGE_DIR}/ssl" ]; then
  rm -rf "${INSTALL_BASE}/ssl"
  mv "${STAGE_DIR}/ssl" "${INSTALL_BASE}/ssl"
fi

if [ -f "${STAGE_DIR}/BUILD_INFO.txt" ]; then
  mv "${STAGE_DIR}/BUILD_INFO.txt" "${INSTALL_BASE}/BUILD_INFO.txt"
fi

# Create convenience symlinks directly in ~/bin
if [ -x "${INSTALL_BASE}/python/bin/python3" ]; then
  ln -sf "${INSTALL_BASE}/python/bin/python3" "${INSTALL_BASE}/python3"
  ln -sf "${INSTALL_BASE}/python/bin/python3" "${INSTALL_BASE}/python"
fi
if [ -x "${INSTALL_BASE}/python/bin/pip3" ]; then
  ln -sf "${INSTALL_BASE}/python/bin/pip3" "${INSTALL_BASE}/pip3"
  ln -sf "${INSTALL_BASE}/python/bin/pip3" "${INSTALL_BASE}/pip"
fi
if [ -x "${INSTALL_BASE}/ssl/bin/openssl" ]; then
  ln -sf "${INSTALL_BASE}/ssl/bin/openssl" "${INSTALL_BASE}/openssl"
fi

# Symlink system CA certificates if available
for ca in "/etc/ssl/cert.pem" "/etc/ssl/certs/ca-certificates.crt" "/etc/pki/tls/certs/ca-bundle.crt" "/etc/ssl/ca-bundle.pem"; do
  if [ -f "$ca" ]; then
    mkdir -p "${INSTALL_BASE}/ssl/ssl"
    [ ! -e "${INSTALL_BASE}/ssl/cert.pem" ] && ln -sf "$ca" "${INSTALL_BASE}/ssl/cert.pem" 2>/dev/null || true
    [ ! -e "${INSTALL_BASE}/ssl/ssl/cert.pem" ] && ln -sf "$ca" "${INSTALL_BASE}/ssl/ssl/cert.pem" 2>/dev/null || true
    break
  fi
done

# Ensure macOS relocatability via install_name_tool if available
if [ "$OS_FAMILY" = "macos" ] && command -v install_name_tool >/dev/null 2>&1; then
  for dylib in "${INSTALL_BASE}/python/lib"/libpython*.dylib; do
    if [ -f "$dylib" ]; then
      fname="$(basename "$dylib")"
      install_name_tool -id "@rpath/${fname}" "$dylib" 2>/dev/null || true
      if command -v otool >/dev/null 2>&1; then
        for py_exec in "${INSTALL_BASE}/python/bin/python3" "${INSTALL_BASE}/python/bin/python"; do
          if [ -f "$py_exec" ]; then
            old_ref="$(otool -L "$py_exec" 2>/dev/null | grep "$fname" | grep -v "@rpath" | awk '{print $1}' | head -n1 || true)"
            if [ -n "$old_ref" ]; then
              install_name_tool -change "$old_ref" "@rpath/${fname}" "$py_exec" 2>/dev/null || true
            fi
          fi
        done
      fi
    fi
  done
fi

# ------------------------------------------------------------------------------
# 6. Update Shell Startup Files (.bashrc, .zshrc, .bash_profile)
# ------------------------------------------------------------------------------
echo "Configuring environment in shell startup files..."

MARKER_START="# >>> jay0lee/python-openssl-latest >>>"
MARKER_END="# <<< jay0lee/python-openssl-latest <<<"

update_shell_file() {
  local cfg_file="$1"
  local tmp_cfg="${cfg_file}.tmp.$$"

  if [ -f "$cfg_file" ] && grep -qF "$MARKER_START" "$cfg_file"; then
    echo -e "  Updating existing configuration block in ${CYAN}${cfg_file}${RESET}..."
    local skip=0
    while IFS= read -r line || [ -n "$line" ]; do
      if [ "$line" = "$MARKER_START" ]; then
        skip=1
        echo "$MARKER_START"
        echo 'export PATH="$HOME/bin/python/bin:$HOME/bin/ssl/bin:$HOME/bin:$PATH"'
        echo 'export OPENSSL_INSTALL_PATH="$HOME/bin/ssl"'
        echo "$MARKER_END"
      elif [ "$line" = "$MARKER_END" ]; then
        skip=0
      elif [ $skip -eq 0 ]; then
        echo "$line"
      fi
    done < "$cfg_file" > "$tmp_cfg"
    mv "$tmp_cfg" "$cfg_file"
  else
    echo -e "  Adding binary directories to ${CYAN}${cfg_file}${RESET}..."
    {
      echo ""
      echo "$MARKER_START"
      echo 'export PATH="$HOME/bin/python/bin:$HOME/bin/ssl/bin:$HOME/bin:$PATH"'
      echo 'export OPENSSL_INSTALL_PATH="$HOME/bin/ssl"'
      echo "$MARKER_END"
    } >> "$cfg_file"
    rm -f "$tmp_cfg"
  fi
}

TARGET_FILES=()
CURRENT_SHELL="$(basename "${SHELL:-bash}")"

if [ "$OS_FAMILY" = "macos" ]; then
  if [ "$CURRENT_SHELL" = "zsh" ]; then
    TARGET_FILES+=("$HOME/.zshrc")
  elif [ "$CURRENT_SHELL" = "bash" ]; then
    if [ -f "$HOME/.bash_profile" ]; then
      TARGET_FILES+=("$HOME/.bash_profile")
    elif [ -f "$HOME/.bashrc" ]; then
      TARGET_FILES+=("$HOME/.bashrc")
    else
      TARGET_FILES+=("$HOME/.bash_profile")
    fi
  else
    TARGET_FILES+=("$HOME/.zshrc")
  fi
else
  # Linux
  if [ "$CURRENT_SHELL" = "zsh" ]; then
    TARGET_FILES+=("$HOME/.zshrc")
  else
    TARGET_FILES+=("$HOME/.bashrc")
  fi
fi

# Also update any other common shell config files if they already exist
for extra_cfg in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
  if [ -f "$extra_cfg" ]; then
    already_present=0
    for existing in "${TARGET_FILES[@]}"; do
      if [ "$existing" = "$extra_cfg" ]; then
        already_present=1
        break
      fi
    done
    if [ $already_present -eq 0 ]; then
      TARGET_FILES+=("$extra_cfg")
    fi
  fi
done

for cfg in "${TARGET_FILES[@]}"; do
  [ ! -f "$cfg" ] && touch "$cfg"
  update_shell_file "$cfg"
done

# ------------------------------------------------------------------------------
# 7. Verification
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}Installation Complete!${RESET}"
echo "--------------------------------------------------"

export PATH="${INSTALL_BASE}/python/bin:${INSTALL_BASE}/ssl/bin:${INSTALL_BASE}:${PATH}"
export OPENSSL_INSTALL_PATH="${INSTALL_BASE}/ssl"

PY_EXE="${INSTALL_BASE}/python/bin/python3"
SSL_EXE="${INSTALL_BASE}/ssl/bin/openssl"

if [ -x "$PY_EXE" ]; then
  echo -n "Python binary:  "
  "$PY_EXE" -VV
  echo -n "Linked OpenSSL: "
  "$PY_EXE" -c "import ssl; print(ssl.OPENSSL_VERSION)"
fi

if [ -x "$SSL_EXE" ]; then
  echo -n "OpenSSL binary: "
  "$SSL_EXE" version
fi

echo "--------------------------------------------------"
echo -e "${BOLD}To start using Python and OpenSSL in your current shell session:${RESET}"
for cfg in "${TARGET_FILES[@]}"; do
  echo -e "  ${CYAN}source ${cfg}${RESET}"
  break
done
echo "Or open a new terminal window."
