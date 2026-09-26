#!/usr/bin/env python3
"""
discover_matrix.py

1. Queries GitHub API for the available GitHub-hosted runner images (actions/runner-images).
2. Detects runner deprecations and brownout schedules:
   - Any runner begins brownouts on Date D -> Stop building starting on (D - 1 day).
3. Queries GitHub API for the latest stable release/tags of Python and OpenSSL.
4. Generates a dynamic GitHub Actions matrix output for Windows, Linux, and macOS runners.
5. Renders a beautiful visual terminal report and GitHub Actions Step Summary.
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


class Style:
    """ANSI color and styling helper with auto-detection and NO_COLOR support."""
    def __init__(self, enabled=True):
        self.enabled = enabled and sys.stderr.isatty() and not os.environ.get("NO_COLOR")
        self.RESET = "\033[0m" if self.enabled else ""
        self.BOLD = "\033[1m" if self.enabled else ""
        self.DIM = "\033[2m" if self.enabled else ""
        self.CYAN = "\033[36m" if self.enabled else ""
        self.GREEN = "\033[32m" if self.enabled else ""
        self.YELLOW = "\033[33m" if self.enabled else ""
        self.RED = "\033[31m" if self.enabled else ""
        self.BLUE = "\033[34m" if self.enabled else ""
        self.MAGENTA = "\033[35m" if self.enabled else ""
        self.WHITE = "\033[37m" if self.enabled else ""

    def bold(self, text):
        return f"{self.BOLD}{text}{self.RESET}"

    def cyan(self, text):
        return f"{self.CYAN}{text}{self.RESET}"

    def green(self, text):
        return f"{self.GREEN}{text}{self.RESET}"

    def yellow(self, text):
        return f"{self.YELLOW}{text}{self.RESET}"

    def red(self, text):
        return f"{self.RED}{text}{self.RESET}"

    def dim(self, text):
        return f"{self.DIM}{text}{self.RESET}"


def visual_width(s):
    """Compute visual monospace column width handling ANSI escapes and wide Unicode."""
    import unicodedata
    s_clean = re.sub(r"\033\[[0-9;]*m", "", s)
    width = 0
    for c in s_clean:
        if unicodedata.combining(c):
            continue
        if unicodedata.east_asian_width(c) in ("W", "F"):
            width += 2
        elif 0x1F000 <= ord(c) <= 0x1FFFF or 0x2600 <= ord(c) <= 0x27BF:
            width += 2
        else:
            width += 1
    return width


def pad_ansi(text, width, align="left"):
    """Pad a string containing ANSI escape codes to a specific visible column width."""
    vis_len = visual_width(text)
    pad = max(0, width - vis_len)
    if align == "right":
        return " " * pad + text
    elif align == "center":
        left = pad // 2
        right = pad - left
        return " " * left + text + " " * right
    return text + " " * pad


def create_ssl_context():
    """Create an SSL context that handles environments with custom CA stores."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
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
    data = github_api_get("https://api.github.com/repos/python/cpython/tags?per_page=100", token)
    if not data:
        return "3.14.7"

    tags = [item["name"] for item in data if isinstance(item, dict) and "name" in item]
    stable_tags = []
    for t in tags:
        if re.match(r"^v\d+\.\d+\.\d+$", t):
            stable_tags.append(t)

    def semver_key(v):
        return [int(x) for x in re.findall(r"\d+", v)]

    stable_tags.sort(key=semver_key, reverse=True)
    if stable_tags:
        return stable_tags[0].lstrip("v")
    return "3.14.7"


def get_latest_openssl_version(token=None):
    """Determine the latest stable OpenSSL tag (e.g. openssl-4.0.2)."""
    data = github_api_get("https://api.github.com/repos/openssl/openssl/tags?per_page=100", token)
    if not data:
        return "4.0.2"

    tags = [item["name"] for item in data if isinstance(item, dict) and "name" in item]
    stable_tags = []
    for t in tags:
        if re.match(r"^openssl-\d+\.\d+\.\d+$", t):
            stable_tags.append(t)

    def semver_key(v):
        return [int(x) for x in re.findall(r"\d+", v)]

    stable_tags.sort(key=semver_key, reverse=True)
    if stable_tags:
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


