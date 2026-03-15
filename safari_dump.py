#!/usr/bin/env python3
"""
safari_dump.py — Extract all open Safari tabs to Markdown

Uses AppleScript (via osascript) to enumerate all Safari windows and their tabs,
then writes a structured Markdown file with clickable links.

Since Apple doesn't expose Safari Profiles to AppleScript, the intended workflow
is to switch profiles in Safari and run this script once per profile:

    1. Switch to your "Work" profile in Safari
    2. python3 safari_dump.py --profile Work
    3. Switch to your "Personal" profile in Safari
    4. python3 safari_dump.py --profile Personal --append safari-tabs-Work-*.md

Usage:
    python3 safari_dump.py                           # dump all tabs
    python3 safari_dump.py --profile Work            # tag windows as "Work"
    python3 safari_dump.py --profile Personal --append safari-tabs-Work-*.md
    python3 safari_dump.py --close                   # dump then close captured tabs
    python3 safari_dump.py --close --keep gmail.com --keep slack.com
    python3 safari_dump.py --meta                    # also grab page descriptions
    python3 safari_dump.py --exclude mail.google.com --exclude notion.so

Requirements:
    - macOS with Safari running
    - Terminal needs Automation permission for Safari
      (System Settings → Privacy & Security → Automation)
    - For --meta: Safari → Develop → Allow JavaScript from Apple Events
"""

import subprocess
import sys
import os
import re
import json
import argparse
from datetime import datetime
from urllib.parse import urlparse


# ─── AppleScript Helpers ────────────────────────────────────────────────────────

def run_applescript(script: str, timeout: int = 60) -> str:
    """Run an AppleScript and return stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"AppleScript error: {result.stderr.strip()}\n"
            "Make sure Safari is running and Terminal has Automation permission."
        )
    return result.stdout.strip()


def run_applescript_quiet(script: str, timeout: int = 10) -> str:
    """Run an AppleScript, returning empty string on any error (no exceptions)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


# ─── Tab Extraction ─────────────────────────────────────────────────────────────

def get_tab_data(exclude_domains: list[str] = []) -> list[dict]:
    """
    Get all Safari windows and their tabs via AppleScript.
    Returns a list of windows, each containing a list of tabs with title + URL.

    Titles come from Safari's `name of tab` — the page title that's already
    loaded in each tab. No extra fetching needed.
    """
    exclude_domains = list(set(d.lower() for d in (exclude_domains or [])))

    script = '''
    set output to ""
    tell application "Safari"
        set windowCount to count of windows
        repeat with w from 1 to windowCount
            set theWindow to window w
            set tabCount to count of tabs of theWindow
            repeat with t from 1 to tabCount
                set theTab to tab t of theWindow
                set tabTitle to name of theTab
                set tabURL to URL of theTab
                if tabURL is missing value then set tabURL to ""
                if tabTitle is missing value then set tabTitle to "(untitled)"
                set output to output & w & " ||| " & t & " ||| " & tabTitle & " ||| " & tabURL & linefeed
            end repeat
        end repeat
    end tell
    return output
    '''
    raw = run_applescript(script)

    if not raw:
        return []

    windows = {}
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ||| ")
        if len(parts) < 4:
            continue

        win_idx = int(parts[0])
        tab_idx = int(parts[1])
        title = parts[2].strip()
        url = " ||| ".join(parts[3:]).strip()

        # Apply --exclude filter
        domain = domain_from_url(url)
        if domain.lower() in exclude_domains:
            continue

        if win_idx not in windows:
            windows[win_idx] = []

        windows[win_idx].append({
            "index": tab_idx,
            "title": title,
            "url": url,
        })

    result = []
    for win_idx in sorted(windows.keys()):
        tabs = sorted(windows[win_idx], key=lambda t: t["index"])
        if tabs:
            result.append({
                "window": win_idx,
                "tabs": tabs,
            })

    return result


# ─── Metadata Extraction ────────────────────────────────────────────────────────

