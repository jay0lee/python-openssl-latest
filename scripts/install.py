#!/usr/bin/env python3
"""
install.py

Runtime installer called by the reusable GitHub Action.
1. Detects runner OS and architecture.
2. Discovers matching pre-compiled Python & OpenSSL bundle from repository releases.
3. Downloads, verifies SHA256, and extracts into install directory.
4. Exports environment variables (GITHUB_PATH, GITHUB_ENV, GITHUB_OUTPUT).
5. Verifies Python and OpenSSL functionality.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def create_ssl_context():
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def download_file(url, target_path, token=None):
    """Download a remote URL to target_path with auth if provided."""
    headers = {"User-Agent": "python-openssl-installer"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

    req = urllib.request.Request(url, headers=headers)
    ctx = create_ssl_context()
    print(f"Downloading {url} -> {target_path} ...", flush=True)
    with urllib.request.urlopen(req, context=ctx) as resp, open(target_path, "wb") as f:
        shutil.copyfileobj(resp, f)


def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def detect_runner_info():
    """Detect current runner OS family, specific runner image label, and arch."""
    sys_name = platform.system().lower()
    machine = platform.machine().lower()

    env_os = os.environ.get("RUNNER_OS", "").lower()
    env_arch = os.environ.get("RUNNER_ARCH", "").lower()
    image_os = os.environ.get("ImageOS", "").lower()

    if env_arch in ("arm64", "aarch64") or "arm" in machine or "aarch64" in machine:
        arch = "arm64"
    else:
        arch = "x64"

    os_family = "linux"
    specific_label = None

    if env_os == "macos" or sys_name == "darwin":
        os_family = "macos"
        try:
            ver_out = subprocess.check_output(["sw_vers", "-productVersion"]).decode().strip()
            major = ver_out.split(".")[0]
            if arch == "x64":
                specific_label = f"macos-{major}-intel"
            else:
                specific_label = f"macos-{major}"
        except Exception:
            specific_label = "macos-15" if arch == "arm64" else "macos-15-intel"

    elif env_os == "windows" or sys_name == "windows":
        os_family = "windows"
        if arch == "arm64":
            specific_label = "windows-11-arm"
        elif "2022" in image_os or "win22" in image_os:
            specific_label = "windows-2022"
        else:
            specific_label = "windows-2025"

    else:
        os_family = "linux"
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                content = f.read()
            m = re.search(r'VERSION_ID="?(\d+\.\d+)"?', content)
            if m:
                ver = m.group(1)
                specific_label = f"ubuntu-{ver}" + ("-arm" if arch == "arm64" else "")
        if not specific_label:
            if "22" in image_os:
                specific_label = "ubuntu-22.04" + ("-arm" if arch == "arm64" else "")
            else:
                specific_label = "ubuntu-24.04" + ("-arm" if arch == "arm64" else "")

    return {
        "os_family": os_family,
        "arch": arch,
        "specific_label": specific_label,
    }


def find_release_metadata(repo, version, token=None):
    """Retrieve release info and manifest from GitHub API or direct download."""
    ctx = create_ssl_context()
    headers = {"User-Agent": "python-openssl-installer", "Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

    if version == "latest":
        url = f"https://api.github.com/repos/{repo}/releases/latest"
    else:
        tag = version if version.startswith("v") else f"v{version}"
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Warning: Failed to fetch release details from {url}: {e}", file=sys.stderr)
        return None


def extract_archive(archive_path, dest_dir):
    """Extract .tar.xz or .zip archive to destination directory."""
    print(f"Extracting {archive_path} into {dest_dir}...", flush=True)
    os.makedirs(dest_dir, exist_ok=True)
    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    else:
        # tar.xz or tar.gz
        with tarfile.open(archive_path, "r:*") as tf:
            try:
                tf.extractall(dest_dir, filter="tar")
            except (TypeError, AttributeError):
                tf.extractall(dest_dir)


def main():
    parser = argparse.ArgumentParser(description="Install pre-compiled Python and OpenSSL.")
    parser.add_argument("--repo", default=os.environ.get("PYTHON_OPENSSL_REPOSITORY", "jay0lee/python-openssl-latest"),
                        help="GitHub repository containing the releases")
    parser.add_argument("--version", default="latest", help="Version tag or 'latest'")
    parser.add_argument("--install-dir", help="Target installation directory")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"), help="GitHub token for API access")
    parser.add_argument("--set-env", action="store_true", default=True, help="Set GITHUB_PATH and GITHUB_ENV")
    parser.add_argument("--quiet", action="store_true", default=False,
                        help="Suppress display of build configuration and compiler flags summary")
    args = parser.parse_args()

    runner = detect_runner_info()
    print(f"Detected Runner Environment: {runner['os_family']} | Arch: {runner['arch']} | Label: {runner['specific_label']}")

    # Determine default install directory
    tool_cache = os.environ.get("RUNNER_TOOL_CACHE") or os.environ.get("RUNNER_TEMP") or "/tmp"
    install_dir = args.install_dir or os.path.join(tool_cache, "python-openssl-bundle")

    # Fetch release
    rel_info = find_release_metadata(args.repo, args.version, args.token)
    if not rel_info or "assets" not in rel_info:
        raise RuntimeError(f"Could not locate GitHub release for '{args.version}' in repository '{args.repo}'")

    assets = rel_info.get("assets", [])
    print(f"Found release '{rel_info.get('tag_name')}' with {len(assets)} assets.")

    # Match matching asset:
    # 1. Exact match with runner['specific_label'] and arch
    # 2. Family match with runner['os_family'] and arch
    selected_asset = None
    target_label = runner["specific_label"]
    target_arch = runner["arch"]
    target_family = runner["os_family"]

    valid_extensions = (".zip",) if target_family == "windows" else (".tar.xz", ".tar.gz")
    package_assets = [a for a in assets if any(a["name"].endswith(ext) for ext in valid_extensions)]

    t_arch = target_arch.lower()
    t_label = target_label.lower() if target_label else ""
    t_family = target_family.lower()

    family_tokens = {
        "linux": ["ubuntu", "linux", "debian"],
        "macos": ["macos", "darwin", "osx"],
        "windows": ["windows", "win"],
    }.get(t_family, [t_family])

    # 1. Exact match with specific runner label and arch (accounting for preview/variant tags)
    if t_label:
        clean_label = re.sub(r"-vs\d+", "", t_label)
        for asset in package_assets:
            n = asset["name"].lower()
            if t_arch in n and (t_label in n or clean_label in n):
                selected_asset = asset
                break

    # 2. Family match with runner OS family and arch
    if not selected_asset:
        for asset in package_assets:
            n = asset["name"].lower()
            if t_arch in n and any(tok in n for tok in family_tokens):
                selected_asset = asset
                break

    if not selected_asset:
        available_names = [a["name"] for a in package_assets]
        raise RuntimeError(
            f"No compatible binary package found for {target_label} ({target_arch}) in release assets.\n"
            f"Available packages in release: {available_names}"
        )

    print(f"Selected asset: {selected_asset['name']}")

    # Download asset
    download_dir = os.environ.get("RUNNER_TEMP", "/tmp")
    archive_path = os.path.join(download_dir, selected_asset["name"])
    download_url = selected_asset["browser_download_url"]
    download_file(download_url, archive_path, args.token)

    # Extract
    if os.path.exists(install_dir):
        shutil.rmtree(install_dir)
    extract_archive(archive_path, install_dir)

    # On Linux, remove any DT_RUNPATH/DT_RPATH tags from shared libraries to support staticx
    if runner["os_family"] == "linux":
        patchelf_bin = shutil.which("patchelf")
        if not patchelf_bin:
            try:
                subprocess.call(
                    ["sudo", "apt-get", "install", "-y", "-qq", "patchelf"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                patchelf_bin = shutil.which("patchelf")
            except Exception:
                pass
        if patchelf_bin:
            for root, _, files in os.walk(install_dir):
                for fname in files:
                    if fname.endswith(".so") or ".so." in fname:
                        fpath = os.path.join(root, fname)
                        try:
                            subprocess.call(
                                [patchelf_bin, "--remove-rpath", fpath],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                            )
                        except Exception:
                            pass

        # Also sanitize _sysconfigdata, _sysconfig_vars, and Makefile to remove any -Wl,-rpath flags
        # so C extensions built via pip (like pyscard in GAM) don't inherit invalid/duplicate RPATHs for staticx
        for root, _, files in os.walk(install_dir):
            for fname in files:
                if (fname.startswith("_sysconfigdata") and fname.endswith(".py")) or \
                   (fname.startswith("_sysconfig_vars") and fname.endswith(".json")) or \
                   fname == "Makefile":
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        cleaned = re.sub(r"-Wl,-rpath,('[^']*'|\S+)", "", content)
                        cleaned = re.sub(r"  +", " ", cleaned)
                        with open(fpath, "w", encoding="utf-8") as f:
                            f.write(cleaned)
                    except Exception as e:
                        print(f"Warning: Failed to sanitize {fpath}: {e}", file=sys.stderr)
                elif fname.startswith("_sysconfigdata") and fname.endswith(".pyc"):
                    try:
                        os.remove(os.path.join(root, fname))
                    except Exception:
                        pass


    # Locate Python binary and OpenSSL directory inside extracted bundle
    py_bin = None
    py_root = os.path.join(install_dir, "python")
    ssl_root = os.path.join(install_dir, "ssl")

    if not os.path.exists(py_root):
        py_root = install_dir
    if not os.path.exists(ssl_root):
        ssl_root = install_dir

    if runner["os_family"] == "windows":
        for cand in [os.path.join(py_root, "python.exe"), os.path.join(install_dir, "python.exe")]:
            if os.path.isfile(cand):
                py_bin = cand
                py_root = os.path.dirname(cand)
                break
        py_bin_dir = py_root
    else:
        for cand in [os.path.join(py_root, "bin", "python3"), os.path.join(install_dir, "bin", "python3")]:
            if os.path.isfile(cand):
                py_bin = cand
                py_bin_dir = os.path.dirname(cand)
                break

    if not py_bin or not os.path.exists(py_bin):
        raise RuntimeError(f"Could not find Python executable in {install_dir}")

    print(f"Installed Python: {py_bin}")
    print(f"Installed OpenSSL root: {ssl_root}")

    # Set GITHUB_PATH & GITHUB_ENV
    if args.set_env:
        github_path = os.environ.get("GITHUB_PATH")
        if github_path:
            with open(github_path, "a", encoding="utf-8") as f:
                f.write(f"{py_bin_dir}\n")
                if os.path.exists(os.path.join(ssl_root, "bin")):
                    f.write(f"{os.path.join(ssl_root, 'bin')}\n")

        github_env = os.environ.get("GITHUB_ENV")
        if github_env:
            with open(github_env, "a", encoding="utf-8") as f:
                f.write(f"PYTHON={py_bin}\n")
                f.write(f"OPENSSL_INSTALL_PATH={ssl_root}\n")
                if runner["os_family"] == "linux":
                    lib_paths = f"{os.path.join(py_root, 'lib')}:{os.path.join(ssl_root, 'lib')}:/usr/local/lib"
                    f.write(f"LD_LIBRARY_PATH={lib_paths}:${{LD_LIBRARY_PATH:-}}\n")
                elif runner["os_family"] == "macos":
                    lib_paths = f"{os.path.join(py_root, 'lib')}:{os.path.join(ssl_root, 'lib')}:/usr/local/lib"
                    f.write(f"DYLD_LIBRARY_PATH={lib_paths}:${{DYLD_LIBRARY_PATH:-}}\n")

                # Detect system CA certificate bundle
                system_ca = None
                for ca in ["/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/ca-bundle.pem"]:
                    if os.path.isfile(ca):
                        system_ca = ca
                        break
                if system_ca:
                    f.write(f"SSL_CERT_FILE={system_ca}\n")
                    os.makedirs(os.path.join(ssl_root, "ssl"), exist_ok=True)
                    for dest in [os.path.join(ssl_root, "cert.pem"), os.path.join(ssl_root, "ssl", "cert.pem")]:
                        if not os.path.exists(dest):
                            try:
                                os.symlink(system_ca, dest)
                            except Exception:
                                pass

    # Ensure macOS relocatability via install_name_tool if needed
    if runner["os_family"] == "macos" and shutil.which("install_name_tool"):
        lib_dir = os.path.join(py_root, "lib")
        if os.path.isdir(lib_dir):
            for fname in os.listdir(lib_dir):
                if fname.startswith("libpython") and fname.endswith(".dylib"):
                    dylib_path = os.path.join(lib_dir, fname)
                    subprocess.call(["install_name_tool", "-id", f"@rpath/{fname}", dylib_path], stderr=subprocess.DEVNULL)
                    for py_exec in [os.path.join(py_bin_dir, "python3"), os.path.join(py_bin_dir, "python"), py_bin]:
                        if os.path.isfile(py_exec):
                            try:
                                otool_out = subprocess.check_output(["otool", "-L", py_exec]).decode()
                                for line in otool_out.splitlines():
                                    if fname in line and "@rpath" not in line:
                                        old_ref = line.strip().split()[0]
                                        subprocess.call(["install_name_tool", "-change", old_ref, f"@rpath/{fname}", py_exec], stderr=subprocess.DEVNULL)
                            except Exception:
                                pass

    # Prepare environment for verification commands
    run_env = os.environ.copy()
    if runner["os_family"] == "linux":
        lib_paths = f"{os.path.join(py_root, 'lib')}:{os.path.join(ssl_root, 'lib')}:/usr/local/lib"
        run_env["LD_LIBRARY_PATH"] = f"{lib_paths}:{run_env.get('LD_LIBRARY_PATH', '')}"
    elif runner["os_family"] == "macos":
        lib_paths = f"{os.path.join(py_root, 'lib')}:{os.path.join(ssl_root, 'lib')}:/usr/local/lib"
        run_env["DYLD_LIBRARY_PATH"] = f"{lib_paths}:{run_env.get('DYLD_LIBRARY_PATH', '')}"
    if system_ca:
        run_env["SSL_CERT_FILE"] = system_ca

    # Verify python and openssl
    print("\nVerifying installed bundle:")
    sys.stdout.flush()
    subprocess.check_call([py_bin, "-VV"], env=run_env)
    ver_cmd = [py_bin, "-c", "import ssl; print(f'Using OpenSSL: {ssl.OPENSSL_VERSION}')"]
    subprocess.check_call(ver_cmd, env=run_env)

    # Retrieve or generate build configuration & compiler flags summary
    try:
        from . import build_info
    except (ImportError, ValueError):
        try:
            import build_info
        except ImportError:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import build_info

    summary = build_info.get_or_create_summary(
        install_dir=install_dir,
        py_bin=py_bin,
        ssl_root=ssl_root,
        runner_label=runner.get("specific_label"),
        runner_arch=runner.get("arch"),
    )

    if not args.quiet and summary:
        try:
            print("\n" + summary, flush=True)
        except Exception:
            try:
                safe_summary = summary.encode("ascii", errors="replace").decode("ascii")
                print("\n" + safe_summary, flush=True)
            except Exception:
                pass

    # Set GITHUB_OUTPUT
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        py_ver_out = subprocess.check_output([py_bin, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"], env=run_env).decode().strip()
        ssl_ver_out = subprocess.check_output([py_bin, "-c", "import ssl; print(ssl.OPENSSL_VERSION.split()[1] if ' ' in ssl.OPENSSL_VERSION else ssl.OPENSSL_VERSION)"], env=run_env).decode().strip()
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"python-path={py_bin}\n")
            f.write(f"python-version={py_ver_out}\n")
            f.write(f"openssl-path={ssl_root}\n")
            f.write(f"openssl-version={ssl_ver_out}\n")
            if summary:
                delimiter = f"EOF_SUMMARY_{hashlib.md5(summary.encode()).hexdigest()[:8]}"
                f.write(f"build-summary<<{delimiter}\n{summary}\n{delimiter}\n")

    print("\nSetup completed successfully!")


if __name__ == "__main__":
    main()