def parse_available_runners_from_readme(readme_content, token=None, current_date=None, free_only=True):
    """
    Parses actions/runner-images README table of Available Images.
    Resolves deprecations via linked issues and detects paid Larger Runners (-large, -xlarge).
    Filters out any runner if:
      - free_only is True and the runner is a paid Larger Runner
      - current_date >= cutoff_date (where cutoff = first_brownout - 1 day).
    """
    if current_date is None:
        current_date = datetime.now(timezone.utc).date()

    runners = []

    table_match = re.search(r"## Available Images\s*([\s\S]*?)(?=\n## |\Z)", readme_content)
    if not table_match:
        return runners

    table_text = table_match.group(1).strip()
    lines = [line.strip() for line in table_text.split("\n") if line.strip().startswith("|")]
    if len(lines) < 3:
        return runners

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

        if "preview" in image_raw.lower() or "slim" in image_raw.lower() or "xcode" in image_raw.lower():
            continue

        labels = re.findall(r"`([^`]+)`", labels_raw)
        if not labels:
            continue

        # Distinguish free standard labels from paid Larger Runner labels (-large, -xlarge)
        free_labels = [lbl for lbl in labels if not lbl.endswith("-large") and "-large-" not in lbl and "-xlarge" not in lbl]
        paid_labels = [lbl for lbl in labels if lbl not in free_labels]

        # If an image only has -large or -xlarge labels (e.g. Intel macOS 14), it is a paid-only larger runner
        is_paid = (len(free_labels) == 0)

        if is_paid:
            canonical_label = paid_labels[0]
        else:
            canonical_label = None
            for lbl in free_labels:
                if "-latest" not in lbl:
                    canonical_label = lbl
                    break
            if not canonical_label:
                canonical_label = free_labels[0]

        # Deduplicate specialized variant images (e.g. windows-11-vs2026-arm when windows-11-arm is present)
        if "-vs2026" in canonical_label and "windows-11-arm" in labels_raw:
            continue

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

        deprecated = False
        deprecation_issue_id = None
        dep_match = re.search(r"\[!\[deprecated\].*?\]\(https://github\.com/actions/runner-images/issues/(\d+)\)", image_raw)
        if dep_match:
            deprecated = True
            deprecation_issue_id = dep_match.group(1)

        is_active = True
        first_brownout_str = None
        cutoff_date_str = None

        if is_paid and free_only:
            is_active = False

        if deprecated and deprecation_issue_id:
            issue_url = f"https://api.github.com/repos/actions/runner-images/issues/{deprecation_issue_id}"
            issue_data = github_api_get(issue_url, token)
            if issue_data and "body" in issue_data:
                first_brownout, cutoff = parse_brownout_from_issue(issue_data["body"])
                if cutoff:
                    first_brownout_str = str(first_brownout)
                    cutoff_date_str = str(cutoff)
                    if current_date >= cutoff:
                        is_active = False

        runner_entry = {
            "os": canonical_label,
            "os_family": os_family,
            "arch": arch,
            "name": canonical_label,
            "deprecated": deprecated,
            "paid": is_paid,
            "first_brownout": first_brownout_str,
            "cutoff_date": cutoff_date_str,
            "active": is_active,
        }
        runners.append(runner_entry)

    return runners