def fetch_tab_meta(win_idx: int, tab_idx: int) -> dict:
    """
    Extract page metadata from an already-loaded tab via `do JavaScript`.

    This is FREE — the page is already rendered in Safari, we're just reading
    the DOM. No network requests needed.

    Requires: Safari → Develop menu → Allow JavaScript from Apple Events

    Returns dict with: description, og_image, og_title, canonical, author, published
    """
    js = (
        "(function(){"
        "var m=function(s){var el=document.querySelector(s);"
        "return el?(el.content||el.getAttribute('href')||''):'';};"
        "return JSON.stringify({"
        "description:m('meta[name=\"description\"]')||m('meta[property=\"og:description\"]')||'',"
        "og_image:m('meta[property=\"og:image\"]')||m('meta[name=\"twitter:image\"]')||'',"
        "og_title:m('meta[property=\"og:title\"]')||'',"
        "canonical:m('link[rel=\"canonical\"]')||'',"
        "author:m('meta[name=\"author\"]')||m('meta[property=\"article:author\"]')||'',"
        "published:m('meta[property=\"article:published_time\"]')||m('meta[name=\"date\"]')||''"
        "});})()"
    )

    js_escaped = js.replace('\\', '\\\\').replace('"', '\\"')

    script = (
        'tell application "Safari"\n'
        "    try\n"
        f'        set jsResult to do JavaScript "{js_escaped}" in tab {tab_idx} of window {win_idx}\n'
        "        return jsResult\n"
        "    on error\n"
        '        return "{}"\n'
        "    end try\n"
        "end tell"
    )

    raw = run_applescript_quiet(script, timeout=5)

    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def enrich_tabs_with_meta(windows: list[dict]) -> int:
    """Add metadata to each tab from the loaded page. Returns count enriched."""
    enriched = 0
    total = sum(len(w["tabs"]) for w in windows)

    for win in windows:
        for tab in win["tabs"]:
            enriched_so_far = sum(1 for w2 in windows for t in w2["tabs"] if "meta" in t)
            idx = enriched_so_far + 1
            domain = domain_from_url(tab["url"])
            print(f"\r   [{idx}/{total}] {domain or 'blank'}...          ", end="", flush=True)

            meta = fetch_tab_meta(win["window"], tab["index"])
            if meta and any(meta.values()):
                tab["meta"] = meta
                enriched += 1

    print(f"\r   Extracted metadata for {enriched}/{total} tabs          ")
    return enriched


# ─── URL Utilities ───────────────────────────────────────────────────────────────

def domain_from_url(url: str) -> str:
    """Extract a short domain from a URL."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def url_matches_domains(url: str, domains: list[str]) -> bool:
    """Check if a URL matches any domain (supports subdomains)."""
    host = domain_from_url(url).lower()
    for d in domains:
        d = d.lower()
        if host == d or host.endswith("." + d):
            return True
    return False


# ─── Markdown Formatting ────────────────────────────────────────────────────────

def format_markdown(windows: list[dict], profile: str = "") -> str:
    """Format window/tab data as Markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_tabs = sum(len(w["tabs"]) for w in windows)
    total_windows = len(windows)

    profile_label = f" [{profile}]" if profile else ""

    lines = [
        f"# Safari Tabs{profile_label} — {now}",
        "",
        f"{total_tabs} tabs across {total_windows} windows",
        "",
    ]

    for win in windows:
        tab_count = len(win["tabs"])
        if profile:
            lines.append(f"## {profile} — Window {win['window']} ({tab_count} tabs)")
            lines.append(f"<!-- profile: {profile} -->")
        else:
            lines.append(f"## Window {win['window']} ({tab_count} tabs)")
            lines.append(f"<!-- profile: UNKNOWN (use --profile NAME to tag) -->")
        lines.append("")

        for tab in win["tabs"]:
            title = tab["title"] or "(untitled)"
            url = tab["url"]
            domain = domain_from_url(url)

            title = title.replace("[", "\\[").replace("]", "\\]")

            if url:
                domain_suffix = f" — {domain}" if domain else ""
                lines.append(f"- [{title}]({url}){domain_suffix}")
            else:
                lines.append(f"- {title} (no URL — possibly a start page or blank tab)")

            # Add metadata as a blockquote if --meta was used
            meta = tab.get("meta", {})
            desc = (meta.get("description") or "").strip()
            author = (meta.get("author") or "").strip()
            published = (meta.get("published") or "").strip()
            og_image = (meta.get("og_image") or "").strip()

            meta_parts = []
            if desc:
                if len(desc) > 200:
                    desc = desc[:197] + "..."
                meta_parts.append(desc)
            if author:
                meta_parts.append(f"By {author}")
            if published:
                try:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    meta_parts.append(dt.strftime("%b %d, %Y"))
                except Exception:
                    meta_parts.append(published[:10])

            if meta_parts:
                lines.append(f"  > {' · '.join(meta_parts)}")

            if og_image:
                lines.append(f"  > ![]({og_image})")

        lines.append("")

    return "\n".join(lines)


