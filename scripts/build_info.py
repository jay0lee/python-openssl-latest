#!/usr/bin/env python3
"""
build_info.py

Collects, saves, and displays text summaries of build configurations and compiler flags
used for OpenSSL and Python binaries.
"""

import argparse
import datetime
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys


def get_openssl_info(ossl_bin=None, ssl_root=None, env=None):
    """Query OpenSSL binary for compile flags and configuration info."""
    info = {
        "version": None,
        "built_on": None,
        "platform": None,
        "options": None,
        "compiler": None,
        "openssldir": None,
        "modulesdir": None,
        "cpuinfo": None,
    }

    candidate_bins = []
    if ossl_bin:
        candidate_bins.append(ossl_bin)
    if ssl_root:
        candidate_bins.extend([
            os.path.join(ssl_root, "bin", "openssl.exe"),
            os.path.join(ssl_root, "bin", "openssl"),
            os.path.join(ssl_root, "openssl.exe"),
            os.path.join(ssl_root, "openssl"),
        ])

    actual_bin = None
    for cand in candidate_bins:
        if cand and os.path.isfile(cand):
            actual_bin = cand
            break

    if not actual_bin:
        return info

    try:
        out = subprocess.check_output(
            [actual_bin, "version", "-a"],
            env=env,
            stderr=subprocess.STDOUT
        ).decode("utf-8", errors="replace")

        for line in out.splitlines():
            line_str = line.strip()
            if not info["version"] and line_str.startswith("OpenSSL"):
                info["version"] = line_str
            elif line_str.lower().startswith("built on:"):
                info["built_on"] = line_str.split(":", 1)[1].strip()
            elif line_str.lower().startswith("platform:"):
                info["platform"] = line_str.split(":", 1)[1].strip()
            elif line_str.lower().startswith("options:"):
                info["options"] = line_str.split(":", 1)[1].strip()
            elif line_str.lower().startswith("compiler:"):
                info["compiler"] = line_str.split(":", 1)[1].strip()
            elif line_str.lower().startswith("openssldir:"):
                info["openssldir"] = line_str.split(":", 1)[1].strip().strip('"')
            elif line_str.lower().startswith("modulesdir:"):
                info["modulesdir"] = line_str.split(":", 1)[1].strip().strip('"')
            elif line_str.lower().startswith("cpuinfo:"):
                info["cpuinfo"] = line_str.split(":", 1)[1].strip()
    except Exception as e:
        info["error"] = str(e)

    return info


