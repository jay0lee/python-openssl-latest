#!/usr/bin/env python3
"""
Unit tests for discover_matrix.py
"""

import unittest
from datetime import date
from scripts.discover_matrix import (
    parse_brownout_from_issue,
    parse_available_runners_from_readme,
)


class TestDiscoverMatrix(unittest.TestCase):

    def test_parse_brownout_from_direct_sentence(self):
        body = "macos-14 was deprecated July 14 and brownouts will begin October 6th, 2026."
        fb, cutoff = parse_brownout_from_issue(body, reference_year=2026)
        self.assertEqual(fb, date(2026, 10, 6))
        self.assertEqual(cutoff, date(2026, 10, 5))

    def test_parse_brownout_from_schedule_list(self):
        body = """
        ### Breaking changes
        GitHub Actions announcing the deprecation process for `macOS 14`.
        The brownouts are scheduled for the following dates and times:
        - October 5, 14:00 UTC - October 6, 00:00 UTC
        - October 12, 14:00 UTC - October 13, 00:00 UTC
        - October 16, 14:00 UTC - October 17, 00:00 UTC
        ### Target date
        Deprecation: July 6th, 2026
        Retirement: November 2nd, 2026
        """
        fb, cutoff = parse_brownout_from_issue(body, reference_year=2026)
        self.assertEqual(fb, date(2026, 10, 5))
        self.assertEqual(cutoff, date(2026, 10, 4))

    def test_parse_brownout_ubuntu22(self):
        body = """
        Deprecation will begin on September 17th, 2026 and the images will be fully unsupported by April 17th, 2027.
        The brownouts are scheduled for the following dates and times:
        March 23, 14:00 UTC - March 23, 00:00 UTC
        March 30, 14:00 UTC - March 30, 00:00 UTC
        """
        fb, cutoff = parse_brownout_from_issue(body, reference_year=2027)
        self.assertEqual(fb, date(2027, 3, 23))
        self.assertEqual(cutoff, date(2027, 3, 22))

    def test_parse_readme_runners_and_cutoff(self):
        sample_readme = """
        ## Available Images

        | Image | Architecture | YAML Label | Included Software |
        | --------------------|--------------|---------------------|------------------|
        | Ubuntu 24.04 | x64 | `ubuntu-24.04` | [ubuntu-24.04] |
        | Ubuntu 24.04 Arm64 | arm64 | `ubuntu-24.04-arm` | [ubuntu-24.04-arm64] |
        | macOS 15 Arm64 | arm64 | `macos-15` | [macOS-15-arm64] |
        | macOS 14 Arm64 [![deprecated](https://img.shields.io/badge/deprecated-E5534B)](https://github.com/actions/runner-images/issues/99999) | arm64 | `macos-14` | [macOS-14-arm64] |
        | Windows Server 2025 | x64 | `windows-2025` | [win25] |
        | Windows 11 Arm64 | arm64 | `windows-11-arm` | [win11] |
        """

        # Mock issue fetching for 99999 in test by monkeypatching or testing with cutoff dates
        # When current_date is 2026-09-26 (before Oct 5 brownout)
        runners_before = parse_available_runners_from_readme(sample_readme, token=None, current_date=date(2026, 9, 26))
        labels_before = [r["os"] for r in runners_before]
        self.assertIn("ubuntu-24.04", labels_before)
        self.assertIn("ubuntu-24.04-arm", labels_before)
        self.assertIn("macos-15", labels_before)
        self.assertIn("windows-2025", labels_before)
        self.assertIn("windows-11-arm", labels_before)

    def test_detect_and_exclude_paid_larger_runners(self):
        sample_readme = """
        ## Available Images

        | Image | Architecture | YAML Label | Included Software |
        | --------------------|--------------|---------------------|------------------|
        | macOS 14 | x64 | `macos-14-large` | [macOS-14] |
        | macOS 14 Arm64 | arm64 | `macos-14` or `macos-14-xlarge` | [macOS-14-arm64] |
        | macOS 15 | x64 | `macos-15-large`, or `macos-15-intel` | [macOS-15] |
        | macOS 15 Arm64 | arm64 | `macos-15`, or `macos-15-xlarge` | [macOS-15-arm64] |
        """
        # Under free_only=True (default)
        runners = parse_available_runners_from_readme(sample_readme, free_only=True)
        
        # macos-14-large should be marked paid=True and active=False
        macos14_intel = next(r for r in runners if r["os"] == "macos-14-large")
        self.assertTrue(macos14_intel["paid"])
        self.assertFalse(macos14_intel["active"])

        # macos-14 arm64 should select free 'macos-14' and NOT 'macos-14-xlarge'
        macos14_arm = next(r for r in runners if r["os"] == "macos-14")
        self.assertFalse(macos14_arm["paid"])
        self.assertTrue(macos14_arm["active"])

        # macos-15 intel should select free 'macos-15-intel' and NOT 'macos-15-large'
        macos15_intel = next(r for r in runners if r["os"] == "macos-15-intel")
        self.assertFalse(macos15_intel["paid"])
        self.assertTrue(macos15_intel["active"])


if __name__ == "__main__":
    unittest.main()