# ─── Tab Closing ─────────────────────────────────────────────────────────────────

def close_tabs(windows: list[dict], keep_domains: list[str] = []):
    """
    Close the specific tabs we captured, leaving others untouched.

    - Closes in reverse order (last tab → first) to avoid index shifting
    - Tabs matching --keep domains are left open
    - Always leaves at least one window with one tab open
    """
    keep_domains = keep_domains or []
    closed = 0
    kept = 0

    # Build list of (window_idx, tab_idx, url) — tabs to close
    close_targets = []
    for win in windows:
        for tab in win["tabs"]:
            if keep_domains and url_matches_domains(tab["url"], keep_domains):
                kept += 1
                continue
            close_targets.append((win["window"], tab["index"], tab["url"]))

    if not close_targets:
        print("   Nothing to close (all tabs matched --keep domains)")
        return

    # Sort reverse: highest window first, highest tab index first
    close_targets.sort(key=lambda x: (x[0], x[1]), reverse=True)

    total = len(close_targets)
    print(f"   Closing {total} tabs" + (f", keeping {kept}" if kept else "") + "...")

    # Group by window and close tabs in reverse index order per window
    tabs_by_window = {}
    for win_idx, tab_idx, url in close_targets:
        if win_idx not in tabs_by_window:
            tabs_by_window[win_idx] = []
        tabs_by_window[win_idx].append(tab_idx)

    for win_idx in sorted(tabs_by_window.keys(), reverse=True):
        tab_indices = sorted(tabs_by_window[win_idx], reverse=True)

        close_lines = [f"            close tab {t}" for t in tab_indices]

        script = (
            'tell application "Safari"\n'
            "    try\n"
            f"        tell window {win_idx}\n"
            + "\n".join(close_lines) + "\n"
            "        end tell\n"
            "    end try\n"
            "end tell"
        )

        try:
            run_applescript(script, timeout=15)
            closed += len(tab_indices)
            print(f"\r   Closed {closed}/{total} tabs...          ", end="", flush=True)
        except RuntimeError:
            pass

    print(f"\r   ✅ Closed {closed} tabs" + (f", kept {kept} (--keep)" if kept else "") + "          ")

    # Clean up any empty windows, ensure at least one remains
    cleanup_script = '''
    tell application "Safari"
        set wCount to count of windows
        repeat with w from wCount to 1 by -1
            try
                if (count of tabs of window w) = 0 then
                    close window w
                end if
            end try
        end repeat
        if (count of windows) = 0 then
            make new document
        end if
    end tell
    '''
    run_applescript_quiet(cleanup_script)


# ─── Append/Merge Logic ─────────────────────────────────────────────────────────

def strip_markdown_header(text: str) -> str:
    """Strip the H1 header and summary line from a Markdown string or file content."""
    lines = text.split("\n") if isinstance(text, str) else text
    content_lines = []
    past_header = False
    for line in (lines if isinstance(lines, list) else lines):
        stripped = line.strip()
        if not past_header:
            if stripped.startswith("# "):
                continue
            if stripped == "":
                continue
            if re.match(r'^\d+ tabs across \d+ windows', stripped):
                continue
            past_header = True
        content_lines.append(line)
    return "\n".join(content_lines) if isinstance(text, str) else "".join(content_lines)


