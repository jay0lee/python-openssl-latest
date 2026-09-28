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
  - Windows builds include Visual Studio MSVC PGO optimizations and native OpenSSL MSBuild property injection via `ExternalProps`.
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
        uses: jay0lee/python-openssl-latest@v1

      - name: Verify Environment
        run: |
          python -VV
          python -c "import ssl; print(f'OpenSSL Version: {ssl.OPENSSL_VERSION}')"
```

### Pinning to an Immutable Release

Consuming workflows can either track the latest build via the floating `@v1` tag or pin a specific immutable release:

```yaml
# Track latest stable release automatically
- uses: jay0lee/python-openssl-latest@v1

# OR pin an exact immutable release (both action code and runtime bundle are pinned)
- uses: jay0lee/python-openssl-latest@v1.2026.09.28.1504

# OR pin via the version input
- uses: jay0lee/python-openssl-latest@v1
  with:
    version: 'v1.2026.09.28.1504'
```

### Action Inputs

| Input | Description | Default |
| :--- | :--- | :--- |
| `version` | Target release tag (e.g. `v1.2026.09.28.1504`) or `latest` | Defaults to action ref if pinned, else `latest` |
| `install-dir` | Custom directory to extract and install into | `$RUNNER_TOOL_CACHE/python-openssl-bundle` |
| `set-env` | Automatically export `PATH`, `PYTHON`, `OPENSSL_INSTALL_PATH`, `LD_LIBRARY_PATH`, and `DYLD_LIBRARY_PATH` | `true` |
| `quiet` | Suppress printing compiler flags & build configuration summary | `false` |
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
  uses: jay0lee/python-openssl-latest@v1

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
- **Free Runner Enforcement**: Detects and excludes paid GitHub Actions Larger Runners (`-large`, `-xlarge` labels). For open-source public repositories, builds strictly use standard free-tier runners (e.g. `macos-15`, `macos-15-intel`, `ubuntu-24.04`, `windows-2025`).
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
  - Fetches externals excluding OpenSSL via `PCBuild\get_externals.bat --no-openssl`.
  - Configures MSBuild to use the locally compiled hardened OpenSSL via native `ExternalProps` hook (`patches\windows\openssl.props`).
  - Compiles with Profile Guided Optimization (`PCBuild\build.bat -c Release -p <arch> --pgo`).
  - Layouts clean distribution with `.\python.bat PC\layout --precompile --preset-default --copy <dest>`.

### 3. Packaging & Publishing
- Bundles are compressed into `python-<py_ver>-openssl-<ossl_ver>-<runner>-<arch>.tar.xz` (or `.zip` for Windows).
- Each build publishes an immutable, timestamped release (e.g. `v1.2026.09.28.1504`) with `--latest`.
- The floating `@v1` git tag is automatically updated on every publish, allowing consumers to track the latest build or pin a specific immutable release.

### 4. GAM & GYB Runtime Validation Suite (`scripts/validate_runtime.py`)
Every compiled Python + OpenSSL runtime bundle undergoes an automated, comprehensive verification suite before packaging (and during end-to-end testing of `action.yml`). The suite uses only Python's standard library with zero third-party dependencies:
- **OpenSSL & TLS Handshake**: Establishes an HTTPS TLS connection to `https://www.googleapis.com` verifying TLS 1.3/1.2 negotiation, modern cipher suites, SNI, ALPN, and system CA root certificates.
- **SQLite3 WAL & High Concurrency**: Tests SQLite batch CRUD operations (10,000 records), Write-Ahead Logging (`PRAGMA journal_mode=WAL`), schema migrations, and thread-safety (`sqlite3.threadsafety == 3`).
- **Multiprocessing Concurrency**: Executes `concurrent.futures.ProcessPoolExecutor` multi-worker process pools (`forkserver` / `spawn`), testing IPC queues, worker initialization, and task distribution across physical CPU cores.
- **Multithreading & Synchronization**: Validates multi-thread worker pool synchronization using `threading.Lock` and `queue.Queue` without race conditions.
- **Compression Engines**: Benchmarks round-trip compression and decompression across `zlib`, `bz2`, and `lzma` (XZ), ensuring GAM / GYB archive handling is fast and intact.
- **Cryptographic Hashing Throughput**: Validates SHA-256 and SHA-512 throughput (> 100 MB/s) backed directly by the compiled OpenSSL `EVP` engine via Python's `_hashlib`.
- **JSON Serialization Accelerator**: Benchmarks high-volume serialization and parsing of Google API response payloads ensuring the C accelerator (`_json`) is active.

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
│       └── openssl.props           # MSBuild properties for OpenSSL linking via ExternalProps
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
