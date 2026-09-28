#!/usr/bin/env python3
"""
Unit tests for build_info.py
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from scripts.build_info import (
    format_build_summary,
    get_openssl_info,
    get_python_info,
    get_or_create_summary,
)


class TestBuildInfo(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_format_build_summary_complete(self):
        py_info = {
            "version": "3.13.0",
            "build_tag": "3.13.0 (main, Oct 2026) [Clang 15.0.0]",
            "compiler": "Clang 15.0.0",
            "cc": "clang",
            "architecture": "arm64",
            "bitness": "64-bit",
            "openssl_version": "OpenSSL 3.5.0",
            "config_args": "--enable-optimizations --with-lto",
            "cflags": "-O3 -Wall",
            "opt": "-DNDEBUG",
            "ldflags": "-Wl,-rpath,/custom",
            "py_cflags": "-O3",
            "openssl_includes": "-I/usr/local/ssl/include",
            "openssl_ldflags": "-L/usr/local/ssl/lib",
            "openssl_libs": "-lssl -lcrypto",
        }
        ossl_info = {
            "version": "OpenSSL 3.5.0 15 Oct 2026",
            "built_on": "Tue Oct 15 12:00:00 2026 UTC",
            "platform": "darwin64-arm64-cc",
            "options": "no-shared no-tests",
            "compiler": "clang -O3",
            "openssldir": "/etc/ssl",
            "modulesdir": "/usr/local/lib/ossl-modules",
            "cpuinfo": "OPENSSL_ia32cap=0x0",
        }

        summary = format_build_summary(
            py_info=py_info,
            ossl_info=ossl_info,
            runner_label="macos-15",
            runner_arch="arm64",
            commit_sha="abcdef123456"
        )

        self.assertIn("Python + OpenSSL Build Configuration & Compiler Flags Summary", summary)
        self.assertIn("Python Version:      3.13.0", summary)
        self.assertIn("OpenSSL Version:     OpenSSL 3.5.0 15 Oct 2026", summary)
        self.assertIn("Target Platform:     macos-15 (arm64)", summary)
        self.assertIn("Binary Architecture: arm64 (64-bit)", summary)
        self.assertIn("Git Commit:          abcdef123456", summary)
        self.assertIn("Platform Target:     darwin64-arm64-cc", summary)
        self.assertIn("Configure Options:   no-shared no-tests", summary)
        self.assertIn("Compiler & Flags:    clang -O3", summary)
        self.assertIn("Configure Arguments: --enable-optimizations --with-lto", summary)
        self.assertIn("CFLAGS:              -O3 -Wall", summary)

    def test_get_or_create_summary_from_existing_file(self):
        # Pre-create BUILD_INFO.txt in install_dir
        expected_text = "PRECOMPILED BUILD INFO SUMMARY TEST"
        info_file = os.path.join(self.temp_dir, "BUILD_INFO.txt")
        with open(info_file, "w", encoding="utf-8") as f:
            f.write(expected_text)

        result = get_or_create_summary(
            install_dir=self.temp_dir,
            runner_label="ubuntu-24.04",
            runner_arch="x64"
        )
        self.assertEqual(result, expected_text)

    def test_get_or_create_summary_generates_and_caches(self):
        summary = get_or_create_summary(
            install_dir=self.temp_dir,
            runner_label="ubuntu-24.04",
            runner_arch="x64",
            commit_sha="commit123"
        )
        self.assertIn("Python + OpenSSL Build Configuration & Compiler Flags Summary", summary)
        self.assertIn("Target Platform:     ubuntu-24.04 (x64)", summary)

        # Check that it was cached to install_dir/BUILD_INFO.txt
        cached_file = os.path.join(self.temp_dir, "BUILD_INFO.txt")
        self.assertTrue(os.path.isfile(cached_file))
        with open(cached_file, "r", encoding="utf-8") as f:
            cached_content = f.read()
        self.assertEqual(cached_content, summary)

    def test_get_openssl_info_parsing(self):
        sample_out = (
            "OpenSSL 3.5.0 15 Oct 2026 (Library: OpenSSL 3.5.0 15 Oct 2026)\n"
            "built on: Tue Oct 15 12:00:00 2026 UTC\n"
            "platform: VC-WIN64-ARM\n"
            "options: bn(64,64)\n"
            "compiler: cl /nologo /O1 /W3\n"
            "OPENSSLDIR: \"C:\\ssl\"\n"
            "MODULESDIR: \"C:\\ssl\\modules\"\n"
        ).encode("utf-8")

        mock_bin = os.path.join(self.temp_dir, "openssl.exe")
        with open(mock_bin, "w") as f:
            f.write("mock")

        with patch("subprocess.check_output", return_value=sample_out):
            info = get_openssl_info(ossl_bin=mock_bin)
            self.assertEqual(info["version"], "OpenSSL 3.5.0 15 Oct 2026 (Library: OpenSSL 3.5.0 15 Oct 2026)")
            self.assertEqual(info["platform"], "VC-WIN64-ARM")
            self.assertEqual(info["compiler"], "cl /nologo /O1 /W3")
            self.assertEqual(info["openssldir"], "C:\\ssl")


if __name__ == "__main__":
    unittest.main()
