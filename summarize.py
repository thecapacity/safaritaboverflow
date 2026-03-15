#!/usr/bin/env python3
"""
summarize.py — AI-powered summarization of Safari tab exports

Reads a Markdown file produced by safari_dump.py or bookmarks_dump.py,
fetches each URL's content, and generates a brief "dating profile" summary
using the Anthropic API.

Output: An enriched Markdown file where each link gets a 1-2 sentence summary.

Usage:
    python3 summarize.py safari-tabs-clean.md                  # summarize all links
    python3 summarize.py safari-tabs-clean.md --limit 20       # only first 20
    python3 summarize.py safari-tabs-clean.md --dry-run        # show what would be fetched

Requirements:
    pip3 install anthropic httpx
    export ANTHROPIC_API_KEY=sk-ant-...
"""

import re
import sys
import os
import time
import json
import argparse
from datetime import datetime
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    print("❌ Missing dependency. Install with: pip3 install httpx")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("❌ Missing dependency. Install with: pip3 install anthropic")
    sys.exit(1)


LINK_RE = re.compile(r'^(\s*-\s+)\[([^\]]*)\]\(([^)]+)\)(.*)')
HEADER_RE = re.compile(r'^(#{1,6})\s+(.*)')

# Domains to skip (login pages, internal URLs, etc.)
SKIP_DOMAINS = {
    "accounts.google.com", "login.microsoftonline.com", "auth0.com",
    "localhost", "127.0.0.1", "about:blank",
}

# Max content to send to Claude (characters)
MAX_CONTENT_CHARS = 15000


def should_skip_url(url: str) -> bool:
    """Check if a URL should be skipped for summarization."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in SKIP_DOMAINS:
            return True
        if not parsed.scheme.startswith("http"):
            return True
        # Skip file downloads
        path = parsed.path.lower()
        skip_extensions = {".pdf", ".zip", ".dmg", ".pkg", ".exe", ".mp4", ".mp3"}
        if any(path.endswith(ext) for ext in skip_extensions):
            return True
    except Exception:
        return True
    return False


def fetch_page_text(url: str, timeout: float = 10.0) -> str:
    """
    Fetch a URL and extract text content.
    Uses Jina AI's reader API for clean text extraction.
    Falls back to raw fetch if Jina fails.
    """
    # Try Jina Reader API first (free, gives clean text)
    jina_url = f"https://r.jina.ai/{url}"
    try:
        resp = httpx.get(
            jina_url,
            timeout=timeout,
            headers={"Accept": "text/plain"},
            follow_redirects=True,
        )
        if resp.status_code == 200 and len(resp.text) > 100:
            return resp.text[:MAX_CONTENT_CHARS]
    except Exception:
        pass
    
    # Fallback: direct fetch
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
        if resp.status_code == 200:
            text = resp.text[:MAX_CONTENT_CHARS]
            # Very basic HTML stripping
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:MAX_CONTENT_CHARS]
    except Exception:
        pass
    
    return ""


def summarize_page(client: anthropic.Anthropic, title: str, url: str, content: str) -> dict:
    """
    Use Claude to generate a brief "dating profile" for the page.
    
    Returns: {"summary": str, "tags": list[str], "action": str}
    Where action is one of: "read" | "reference" | "archive" | "skip"
    """
    domain = urlparse(url).hostname or ""
    
    prompt = f"""Analyze this web page and create a brief "card" summary. Be concise and helpful.

Page title: {title}
URL: {url}
Domain: {domain}

Page content (may be truncated):
{content[:8000]}

Respond in exactly this JSON format (no markdown, no code fences):
{{
    "summary": "1-2 sentence summary of what this page is about and why someone saved it",
    "tags": ["tag1", "tag2"],
    "action": "read|reference|archive|skip",
    "action_reason": "brief reason for the suggested action"
}}

Action guide:
- "read": This is an article/post worth actually reading (has substantial content)
- "reference": This is a tool, docs page, or resource to keep for later reference
- "archive": This seems outdated or low-value but might be worth keeping filed away
- "skip": This is a login page, error page, or not useful"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Try to parse JSON
        # Strip any markdown code fences if present
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "summary": text[:200] if text else "Could not summarize",
            "tags": [],
            "action": "read",
            "action_reason": "parse error",
        }
    except Exception as e:
        return {
            "summary": f"Error: {str(e)[:100]}",
            "tags": [],
            "action": "skip",
            "action_reason": "API error",
        }


