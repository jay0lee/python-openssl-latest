# python-openssl-latest

A reusable GitHub Action and automated weekly build pipeline that compiles and distributes the latest stable versions of **Python** and **OpenSSL** across all currently supported GitHub-hosted runners (**Linux**, **macOS**, and **Windows**, across both **x64** and **arm64** architectures).

The compilation flags and build methodology are modeled directly on [GAM](https://github.com/gam-team/gam) and [GYB](https://github.com/gam-team/got-your-back), producing fully optimized, standalone Python binaries statically linked against custom-hardened OpenSSL.

---

## Features

- **Automated Weekly Builds**: Runs on a weekly schedule (`cron: '0 4 * * 0'`) to detect new stable releases of Python and OpenSSL.
- **Dynamic Runner Discovery**: Automatically queries the GitHub API (`actions/runner-images`) to determine all currently available GitHub-hosted runner environments.
- **Proactive Deprecation & Brownout Handling**: Monitors runner deprecation announcements and brownout schedules. As runners begin deprecation, **they stop being used the day before brownouts start** (e.g., macos-14 brownouts begin October 6th &rarr; builds stop using macos-14 on October 5th).
- **Reusable GitHub Action**: Consuming projects like GAM and GYB can replace hundreds of lines of complex build scripts and brittle caching with a clean 3-line action step.
- **GAM-Hardened Build Specs**:
  - OpenSSL compiled with `no-shared -fPIC`, modern API target (`--api=3.0.0`), and deprecated insecure protocols disabled (`no-tls1`, `no-tls1_1`, `no-weak-ssl-ciphers`, `no-rc4`, etc.).
  - Python compiled with `--enable-optimizations`, `--with-lto`, `--enable-shared`, and relocatable RPATHs.
  - Windows builds include Visual Studio MSVC PGO optimizations and custom OpenSSL project definitions (`openssl.props`, `_hashlib.vcxproj`).
  - Includes compatibility patches for forward-looking Python / OpenSSL combinations (such as Python 3.14 + OpenSSL 4.0).
- **Release Manifest & Fast Discovery**: Releases include `.tar.xz` / `.zip` packages, SHA256 checksums, and a machine-readable `manifest.json` for discovery.

---

## Using in Consuming Projects (GAM, GYB, etc.)

Add the action to your workflow job. It automatically detects the runner's operating system and architecture, downloads the matching pre-compiled bundle, extracts it, configures environment variables, and verifies that `import ssl` reports the expected OpenSSL version.

### Basic Usage (Latest Stable)

```yaml
jobs:
  build:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-24.04, ubuntu-24.04-arm, macos-15, macos-15-intel, windows-2025, windows-11-arm]
    steps:
      - uses: actions/checkout@v4

      - name: Set up latest Python and OpenSSL
        uses: gam-team/python-openssl-latest@v1

      - name: Verify Environment
        run: |
          python -VV
          python -c "import ssl; print(f'OpenSSL Version: {ssl.OPENSSL_VERSION}')"
```

### Pinning to a Specific Version

```yaml
- name: Set up Python and OpenSSL
  uses: gam-team/python-openssl-latest@v1
  with:
    version: 'v3.14.7-ossl4.0.2' # or 'latest'
```

### Action Inputs

| Input | Description | Default |
| :--- | :--- | :--- |
| `version` | Target release tag (e.g. `v3.14.7-ossl4.0.2`) or `latest` | `latest` |
| `install-dir` | Custom directory to extract and install into | `$RUNNER_TOOL_CACHE/python-openssl-bundle` |
| `set-env` | Automatically export `PATH`, `PYTHON`, `OPENSSL_INSTALL_PATH`, `LD_LIBRARY_PATH`, and `DYLD_LIBRARY_PATH` | `true` |
| `github-token` | GitHub token for querying releases and downloading assets | `${{ github.token }}` |

### Action Outputs

| Output | Description |
| :--- | :--- |
| `python-path` | Absolute path to the installed `python` / `python3` executable |
| `python-version` | Version of the installed Python runtime (e.g., `3.14.7`) |
| `openssl-path` | Root directory of the installed OpenSSL headers and libraries |
| `openssl-version` | OpenSSL version string reported by Python's `ssl` module |

---

## Example: Updating GAM's Build Workflow

In GAM's `.github/workflows/build.yml`, consuming this reusable action replaces:
- Cloning OpenSSL, running `./Configure`, compiling, and installing OpenSSL
- Windows NASM installation and link renaming workarounds
- Cloning cpython, applying OpenSSL 4 diffs, running `./configure --with-openssl`, compiling, and installing Python
- Windows `get_externals.bat` and overwriting OpenSSL files
- Manually hashing and saving cache tarballs (`cache.tar.xz`)

**Before:**
```yaml
# GAM previously executed ~150 lines of shell / PowerShell scripts per matrix runner
- name: Cache multiple paths
  uses: actions/cache@v4
  ...
- name: Get latest stable OpenSSL source
  run: ...
- name: Config OpenSSL
  run: ...
- name: Get latest stable Python source
  run: ...
- name: Mac/Linux Configure Python
  run: ...
- name: Tar Cache archive
  run: ...
```

**After:**
```yaml
- name: Set up latest Python and OpenSSL
  uses: gam-team/python-openssl-latest@v1

# $PYTHON, $OPENSSL_INSTALL_PATH, and $PATH are already configured and verified!
- name: Create venv and install dependencies
  run: |
    $PYTHON -m venv .venv
    source .venv/bin/activate
    pip install -r src/requirements.txt
```

---

## How the Automation Works

### 1. Matrix and Version Discovery (`scripts/discover_matrix.py`)
- Fetches the active runner list from `https://api.github.com/repos/actions/runner-images/readme`.
- Identifies all Ubuntu, macOS, and Windows runners across `x64` and `arm64`.
- Checks for deprecation badges linking to issues in `actions/runner-images`.
- Extracts brownout schedules from the deprecation issues.
- **Cutoff Calculation**:
  $$\text{Cutoff Date} = \text{First Brownout Date} - 1\text{ day}$$
  If $\text{Current Date} \ge \text{Cutoff Date}$, the runner is marked inactive and dropped from the build matrix.
- Fetches the latest stable releases from `python/cpython` and `openssl/openssl` (filtering out pre-releases, alphas, betas, and release candidates).

### 2. Compilation
- **OpenSSL**:
  ```bash
  perl ./Configure --libdir=lib --prefix="$INSTALL_DIR" \
    no-fips --api=3.0.0 no-docs no-tls1 no-tls1_1 no-dtls no-comp \
    no-srp no-psk no-nextprotoneg no-weak-ssl-ciphers no-idea no-seed \
    no-camellia no-sm2 no-sm3 no-sm4 no-rc2 no-rc4 no-rc5 no-md2 no-md4 \
    no-cast no-des no-shared -fPIC no-tests -O3
  make -j$(nproc)
  make install_sw
  ```
- **Python (Unix)**:
  ```bash
  ./configure --with-openssl="$OPENSSL_INSTALL" \
              --prefix="$PYTHON_INSTALL" \
              --enable-shared \
              --with-ensurepip=upgrade \
              --enable-optimizations \
              --with-lto \
              --disable-test-modules \
              --without-doc-strings
  make -j$(nproc)
  make altinstall && make bininstall
  ```
- **Python (Windows)**:
  - Fetches externals via `PCBuild\get_externals.bat`.
  - Replaces external OpenSSL binaries/headers with the locally compiled hardened OpenSSL.
  - Applies custom `openssl.props` and `_hashlib.vcxproj`.
  - Compiles with Profile Guided Optimization (`PCBuild\build.bat -c Release -p <arch> --pgo`).
  - Layouts clean distribution with `.\python.bat PC\layout --precompile --preset-default --copy <dest>`.

### 3. Packaging & Publishing
- Bundles are compressed into `python-<py_ver>-openssl-<ossl_ver>-<runner>-<arch>.tar.xz` (or `.zip` for Windows).
- SHA256 checksums are generated and published alongside a structured `manifest.json`.
- Both version-specific releases (`v3.14.7-ossl4.0.2`) and a floating `latest` release are published.

---

## Local Development and Testing

Run the test suite:
```bash
python3 -m unittest discover -s tests -v
```

Test dynamic runner matrix discovery:
```bash
python3 scripts/discover_matrix.py --output-json
```

Test deprecation cutoff simulation (e.g. simulating date 2026-10-05 when macOS 14 begins brownouts):
```bash
python3 scripts/discover_matrix.py --date 2026-10-05 --output-json
```

---

## Repository Structure

```
├── .github/
│   └── workflows/
│       ├── build-and-release.yml   # Weekly scheduled matrix build and release workflow
│       └── test-action.yml         # CI tests for action and discovery scripts
├── action.yml                      # Reusable GitHub Action definition
├── patches/
│   ├── py314-ossl4.diff            # Python 3.14 + OpenSSL 4.0 compatibility patch
│   └── windows/
│       ├── openssl.props           # MSBuild properties for OpenSSL linking
│       └── _hashlib.vcxproj        # Visual Studio project file for _hashlib
├── scripts/
│   ├── discover_matrix.py          # Dynamic matrix and version discovery
│   ├── build_openssl.sh            # Unix OpenSSL build script
│   ├── build_python.sh             # Unix Python build script
│   ├── build_openssl.ps1           # Windows OpenSSL build script
│   ├── build_python.ps1            # Windows Python build script
│   └── install.py                  # Client installer called by action.yml
├── tests/
│   └── test_discover_matrix.py     # Unit tests for runner and brownout parsing
└── README.md
```

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.
