#!/usr/bin/env python3
"""
discover_matrix.py

1. Queries GitHub API for the available GitHub-hosted runner images (actions/runner-images).
2. Detects runner deprecations and brownout schedules:
   - Any runner begins brownouts on Date D -> Stop building starting on (D - 1 day).
3. Queries GitHub API for the latest stable release/tags of Python and OpenSSL.
4. Generates a dynamic GitHub Actions matrix output for Windows, Linux, and macOS runners.
"""

import argparse
import base64
import json
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone


def create_ssl_context():
    """Create an SSL context that handles environments with custom CA stores."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        # Fallback for environments with strict local sandbox certificate hurdles
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def github_api_get(url, token=None):
    """Make an authenticated GET request to GitHub API with fallback."""
    headers = {
        "User-Agent": "python-openssl-matrix-discovery",
        "Accept": "application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

    req = urllib.request.Request(url, headers=headers)
    ctx = create_ssl_context()
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Warning: Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def get_latest_python_version(token=None):
    """Determine the latest stable CPython tag (e.g. v3.14.7)."""
    # Prefer releases API, fallback to tags
    data = github_api_get("https://api.github.com/repos/python/cpython/tags?per_page=100", token)
    if not data:
        # Fallback default if API rate limited without token
        return "3.14.7"

    tags = [item["name"] for item in data if isinstance(item, dict) and "name" in item]
    # Filter stable tags: vX.Y.Z without a, b, rc
    stable_tags = []
    for t in tags:
        if re.match(r"^v\d+\.\d+\.\d+$", t):
            stable_tags.append(t)

    def semver_key(v):
        return [int(x) for x in re.findall(r"\d+", v)]

    stable_tags.sort(key=semver_key, reverse=True)
    if stable_tags:
        # Return stripped version without leading 'v'
        return stable_tags[0].lstrip("v")
    return "3.14.7"


def get_latest_openssl_version(token=None):
    """Determine the latest stable OpenSSL tag (e.g. openssl-4.0.2 or openssl-3.4.0)."""
    data = github_api_get("https://api.github.com/repos/openssl/openssl/tags?per_page=100", token)
    if not data:
        return "4.0.2"

    tags = [item["name"] for item in data if isinstance(item, dict) and "name" in item]
    stable_tags = []
    for t in tags:
        # Match openssl-X.Y.Z, ignore alpha, beta, rc
        if re.match(r"^openssl-\d+\.\d+\.\d+$", t):
            stable_tags.append(t)

    def semver_key(v):
        return [int(x) for x in re.findall(r"\d+", v)]

    stable_tags.sort(key=semver_key, reverse=True)
    if stable_tags:
        # Return tag without 'openssl-' prefix
        return stable_tags[0].replace("openssl-", "")
    return "4.0.2"


def parse_brownout_from_issue(issue_body, reference_year=None):
    """
    Extract the earliest brownout date from a GitHub deprecation issue body.
    Returns (first_brownout_date, cutoff_date).
    Cutoff date is strictly (first_brownout_date - 1 day).
    """
    if not issue_body:
        return None, None

    months = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
    }

    # Extract year mentioned in issue or reference year
    if reference_year is None:
        year_match = re.search(r"202\d", issue_body)
        reference_year = int(year_match.group(0)) if year_match else datetime.now(timezone.utc).year

    dates = []

    # Pattern A: 'brownouts will begin [on] Month Day'
    begin_match = re.search(r"brownouts?\s+(?:will\s+)?begin\s+(?:on\s+)?([A-Za-z]+)\s+(\d{1,2})", issue_body, re.IGNORECASE)
    if begin_match:
        m_str = begin_match.group(1).lower()
        if m_str in months:
            m_num = months[m_str]
            day = int(begin_match.group(2))
            try:
                dates.append(datetime(reference_year, m_num, day).date())
            except Exception:
                pass

    # Pattern B: 'The brownouts are scheduled for the following dates and times:' list
    section_match = re.search(r"brownouts?.*?:([\s\S]*?)(?=###|\n\n\n|\Z)", issue_body, re.IGNORECASE)
    if section_match:
        lines = section_match.group(1).split("\n")
        for line in lines:
            line = line.strip()
            # e.g., 'October 5, 14:00 UTC - October 6, 00:00 UTC'
            dm = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(\d{4}))?", line)
            if dm:
                m_str = dm.group(1).lower()
                if m_str in months:
                    m_num = months[m_str]
                    day = int(dm.group(2))
                    yr = int(dm.group(3)) if dm.group(3) else reference_year
                    try:
                        dates.append(datetime(yr, m_num, day).date())
                    except Exception:
                        pass

    if dates:
        dates.sort()
        first_brownout = dates[0]
        cutoff = first_brownout - timedelta(days=1)
        return first_brownout, cutoff

    # Fallback: check retirement date if no brownout is announced yet
    retire_match = re.search(r"(?:unsupported|retired|retirement).*?([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})", issue_body, re.IGNORECASE)
    if retire_match:
        m_str = retire_match.group(1).lower()
        if m_str in months:
            m_num = months[m_str]
            day = int(retire_match.group(2))
            yr = int(retire_match.group(3))
            try:
                retire_date = datetime(yr, m_num, day).date()
                cutoff = retire_date - timedelta(days=1)
                return retire_date, cutoff
            except Exception:
                pass

    return None, None


def parse_available_runners_from_readme(readme_content, token=None, current_date=None):
    """
    Parses actions/runner-images README table of Available Images.
    Resolves deprecations via linked issues.
    Filters out any runner if current_date >= cutoff_date (where cutoff = first_brownout - 1 day).
    """
    if current_date is None:
        current_date = datetime.now(timezone.utc).date()

    runners = []

    # Find the Available Images section
    table_match = re.search(r"## Available Images\s*([\s\S]*?)(?=\n## |\Z)", readme_content)
    if not table_match:
        return runners

    table_text = table_match.group(1).strip()
    lines = [line.strip() for line in table_text.split("\n") if line.strip().startswith("|")]
    if len(lines) < 3:
        return runners

    # Parse header to identify columns
    header_cols = [c.strip().lower() for c in lines[0].split("|")[1:-1]]
    image_idx = 0
    arch_idx = 1
    label_idx = 2

    for i, col in enumerate(header_cols):
        if "image" in col:
            image_idx = i
        elif "arch" in col:
            arch_idx = i
        elif "yaml" in col or "label" in col:
            label_idx = i

    for line in lines[2:]:
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if len(cols) <= max(image_idx, arch_idx, label_idx):
            continue

        image_raw = cols[image_idx]
        arch_raw = cols[arch_idx].lower()
        labels_raw = cols[label_idx]

        # Skip previews, beta or special variants not part of standard builds
        if "preview" in image_raw.lower() or "slim" in image_raw.lower() or "xcode" in image_raw.lower():
            continue

        # Extract primary labels
        labels = re.findall(r"`([^`]+)`", labels_raw)
        if not labels:
            continue

        # Choose the canonical runner label (avoiding generic -latest and -large/-xlarge when possible)
        canonical_label = None
        for lbl in labels:
            # We want specific versioned labels like 'ubuntu-24.04', 'ubuntu-24.04-arm', 'macos-15', 'windows-2025'
            if "-latest" not in lbl and "-xlarge" not in lbl and not lbl.endswith("-large"):
                canonical_label = lbl
                break
        if not canonical_label:
            canonical_label = labels[0]

        # Normalize OS family and runner arch
        os_lower = canonical_label.lower()
        if "ubuntu" in os_lower:
            os_family = "linux"
        elif "macos" in os_lower or "osx" in os_lower:
            os_family = "macos"
        elif "windows" in os_lower or "win" in os_lower:
            os_family = "windows"
        else:
            continue

        arch = "arm64" if ("arm" in arch_raw or "arm" in canonical_label.lower()) else "x64"

        # Check deprecation
        deprecated = False
        deprecation_issue_id = None
        dep_match = re.search(r"\[!\[deprecated\].*?\]\(https://github\.com/actions/runner-images/issues/(\d+)\)", image_raw)
        if dep_match:
            deprecated = True
            deprecation_issue_id = dep_match.group(1)

        is_active = True
        first_brownout_str = None
        cutoff_date_str = None

        if deprecated and deprecation_issue_id:
            # Fetch issue details
            issue_url = f"https://api.github.com/repos/actions/runner-images/issues/{deprecation_issue_id}"
            issue_data = github_api_get(issue_url, token)
            if issue_data and "body" in issue_data:
                first_brownout, cutoff = parse_brownout_from_issue(issue_data["body"])
                if cutoff:
                    first_brownout_str = str(first_brownout)
                    cutoff_date_str = str(cutoff)
                    # "stop being used the day before it starts browning out"
                    if current_date >= cutoff:
                        is_active = False

        runner_entry = {
            "os": canonical_label,
            "os_family": os_family,
            "arch": arch,
            "name": f"{os_family.capitalize()} {arch} ({canonical_label})",
            "deprecated": deprecated,
            "first_brownout": first_brownout_str,
            "cutoff_date": cutoff_date_str,
            "active": is_active,
        }
        runners.append(runner_entry)

    return runners


def get_supported_runners(token=None, current_date=None):
    """Fetch README from actions/runner-images and return active runners."""
    readme_data = github_api_get("https://api.github.com/repos/actions/runner-images/readme", token)
    if readme_data and "content" in readme_data:
        readme_content = base64.b64decode(readme_data["content"]).decode("utf-8")
        all_runners = parse_available_runners_from_readme(readme_content, token, current_date)
    else:
        # Offline/fallback default runners if API is unreachable
        all_runners = [
            {"os": "ubuntu-26.04", "os_family": "linux", "arch": "x64", "name": "Linux x64 (ubuntu-26.04)", "active": True},
            {"os": "ubuntu-26.04-arm", "os_family": "linux", "arch": "arm64", "name": "Linux arm64 (ubuntu-26.04-arm)", "active": True},
            {"os": "ubuntu-24.04", "os_family": "linux", "arch": "x64", "name": "Linux x64 (ubuntu-24.04)", "active": True},
            {"os": "ubuntu-24.04-arm", "os_family": "linux", "arch": "arm64", "name": "Linux arm64 (ubuntu-24.04-arm)", "active": True},
            {"os": "ubuntu-22.04", "os_family": "linux", "arch": "x64", "name": "Linux x64 (ubuntu-22.04)", "active": True},
            {"os": "ubuntu-22.04-arm", "os_family": "linux", "arch": "arm64", "name": "Linux arm64 (ubuntu-22.04-arm)", "active": True},
            {"os": "macos-15", "os_family": "macos", "arch": "arm64", "name": "Macos arm64 (macos-15)", "active": True},
            {"os": "macos-15-intel", "os_family": "macos", "arch": "x64", "name": "Macos x64 (macos-15-intel)", "active": True},
            {"os": "macos-26", "os_family": "macos", "arch": "arm64", "name": "Macos arm64 (macos-26)", "active": True},
            {"os": "macos-26-intel", "os_family": "macos", "arch": "x64", "name": "Macos x64 (macos-26-intel)", "active": True},
            {"os": "windows-2025", "os_family": "windows", "arch": "x64", "name": "Windows x64 (windows-2025)", "active": True},
            {"os": "windows-2022", "os_family": "windows", "arch": "x64", "name": "Windows x64 (windows-2022)", "active": True},
            {"os": "windows-11-arm", "os_family": "windows", "arch": "arm64", "name": "Windows arm64 (windows-11-arm)", "active": True},
        ]

    # Deduplicate by (os, arch) and keep only active
    seen = set()
    active_runners = []
    for r in all_runners:
        key = (r["os"], r["arch"])
        if key not in seen and r.get("active", True):
            seen.add(key)
            active_runners.append(r)

    return active_runners, all_runners


def main():
    parser = argparse.ArgumentParser(description="Discover active runner matrix and latest Python/OpenSSL versions.")
    parser.add_argument("--token", help="GitHub token for API authentication", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--python-version", help="Override Python version")
    parser.add_argument("--openssl-version", help="Override OpenSSL version")
    parser.add_argument("--date", help="Override current date (YYYY-MM-DD) for deprecation testing")
    parser.add_argument("--output-json", action="store_true", help="Print matrix JSON to stdout")
    args = parser.parse_args()

    current_date = None
    if args.date:
        current_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        current_date = datetime.now(timezone.utc).date()

    print(f"Current evaluation date: {current_date}", file=sys.stderr)

    # 1. Determine versions
    py_ver = args.python_version or get_latest_python_version(args.token)
    ossl_ver = args.openssl_version or get_latest_openssl_version(args.token)
    release_tag = f"v{py_ver}-ossl{ossl_ver}"

    print(f"Latest Python: {py_ver}", file=sys.stderr)
    print(f"Latest OpenSSL: {ossl_ver}", file=sys.stderr)
    print(f"Target release tag: {release_tag}", file=sys.stderr)

    # 2. Determine runners
    active_runners, all_runners = get_supported_runners(args.token, current_date)

    print("\n--- Runner Discovery Summary ---", file=sys.stderr)
    for r in all_runners:
        status = "ACTIVE" if r.get("active", True) else f"EXCLUDED (Cutoff: {r.get('cutoff_date')}, First Brownout: {r.get('first_brownout')})"
        print(f"  [{r['os_family'].upper()}] {r['os']} ({r['arch']}): {status}", file=sys.stderr)

    matrix_data = {"include": active_runners}
    matrix_json = json.dumps(matrix_data)

    if args.output_json:
        print(matrix_json)

    # Output to GitHub Actions environment if running in workflow
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"matrix={matrix_json}\n")
            f.write(f"python_version={py_ver}\n")
            f.write(f"openssl_version={ossl_ver}\n")
            f.write(f"release_tag={release_tag}\n")
            f.write(f"active_count={len(active_runners)}\n")
            f.write("should_build=true\n")
        print("\nExported outputs to $GITHUB_OUTPUT", file=sys.stderr)


if __name__ == "__main__":
    main()