def main():
    parser = argparse.ArgumentParser(
        description="AI-powered summarization of Safari tab/bookmark exports"
    )
    parser.add_argument(
        "file",
        help="Markdown file to process",
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file (default: adds '-summarized' suffix)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max number of links to summarize (0 = all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which URLs would be fetched without actually doing it",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between API calls in seconds (default: 1.0)",
    )
    args = parser.parse_args()
    
    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        print("❌ Set ANTHROPIC_API_KEY environment variable")
        print("   export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)
    
    # Parse input file
    print(f"📄 Reading {args.file}...")
    with open(args.file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # Find all links
    links = []
    for i, line in enumerate(lines):
        match = LINK_RE.match(line.rstrip("\n"))
        if match:
            url = match.group(3)
            if not should_skip_url(url):
                links.append({
                    "line_index": i,
                    "indent": match.group(1),
                    "title": match.group(2),
                    "url": url,
                    "suffix": match.group(4),
                })
    
    print(f"🔗 Found {len(links)} links to summarize")
    
    if args.limit > 0:
        links = links[:args.limit]
        print(f"   (limited to {args.limit})")
    
    if args.dry_run:
        print("\n🔍 Dry run — URLs that would be processed:")
        for link in links:
            print(f"   {link['url']}")
        return
    
    # Initialize Anthropic client
    client = anthropic.Anthropic(api_key=api_key)
    
    # Process each link
    summaries = {}
    for idx, link in enumerate(links):
        progress = f"[{idx + 1}/{len(links)}]"
        url = link["url"]
        domain = urlparse(url).hostname or ""
        print(f"  {progress} Fetching {domain}...", end="", flush=True)
        
        content = fetch_page_text(url)
        if not content or len(content) < 50:
            print(" (no content, skipping)")
            summaries[link["line_index"]] = {
                "summary": "Could not fetch page content",
                "tags": [],
                "action": "skip",
                "action_reason": "page not accessible",
            }
            continue
        
        print(" summarizing...", end="", flush=True)
        result = summarize_page(client, link["title"], url, content)
        summaries[link["line_index"]] = result
        
        action_emoji = {"read": "📖", "reference": "📌", "archive": "📦", "skip": "⏭️"}.get(
            result.get("action", ""), "❓"
        )
        print(f" {action_emoji} {result.get('summary', '')[:60]}...")
        
        if args.delay > 0 and idx < len(links) - 1:
            time.sleep(args.delay)
    
    # Build enriched output
    output_lines = []
    for i, line in enumerate(lines):
        output_lines.append(line.rstrip("\n"))
        
        if i in summaries:
            s = summaries[i]
            action = s.get("action", "")
            action_emoji = {"read": "📖", "reference": "📌", "archive": "📦", "skip": "⏭️"}.get(action, "")
            summary = s.get("summary", "")
            tags = s.get("tags", [])
            reason = s.get("action_reason", "")
            
            tag_str = " ".join(f"`{t}`" for t in tags) if tags else ""
            output_lines.append(f"  > {action_emoji} **{action.upper()}**: {summary}")
            if tag_str:
                output_lines.append(f"  > Tags: {tag_str}")
    
    # Write output
    if args.output:
        out_path = args.output
    else:
        base = args.file
        if base.endswith(".md"):
            out_path = base[:-3] + "-summarized.md"
        else:
            out_path = base + "-summarized.md"
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines) + "\n")
    
    print(f"\n📝 Written to {out_path}")
    
    # Print action stats
    actions = [s.get("action", "") for s in summaries.values()]
    print(f"\n📊 Summary:")
    for action in ["read", "reference", "archive", "skip"]:
        count = actions.count(action)
        if count:
            emoji = {"read": "📖", "reference": "📌", "archive": "📦", "skip": "⏭️"}[action]
            print(f"   {emoji} {action}: {count}")
    
    print("\nDone! 🎉")


if __name__ == "__main__":
    main()