def get_supported_runners(token=None, current_date=None, free_only=True):
    """Fetch README from actions/runner-images and return active runners."""
    readme_data = github_api_get("https://api.github.com/repos/actions/runner-images/readme", token)
    if readme_data and "content" in readme_data:
        readme_content = base64.b64decode(readme_data["content"]).decode("utf-8")
        all_runners = parse_available_runners_from_readme(readme_content, token, current_date, free_only=free_only)
    else:
        all_runners = [
            {"os": "ubuntu-26.04", "os_family": "linux", "arch": "x64", "name": "ubuntu-26.04", "deprecated": False, "paid": False, "active": True},
            {"os": "ubuntu-26.04-arm", "os_family": "linux", "arch": "arm64", "name": "ubuntu-26.04-arm", "deprecated": False, "paid": False, "active": True},
            {"os": "ubuntu-24.04", "os_family": "linux", "arch": "x64", "name": "ubuntu-24.04", "deprecated": False, "paid": False, "active": True},
            {"os": "ubuntu-24.04-arm", "os_family": "linux", "arch": "arm64", "name": "ubuntu-24.04-arm", "deprecated": False, "paid": False, "active": True},
            {"os": "ubuntu-22.04", "os_family": "linux", "arch": "x64", "name": "ubuntu-22.04", "deprecated": False, "paid": False, "active": True},
            {"os": "ubuntu-22.04-arm", "os_family": "linux", "arch": "arm64", "name": "ubuntu-22.04-arm", "deprecated": False, "paid": False, "active": True},
            {"os": "macos-15", "os_family": "macos", "arch": "arm64", "name": "macos-15", "deprecated": False, "paid": False, "active": True},
            {"os": "macos-15-intel", "os_family": "macos", "arch": "x64", "name": "macos-15-intel", "deprecated": False, "paid": False, "active": True},
            {"os": "macos-26", "os_family": "macos", "arch": "arm64", "name": "macos-26", "deprecated": False, "paid": False, "active": True},
            {"os": "macos-26-intel", "os_family": "macos", "arch": "x64", "name": "macos-26-intel", "deprecated": False, "paid": False, "active": True},
            {"os": "windows-2025", "os_family": "windows", "arch": "x64", "name": "windows-2025", "deprecated": False, "paid": False, "active": True},
            {"os": "windows-2022", "os_family": "windows", "arch": "x64", "name": "windows-2022", "deprecated": False, "paid": False, "active": True},
            {"os": "windows-11-arm", "os_family": "windows", "arch": "arm64", "name": "windows-11-arm", "deprecated": False, "paid": False, "active": True},
        ]

    seen = set()
    active_runners = []
    for r in all_runners:
        key = (r["os"], r["arch"])
        if key not in seen and r.get("active", True):
            seen.add(key)
            active_runners.append(r)

    return active_runners, all_runners