def read_existing_markdown(filepath: str) -> str:
    """Read a Markdown file, stripping its H1 header and summary line."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    return strip_markdown_header(content)


def rewrite_merged_header(existing_md: str, new_md: str, profile: str) -> str:
    """Merge new dump content into existing, rewriting the top-level header."""
    combined = existing_md.rstrip("\n") + "\n\n" + new_md.rstrip("\n") + "\n"

    window_headers = re.findall(r'^## .+\((\d+) tabs\)', combined, re.MULTILINE)
    total_tabs = sum(int(n) for n in window_headers)
    total_windows = len(window_headers)

    profiles = re.findall(r'<!-- profile: (.+?) -->', combined)
    unique_profiles = list(dict.fromkeys(profiles))
    profile_str = ", ".join(unique_profiles) if unique_profiles else "unknown"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = (
        f"# Safari Tabs — {now}\n\n"
        f"{total_tabs} tabs across {total_windows} windows · profiles: {profile_str}\n\n"
    )

    return header + combined


# ─── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Dump all open Safari tabs to a Markdown file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s --profile Work                              tag as Work profile
  %(prog)s --profile Personal -a safari-tabs-Work*.md  append Personal
  %(prog)s --meta                                      include page descriptions
  %(prog)s --close --keep gmail.com --keep slack.com   close tabs, keep some
  %(prog)s --exclude notion.so --exclude figma.com     skip certain domains
        """,
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: auto-generated with timestamp)",
    )
    parser.add_argument(
        "-p", "--profile",
        default="",
        help="Tag all captured windows with this profile name",
    )
    parser.add_argument(
        "-a", "--append",
        metavar="FILE",
        help="Append to an existing dump file (for multi-profile workflows)",
    )
    parser.add_argument(
        "--meta",
        action="store_true",
        help=(
            "Extract page metadata (description, author, date, og:image) from "
            "each loaded tab via JavaScript. Reads the already-rendered DOM — no "
            "network requests. Requires: Safari → Develop → Allow JavaScript "
            "from Apple Events"
        ),
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help=(
            "Close captured tabs after dumping. Only closes tabs that were "
            "captured (not others). Respects --keep. Asks for confirmation."
        ),
    )
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        metavar="DOMAIN",
        help=(
            "With --close: don't close tabs on this domain. "
            "Repeatable: --keep gmail.com --keep slack.com"
        ),
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="DOMAIN",
        help=(
            "Skip tabs on this domain entirely (don't capture or list them). "
            "Repeatable: --exclude mail.google.com --exclude notion.so"
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also output a JSON file alongside the Markdown",
    )
    args = parser.parse_args()

    profile = args.profile.strip()

    # ── Capture ──────────────────────────────────────────
    print("📱 Fetching Safari tabs via AppleScript...")
    if profile:
        print(f"   Profile: {profile}")
    if args.exclude:
        print(f"   Excluding: {', '.join(args.exclude)}")

    try:
        windows = get_tab_data(exclude_domains=args.exclude)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)

    if not windows:
        print("⚠️  No tabs found. Is Safari running with any windows open?")
        sys.exit(0)

    total_tabs = sum(len(w["tabs"]) for w in windows)
    print(f"✅ Found {total_tabs} tabs across {len(windows)} windows")

    # ── Metadata enrichment ──────────────────────────────
    if args.meta:
        print("🔍 Extracting page metadata (reading loaded DOM)...")
        enriched = enrich_tabs_with_meta(windows)
        if enriched == 0:
            print("   ⚠️  No metadata found. Enable: Safari → Develop → Allow JavaScript from Apple Events")

    # ── Format ───────────────────────────────────────────
    new_md = format_markdown(windows, profile=profile)

    # ── Write ────────────────────────────────────────────
    if args.append:
        append_path = args.append
        if not os.path.exists(append_path):
            print(f"❌ Append target not found: {append_path}", file=sys.stderr)
            sys.exit(1)

        print(f"📎 Appending to {append_path}...")
        existing_content = read_existing_markdown(append_path)
        new_sections = strip_markdown_header(new_md)
        merged = rewrite_merged_header(existing_content, new_sections, profile)

        with open(append_path, "w", encoding="utf-8") as f:
            f.write(merged)
        print(f"📝 Updated {append_path}")
        out_path = append_path
    else:
        timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        if args.output:
            out_path = args.output
        elif profile:
            safe_profile = re.sub(r'[^\w\-]', '_', profile)
            out_path = f"safari-tabs-{safe_profile}-{timestamp}.md"
        else:
            out_path = f"safari-tabs-{timestamp}.md"

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(new_md)
        print(f"📝 Written to {out_path}")

    # ── JSON ─────────────────────────────────────────────
    if args.json:
        json_path = out_path.replace(".md", ".json")
        for win in windows:
            win["profile"] = profile
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(windows, f, indent=2, ensure_ascii=False)
        print(f"📝 JSON written to {json_path}")

    # ── Close ────────────────────────────────────────────
    if args.close:
        keep_note = ""
        if args.keep:
            keep_note = f"\n   Keeping tabs on: {', '.join(args.keep)}"

        confirm = input(
            f"⚠️  Close {total_tabs} captured tabs?{keep_note}\n"
            f"   Type 'yes' to confirm: "
        )
        if confirm.strip().lower() == "yes":
            print("🗑️  Closing tabs...")
            close_tabs(windows, keep_domains=args.keep)
        else:
            print("↩️  Skipped closing tabs.")

    # ── Hints ────────────────────────────────────────────
    if not args.append and profile:
        print(f"\n💡 To add another profile, switch Safari and run:")
        print(f"   python3 safari_dump.py --profile <NAME> --append {out_path}")

    print("Done! 🎉")


if __name__ == "__main__":
    main()