def get_python_info(py_bin=None, env=None):
    """Query Python binary for compile configuration and sysconfig variables."""
    info = {
        "version": None,
        "build_tag": None,
        "compiler": None,
        "architecture": None,
        "bitness": None,
        "config_args": None,
        "cflags": None,
        "opt": None,
        "ldflags": None,
        "cc": None,
        "py_cflags": None,
        "openssl_version": None,
    }

    if not py_bin or not os.path.isfile(py_bin):
        return info

    query_script = """
import sys, ssl, platform, struct, json
try:
    import sysconfig
    sc_keys = ['CONFIG_ARGS', 'CFLAGS', 'OPT', 'CC', 'LDFLAGS', 'PY_CFLAGS', 'OPENSSL_INCLUDES', 'OPENSSL_LDFLAGS', 'OPENSSL_LIBS']
    sc = {k: sysconfig.get_config_var(k) for k in sc_keys if sysconfig.get_config_var(k)}
except Exception:
    sc = {}

data = {
    'version': sys.version.split()[0],
    'build_tag': sys.version,
    'compiler': platform.python_compiler(),
    'bitness': struct.calcsize('P') * 8,
    'machine': platform.machine(),
    'openssl_version': ssl.OPENSSL_VERSION,
    'sysconfig': sc
}
print('__JSON_START__' + json.dumps(data) + '__JSON_END__')
"""

    try:
        out = subprocess.check_output(
            [py_bin, "-c", query_script],
            env=env,
            stderr=subprocess.STDOUT
        ).decode("utf-8", errors="replace")

        m = re.search(r'__JSON_START__(.*?)__JSON_END__', out, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            info["version"] = data.get("version")
            info["build_tag"] = data.get("build_tag")
            info["compiler"] = data.get("compiler")
            info["bitness"] = f"{data.get('bitness')}-bit"
            info["architecture"] = data.get("machine")
            info["openssl_version"] = data.get("openssl_version")
            sc = data.get("sysconfig", {})
            info["config_args"] = sc.get("CONFIG_ARGS")
            info["cflags"] = sc.get("CFLAGS")
            info["opt"] = sc.get("OPT")
            info["ldflags"] = sc.get("LDFLAGS")
            info["cc"] = sc.get("CC")
            info["py_cflags"] = sc.get("PY_CFLAGS")
            info["openssl_includes"] = sc.get("OPENSSL_INCLUDES")
            info["openssl_ldflags"] = sc.get("OPENSSL_LDFLAGS")
            info["openssl_libs"] = sc.get("OPENSSL_LIBS")
    except Exception as e:
        info["error"] = str(e)

    return info


def format_build_summary(py_info, ossl_info, runner_label=None, runner_arch=None, commit_sha=None):
    """Format dictionary info into human-readable monospace text summary."""
    lines = []
    bar = "=" * 80
    sub_bar = "-" * 80

    lines.append(bar)
    lines.append("🚀 Python + OpenSSL Build Configuration & Compiler Flags Summary")
    lines.append(bar)

    # 1. Package & Environment Overview
    lines.append("\n📦 Package & Target Environment:")
    if py_info.get("version"):
        lines.append(f"  • Python Version:      {py_info['version']}")
    if ossl_info.get("version"):
        lines.append(f"  • OpenSSL Version:     {ossl_info['version']}")
    elif py_info.get("openssl_version"):
        lines.append(f"  • OpenSSL Version:     {py_info['openssl_version']}")

    target_env = runner_label or platform.system()
    if runner_arch:
        target_env += f" ({runner_arch})"
    lines.append(f"  • Target Platform:     {target_env}")

    if py_info.get("architecture") or py_info.get("bitness"):
        arch_str = f"{py_info.get('architecture', 'unknown')} ({py_info.get('bitness', 'unknown')})"
        lines.append(f"  • Binary Architecture: {arch_str}")

    if commit_sha:
        lines.append(f"  • Git Commit:          {commit_sha}")
    build_time = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines.append(f"  • Generated At:        {build_time}")

    # 2. OpenSSL Build Configuration & Flags
    lines.append("\n🔒 OpenSSL Build Configuration & Flags:")
    if ossl_info.get("platform"):
        lines.append(f"  • Platform Target:     {ossl_info['platform']}")
    if ossl_info.get("built_on"):
        lines.append(f"  • Build Date:          {ossl_info['built_on']}")
    if ossl_info.get("options"):
        lines.append(f"  • Configure Options:   {ossl_info['options']}")
    if ossl_info.get("compiler"):
        lines.append(f"  • Compiler & Flags:    {ossl_info['compiler']}")
    if ossl_info.get("openssldir"):
        lines.append(f"  • OPENSSLDIR:          {ossl_info['openssldir']}")
    if ossl_info.get("modulesdir"):
        lines.append(f"  • MODULESDIR:          {ossl_info['modulesdir']}")
    if ossl_info.get("cpuinfo"):
        lines.append(f"  • CPU Info:            {ossl_info['cpuinfo']}")

    # 3. Python Build Configuration & Flags
    lines.append("\n🐍 Python Build Configuration & Flags:")
    if py_info.get("build_tag"):
        lines.append(f"  • Build Details:       {py_info['build_tag']}")
    if py_info.get("compiler"):
        lines.append(f"  • Compiler:            {py_info['compiler']}")
    if py_info.get("cc"):
        lines.append(f"  • C Compiler (CC):     {py_info['cc']}")
    if py_info.get("config_args"):
        lines.append(f"  • Configure Arguments: {py_info['config_args']}")
    if py_info.get("cflags"):
        lines.append(f"  • CFLAGS:              {py_info['cflags']}")
    if py_info.get("opt"):
        lines.append(f"  • OPT Flags:           {py_info['opt']}")
    if py_info.get("ldflags"):
        lines.append(f"  • LDFLAGS:             {py_info['ldflags']}")
    if py_info.get("py_cflags"):
        lines.append(f"  • PY_CFLAGS:           {py_info['py_cflags']}")
    if py_info.get("openssl_includes"):
        lines.append(f"  • OpenSSL Includes:    {py_info['openssl_includes']}")
    if py_info.get("openssl_ldflags"):
        lines.append(f"  • OpenSSL LDFLAGS:     {py_info['openssl_ldflags']}")
    if py_info.get("openssl_libs"):
        lines.append(f"  • OpenSSL Libs:        {py_info['openssl_libs']}")

    lines.append("\n" + bar + "\n")
    return "\n".join(lines)


def get_or_create_summary(install_dir, py_bin=None, ssl_root=None, runner_label=None, runner_arch=None, commit_sha=None):
    """Retrieve existing BUILD_INFO.txt from bundle or dynamically generate it."""
    # 1. Search for existing pre-compiled summary file
    search_dirs = [
        install_dir,
        os.path.join(install_dir, "python") if install_dir else None,
        os.path.join(install_dir, "ssl") if install_dir else None,
        ssl_root,
    ]
    for d in search_dirs:
        if d and os.path.isdir(d):
            for candidate_name in ["BUILD_INFO.txt", "BUILD_CONFIG.txt"]:
                fpath = os.path.join(d, candidate_name)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read().strip()
                            if content:
                                return content
                    except Exception:
                        pass

    # 2. Dynamically extract info if pre-compiled file was not present
    py_info = get_python_info(py_bin=py_bin)
    ossl_info = get_openssl_info(ssl_root=ssl_root)
    summary = format_build_summary(
        py_info=py_info,
        ossl_info=ossl_info,
        runner_label=runner_label,
        runner_arch=runner_arch,
        commit_sha=commit_sha
    )

    # Cache to install_dir if writable
    if install_dir and os.path.isdir(install_dir):
        try:
            cache_path = os.path.join(install_dir, "BUILD_INFO.txt")
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(summary)
        except Exception:
            pass

    return summary


def main():
    parser = argparse.ArgumentParser(description="Generate and display build configuration summary.")
    parser.add_argument("--python-bin", help="Path to Python executable")
    parser.add_argument("--openssl-bin", help="Path to OpenSSL binary")
    parser.add_argument("--ssl-root", help="Root directory of OpenSSL installation")
    parser.add_argument("--install-dir", help="Installation root containing python and ssl directories")
    parser.add_argument("--runner-label", default=os.environ.get("RUNNER_LABEL"), help="Runner label (e.g. ubuntu-24.04)")
    parser.add_argument("--runner-arch", default=os.environ.get("RUNNER_ARCH"), help="Architecture (e.g. x64, arm64)")
    parser.add_argument("--commit-sha", default=os.environ.get("GITHUB_SHA"), help="Commit SHA")
    parser.add_argument("--output", help="File path to save the generated text summary")
    parser.add_argument("--quiet", action="store_true", default=False, help="Suppress printing summary to console")
    args = parser.parse_args()

    # Determine binary paths if install_dir provided
    py_bin = args.python_bin
    ssl_root = args.ssl_root
    if args.install_dir and os.path.isdir(args.install_dir):
        if not py_bin:
            for cand in [
                os.path.join(args.install_dir, "python", "bin", "python3"),
                os.path.join(args.install_dir, "python", "python.exe"),
                os.path.join(args.install_dir, "bin", "python3"),
                os.path.join(args.install_dir, "python.exe"),
            ]:
                if os.path.isfile(cand):
                    py_bin = cand
                    break
        if not ssl_root:
            cand_ssl = os.path.join(args.install_dir, "ssl")
            if os.path.isdir(cand_ssl):
                ssl_root = cand_ssl

    py_info = get_python_info(py_bin=py_bin)
    ossl_info = get_openssl_info(ossl_bin=args.openssl_bin, ssl_root=ssl_root)

    summary = format_build_summary(
        py_info=py_info,
        ossl_info=ossl_info,
        runner_label=args.runner_label,
        runner_arch=args.runner_arch,
        commit_sha=args.commit_sha
    )

    if args.output:
        out_dir = os.path.dirname(os.path.abspath(args.output))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"Build configuration summary written to: {args.output}")

    if not args.quiet:
        print(summary)


if __name__ == "__main__":
    main()
