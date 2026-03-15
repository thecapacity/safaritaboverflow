#!/usr/bin/env python3
"""
cleanup.py — Deduplicate and organize Safari tab/bookmark exports

Takes one or more Markdown files produced by safari_dump.py or bookmarks_dump.py
and produces a cleaned version with:
  1. Duplicate URLs removed (keeps the first occurrence)
  2. Optional sorting by domain within each section
  3. Stats on what was removed

Usage:
    python3 cleanup.py safari-tabs-*.md                   # clean one or more files
    python3 cleanup.py tabs.md bookmarks.md -o merged.md  # merge and clean
    python3 cleanup.py tabs.md --sort                     # sort by domain within sections
    python3 cleanup.py tabs.md --flat                     # flatten all into one list, grouped by domain
"""

import re
import sys
import argparse
from datetime import datetime
from urllib.parse import urlparse
from collections import OrderedDict


# Regex to match markdown links: - [title](url) with optional suffix
LINK_RE = re.compile(r'^(\s*-\s+)\[([^\]]*)\]\(([^)]+)\)(.*)')
# Regex to match section headers
HEADER_RE = re.compile(r'^(#{1,6})\s+(.*)')
# Regex to match bare URLs on a line
BARE_URL_RE = re.compile(r'^(\s*-\s+)(https?://\S+)(.*)')


def normalize_url(url: str) -> str:
    """Normalize a URL for dedup comparison."""
    url = url.strip().rstrip("/")
    # Remove common tracking parameters
    try:
        parsed = urlparse(url)
        # Strip fragments
        url = parsed._replace(fragment="").geturl().rstrip("/")
    except Exception:
        pass
    return url.lower()