def print_pretty_report(current_date, py_ver, ossl_ver, release_tag, all_runners, active_runners, style):
    """Render a visually stunning, colored Unicode table report to stderr."""
    out = sys.stderr

    # 1. Header Banner
    w = 88
    out.write("\n" + style.cyan("╔" + "═" * (w - 2) + "╗") + "\n")
    title = "🚀 Python & OpenSSL Dynamic Matrix Discovery"
    out.write(style.cyan("║") + " " * ((w - 2 - len(title)) // 2) + style.bold(title) + " " * ((w - 1 - len(title)) // 2) + style.cyan("║") + "\n")
    out.write(style.cyan("╚" + "═" * (w - 2) + "╝") + "\n")

    # 2. Metadata Cards
    out.write(f"  {style.bold('📅 Evaluation Date :')} {style.cyan(str(current_date))} (UTC)\n")
    out.write(f"  {style.bold('🐍 Python Target   :')} {style.green(py_ver)} {style.dim('(Latest Stable)')}\n")
    out.write(f"  {style.bold('🔒 OpenSSL Target  :')} {style.green(ossl_ver)} {style.dim('(Latest Stable)')}\n")
    out.write(f"  {style.bold('🏷️  Release Tag     :')} {style.yellow(release_tag)}\n")
    out.write(style.dim("─" * w) + "\n\n")

    # 3. Unicode Table
    # Columns: OS (10), Label (24), Arch (8), Status (18), Details (24)
    cols = [
        ("OS", 10, "left"),
        ("Runner Label", 24, "left"),
        ("Arch", 8, "center"),
        ("Status", 18, "left"),
        ("Brownout / Cutoff Details", 24, "left")
    ]

    top_border = "┌" + "┬".join("─" * (c[1] + 2) for c in cols) + "┐"
    header_row = "│" + "│".join(" " + pad_ansi(style.bold(c[0]), c[1], c[2]) + " " for c in cols) + "│"
    mid_border = "├" + "┼".join("─" * (c[1] + 2) for c in cols) + "┤"
    bot_border = "└" + "┴".join("─" * (c[1] + 2) for c in cols) + "┘"

    out.write(style.dim(top_border) + "\n")
    out.write(header_row + "\n")
    out.write(style.dim(mid_border) + "\n")

    os_icons = {
        "linux": "🐧 Linux",
        "macos": "🍏 macOS",
        "windows": "🪟 Windows"
    }

    for r in all_runners:
        os_label = os_icons.get(r["os_family"], r["os_family"].capitalize())
        runner_lbl = r["os"]
        arch_lbl = r["arch"]

        if r.get("active", True):
            if r.get("deprecated"):
                status_str = style.yellow("▲ DEPRECATED")
                details_str = f"Cutoff: {r.get('cutoff_date')}"
            else:
                status_str = style.green("● ACTIVE")
                details_str = style.dim("Free Standard Runner")
        else:
            if r.get("paid"):
                status_str = style.yellow("💰 PAID")
                details_str = style.dim("Larger Runner (Excluded)")
            else:
                status_str = style.red("✖ EXCLUDED")
                details_str = style.red(f"Cutoff: {r.get('cutoff_date')}")

        row_str = "│" + "│".join([
            " " + pad_ansi(os_label, cols[0][1], cols[0][2]) + " ",
            " " + pad_ansi(runner_lbl, cols[1][1], cols[1][2]) + " ",
            " " + pad_ansi(arch_lbl, cols[2][1], cols[2][2]) + " ",
            " " + pad_ansi(status_str, cols[3][1], cols[3][2]) + " ",
            " " + pad_ansi(details_str, cols[4][1], cols[4][2]) + " "
        ]) + "│"
        out.write(row_str + "\n")

    out.write(style.dim(bot_border) + "\n\n")

    # 4. Summary Box
    paid_count = sum(1 for r in all_runners if r.get("paid"))
    brownout_count = sum(1 for r in all_runners if not r.get("active", True) and not r.get("paid"))
    excluded_count = len(all_runners) - len(active_runners)

    stats = (
        f"  🎯 {style.bold('Summary:')} {style.green(f'{len(active_runners)} Free Active Targets')} │ "
        f"{style.yellow(f'{paid_count} Paid Excluded')} │ "
        f"{style.red(f'{brownout_count} Brownout Excluded')} │ "
        f"{style.dim(f'{len(all_runners)} Total Evaluated')}\n"
    )
    out.write(stats)
    out.write(style.dim("─" * w) + "\n\n")
    out.flush()


def write_github_step_summary(summary_file, current_date, py_ver, ossl_ver, release_tag, all_runners, active_runners):
    """Generate an interactive, rich Markdown table in the GitHub Actions summary dashboard."""
    if not summary_file:
        return

    paid_count = sum(1 for r in all_runners if r.get("paid"))
    brownout_count = sum(1 for r in all_runners if not r.get("active", True) and not r.get("paid"))
    excluded_count = len(all_runners) - len(active_runners)

    md = []
    md.append("## 🚀 Python & OpenSSL Dynamic Runner Matrix")
    md.append("")
    md.append("| Property | Target Value | Status |")
    md.append("| :--- | :--- | :--- |")
    md.append(f"| **Python Version** | `{py_ver}` | :package: Latest Stable |")
    md.append(f"| **OpenSSL Version** | `{ossl_ver}` | :lock: Hardened GAM Build |")
    md.append(f"| **Release Tag** | `{release_tag}` | :label: Ready for CI |")
    md.append(f"| **Evaluation Date** | `{current_date}` (UTC) | :calendar: Weekly Schedule |")
    md.append("")
    md.append("### Evaluated GitHub Runner Images")
    md.append("")
    md.append("| OS Family | Runner Label | Arch | Status | Brownout Date | Cutoff Date | Notes |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    os_icons = {"linux": "🐧 Linux", "macos": "🍏 macOS", "windows": "🪟 Windows"}

    for r in all_runners:
        icon = os_icons.get(r["os_family"], r["os_family"].capitalize())
        lbl = f"`{r['os']}`"
        arch = f"`{r['arch']}`"
        brownout = r.get("first_brownout") or "—"
        cutoff = r.get("cutoff_date") or "—"

        if r.get("active", True):
            if r.get("deprecated"):
                status = "⚠️ **Active (Deprecated)**"
                note = f"Approaching brownouts on {brownout}"
            else:
                status = "✅ **Active (Free)**"
                note = "Standard Free Runner (GA)"
        else:
            if r.get("paid"):
                status = "💰 **Paid Larger Runner**"
                note = "Excluded (Open-Source Free Tier)"
            else:
                status = "🚫 **Excluded (Brownout)**"
                note = f"Brownout cutoff reached on {cutoff}"

        md.append(f"| {icon} | {lbl} | {arch} | {status} | {brownout} | {cutoff} | {note} |")

    md.append("")
    notices = []
    if paid_count > 0:
        notices.append(f"**{paid_count} paid Larger Runner(s)** excluded for open-source free tier")
    if brownout_count > 0:
        notices.append(f"**{brownout_count} deprecated runner(s)** excluded to protect against brownout failures")

    if notices:
        md.append(f"> [!WARNING]\n> {', and '.join(notices)}.")
    else:
        md.append(f"> [!NOTE]\n> All **{len(active_runners)} evaluated runners** are free standard runners and currently active.")
    md.append("")

    try:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
    except Exception as e:
        print(f"Warning: Failed to write to step summary file {summary_file}: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Discover active runner matrix and latest Python/OpenSSL versions.")
    parser.add_argument("--token", help="GitHub token for API authentication", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--python-version", help="Override Python version")
    parser.add_argument("--openssl-version", help="Override OpenSSL version")
    parser.add_argument("--date", help="Override current date (YYYY-MM-DD) for deprecation testing")
    parser.add_argument("--free-only", action="store_true", default=True, help="Only include standard free runners for public/open-source projects (default: True)")
    parser.add_argument("--allow-paid", action="store_false", dest="free_only", help="Include paid Larger Runners (e.g. -large, -xlarge)")
    parser.add_argument("--output-json", action="store_true", help="Print matrix JSON to stdout")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the matrix JSON on stdout")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI color output")
    parser.add_argument("--summary-file", default=os.environ.get("GITHUB_STEP_SUMMARY"), help="Path to write GitHub Step Summary Markdown")
    args = parser.parse_args()

    style = Style(enabled=not args.no_color)

    current_date = None
    if args.date:
        current_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        current_date = datetime.now(timezone.utc).date()

    # 1. Determine target versions
    py_ver = args.python_version or get_latest_python_version(args.token)
    ossl_ver = args.openssl_version or get_latest_openssl_version(args.token)
    release_tag = f"v{py_ver}-ossl{ossl_ver}"

    # 2. Determine runners
    active_runners, all_runners = get_supported_runners(args.token, current_date, free_only=args.free_only)

    # 3. Print pretty terminal report to stderr
    print_pretty_report(current_date, py_ver, ossl_ver, release_tag, all_runners, active_runners, style)

    # 4. Generate GitHub Step Summary if running in GitHub Actions
    if args.summary_file:
        write_github_step_summary(args.summary_file, current_date, py_ver, ossl_ver, release_tag, all_runners, active_runners)

    # 5. Output JSON to stdout if requested
    matrix_data = {"include": active_runners}
    if args.pretty:
        matrix_json = json.dumps(matrix_data, indent=2)
    else:
        matrix_json = json.dumps(matrix_data)

    if args.output_json:
        print(matrix_json)

    # 6. Export outputs to $GITHUB_OUTPUT
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"matrix={json.dumps(matrix_data)}\n")
            f.write(f"python_version={py_ver}\n")
            f.write(f"openssl_version={ossl_ver}\n")
            f.write(f"release_tag={release_tag}\n")
            f.write(f"active_count={len(active_runners)}\n")
            f.write("should_build=true\n")


if __name__ == "__main__":
    main()