def domain_from_url(url: str) -> str:
    """Extract domain for sorting."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host.lower()
    except Exception:
        return ""


def parse_markdown_file(filepath: str) -> list[dict]:
    """
    Parse a Markdown file into a list of structured items.
    
    Each item is either:
      {"type": "header", "level": int, "text": str, "raw": str}
      {"type": "link", "title": str, "url": str, "suffix": str, "indent": str, "raw": str}
      {"type": "text", "raw": str}
    """
    items = []
    
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            
            # Check for header
            header_match = HEADER_RE.match(line)
            if header_match:
                items.append({
                    "type": "header",
                    "level": len(header_match.group(1)),
                    "text": header_match.group(2),
                    "raw": line,
                })
                continue
            
            # Check for markdown link
            link_match = LINK_RE.match(line)
            if link_match:
                items.append({
                    "type": "link",
                    "indent": link_match.group(1),
                    "title": link_match.group(2),
                    "url": link_match.group(3),
                    "suffix": link_match.group(4),
                    "raw": line,
                })
                continue
            
            # Check for bare URL
            bare_match = BARE_URL_RE.match(line)
            if bare_match:
                items.append({
                    "type": "link",
                    "indent": bare_match.group(1),
                    "title": bare_match.group(2),
                    "url": bare_match.group(2),
                    "suffix": bare_match.group(3),
                    "raw": line,
                })
                continue
            
            # Everything else
            items.append({
                "type": "text",
                "raw": line,
            })
    
    return items


def deduplicate(items: list[dict]) -> tuple[list[dict], int]:
    """
    Remove duplicate URLs, keeping the first occurrence.
    Returns (cleaned_items, num_removed).
    """
    seen_urls = set()
    result = []
    removed = 0
    
    for item in items:
        if item["type"] == "link":
            norm = normalize_url(item["url"])
            if norm in seen_urls:
                removed += 1
                continue
            seen_urls.add(norm)
        result.append(item)
    
    return result, removed


def sort_sections_by_domain(items: list[dict]) -> list[dict]:
    """
    Sort links within each section (between headers) by domain.
    Preserves header order and non-link content.
    """
    result = []
    current_section_links = []
    current_section_other = []  # non-link items between links
    
    def flush_section():
        """Sort accumulated links and add them to result."""
        if current_section_links:
            sorted_links = sorted(
                current_section_links,
                key=lambda item: (domain_from_url(item["url"]), item["title"].lower())
            )
            result.extend(sorted_links)
            current_section_links.clear()
        result.extend(current_section_other)
        current_section_other.clear()
    
    for item in items:
        if item["type"] == "header":
            flush_section()
            result.append(item)
        elif item["type"] == "link":
            current_section_links.append(item)
        else:
            # Preserve blank lines and comments between links
            if current_section_links:
                current_section_other.append(item)
            else:
                result.append(item)
    
    flush_section()
    return result


def flatten_by_domain(items: list[dict]) -> list[dict]:
    """
    Ignore existing sections and regroup all links by domain.
    """
    # Collect all links
    links = [item for item in items if item["type"] == "link"]
    
    if not links:
        return items
    
    # Group by domain
    domain_groups = OrderedDict()
    for link in links:
        domain = domain_from_url(link["url"]) or "(other)"
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(link)
    
    # Sort domains alphabetically
    sorted_domains = sorted(domain_groups.keys())
    
    # Build new document
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = [
        {"type": "header", "level": 1, "text": f"Safari Links by Domain — {now}", "raw": f"# Safari Links by Domain — {now}"},
        {"type": "text", "raw": ""},
        {"type": "text", "raw": f"{len(links)} links across {len(sorted_domains)} domains"},
        {"type": "text", "raw": ""},
    ]
    
    for domain in sorted_domains:
        domain_links = domain_groups[domain]
        result.append({
            "type": "header",
            "level": 2,
            "text": f"{domain} ({len(domain_links)})",
            "raw": f"## {domain} ({len(domain_links)})",
        })
        result.append({"type": "text", "raw": ""})
        result.extend(sorted(domain_links, key=lambda l: l["title"].lower()))
        result.append({"type": "text", "raw": ""})
    
    return result


def items_to_markdown(items: list[dict]) -> str:
    """Convert structured items back to Markdown text."""
    lines = []
    for item in items:
        if item["type"] == "link":
            title = item["title"]
            url = item["url"]
            suffix = item.get("suffix", "")
            indent = item.get("indent", "- ")
            lines.append(f"{indent}[{title}]({url}){suffix}")
        else:
            lines.append(item["raw"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate and organize Safari tab/bookmark Markdown exports"
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="One or more Markdown files to process",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: adds '-clean' suffix to first input)",
    )
    parser.add_argument(
        "--sort",
        action="store_true",
        help="Sort links by domain within each section",
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        help="Flatten all links and regroup by domain (ignores existing sections)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        default=True,
        help="Print stats about duplicates found (default: on)",
    )
    args = parser.parse_args()
    
    # Parse all input files
    all_items = []
    for filepath in args.files:
        print(f"📄 Reading {filepath}...")
        try:
            items = parse_markdown_file(filepath)
            all_items.extend(items)
            link_count = sum(1 for i in items if i["type"] == "link")
            print(f"   Found {link_count} links")
        except FileNotFoundError:
            print(f"❌ File not found: {filepath}", file=sys.stderr)
            sys.exit(1)
    
    total_before = sum(1 for i in all_items if i["type"] == "link")
    
    # Step 1: Deduplicate
    print("\n🔍 Removing duplicates...")
    cleaned, num_removed = deduplicate(all_items)
    total_after = sum(1 for i in cleaned if i["type"] == "link")
    print(f"   Removed {num_removed} duplicates ({total_before} → {total_after} links)")
    
    # Step 2: Sort or flatten
    if args.flat:
        print("📊 Flattening and grouping by domain...")
        cleaned = flatten_by_domain(cleaned)
    elif args.sort:
        print("📊 Sorting by domain within sections...")
        cleaned = sort_sections_by_domain(cleaned)
    
    # Write output
    if args.output:
        out_path = args.output
    else:
        base = args.files[0]
        if base.endswith(".md"):
            out_path = base[:-3] + "-clean.md"
        else:
            out_path = base + "-clean.md"
    
    md = items_to_markdown(cleaned)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    
    print(f"\n📝 Written to {out_path}")
    
    # Domain stats
    if args.stats:
        domain_counts = {}
        for item in cleaned:
            if item["type"] == "link":
                d = domain_from_url(item["url"]) or "(other)"
                domain_counts[d] = domain_counts.get(d, 0) + 1
        
        top = sorted(domain_counts.items(), key=lambda x: -x[1])[:15]
        print(f"\n📊 Top domains:")
        for domain, count in top:
            print(f"   {domain}: {count}")
    
    print("\nDone! 🎉")


if __name__ == "__main__":
    main()
