#!/usr/bin/env python3
"""
triage_app.py — Mobile-friendly web app for triaging Safari tabs

Serves a swipe-style "link dating" card interface for triaging saved links.
Decisions are cached to a JSON file on exit and reloaded on subsequent runs.
The source .md file is never modified.

Usage:
    python3 triage_app.py safari-tabs-summarized.md          # serve on localhost:8080
    python3 triage_app.py safari-tabs-summarized.md -p 9090  # custom port

Then open http://YOUR_MAC_IP:8080 on your iPhone (same Wi-Fi network).

Cache: stored as <input>.cache.json alongside the input file.

Requirements:
    No pip packages needed — uses only Python stdlib (http.server)
"""

import re
import sys
import ssl
import json
import socket
import argparse
import subprocess
import tempfile
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse


LINK_RE    = re.compile(r'^(\s*-\s+)\[([^\]]*)\]\(([^)]+)\)(.*)')
HEADER_RE  = re.compile(r'^(#{1,6})\s+(.*)')
SUMMARY_RE = re.compile(r'^\s*>\s*(.+)')

# Global state — populated in main()
CARDS      = []
DECISIONS  = {}   # url -> {"action": "keep"|"archive"|"read"|"delete", "tag": str}
CACHE_FILE = None
HTML_FILE  = Path(__file__).with_name("triage_app.html")


# ─── Parsing ────────────────────────────────────────────────────────────────────

def parse_summarized_markdown(filepath: str) -> list[dict]:
    """Parse a summarized markdown file into card data."""
    cards = []
    current_section = "Unsorted"

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")

        header_match = HEADER_RE.match(line)
        if header_match:
            current_section = header_match.group(2)
            i += 1
            continue

        link_match = LINK_RE.match(line)
        if link_match:
            title  = link_match.group(2)
            url    = link_match.group(3)
            suffix = link_match.group(4).strip()

            summary_lines = []
            j = i + 1
            while j < len(lines):
                s_match = SUMMARY_RE.match(lines[j].rstrip("\n"))
                if s_match:
                    summary_lines.append(s_match.group(1))
                    j += 1
                else:
                    break

            domain = ""
            try:
                parsed = urlparse(url)
                domain = parsed.hostname or ""
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                pass

            cards.append({
                "id":      len(cards),
                "title":   title,
                "url":     url,
                "domain":  domain,
                "section": current_section,
                "suffix":  suffix,
                "summary": "\n".join(summary_lines) if summary_lines else "",
            })
            i = j
            continue

        i += 1

    return cards


# ─── Cache ──────────────────────────────────────────────────────────────────────

def cache_path_for(md_path: str) -> Path:
    return Path(md_path).with_suffix(".cache.json")


def load_cache(path: Path) -> dict:
    """Load decisions from cache file. Returns {} if not found."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Could not read cache {path}: {e}")
        return {}


def save_cache(path: Path, decisions: dict) -> None:
    """Write decisions to cache file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(decisions, f, indent=2)


# ─── Export ─────────────────────────────────────────────────────────────────────

def export_decisions() -> str:
    """Export triage decisions as organized Markdown."""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sections = {"keep": [], "read": [], "archive": [], "delete": []}

    for card in CARDS:
        decision = DECISIONS.get(card["url"])
        if decision:
            action = decision["action"]
            if action in sections:
                sections[action].append({"card": card, "tag": decision.get("tag", "")})

    lines = [f"# Tab Triage Results — {now}", ""]

    for action, emoji, label in [
        ("keep",    "✅", "Keep"),
        ("read",    "📖", "Read Later"),
        ("archive", "📦", "Archive"),
        ("delete",  "🗑️", "Delete"),
    ]:
        items = sections[action]
        if not items:
            continue
        lines.append(f"## {emoji} {label} ({len(items)})")
        lines.append("")
        for entry in items:
            c = entry["card"]
            tag_str = f" `{entry['tag']}`" if entry["tag"] else ""
            lines.append(f"- [{c['title']}]({c['url']}) — {c['domain']}{tag_str}")
        lines.append("")

    return "\n".join(lines) + "\n"


# ─── HTTP Handler ────────────────────────────────────────────────────────────────

class TriageHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress request logging

    def do_GET(self):
        if self.path == "/":
            try:
                html = HTML_FILE.read_bytes()
            except FileNotFoundError:
                self.send_error(500, f"Template not found: {HTML_FILE}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)

        elif self.path == "/api/cards":
            # Attach any cached decision to each card before sending
            cards_out = []
            for card in CARDS:
                c = dict(card)
                c["decision"] = DECISIONS.get(card["url"])
                cards_out.append(c)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(cards_out).encode())

        elif self.path == "/api/export":
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown")
            self.send_header("Content-Disposition", "attachment; filename=triage-results.md")
            self.end_headers()
            self.wfile.write(export_decisions().encode())

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/decide":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            DECISIONS[body["url"]] = {
                "action": body["action"],
                "tag":    body.get("tag", ""),
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        else:
            self.send_response(404)
            self.end_headers()


# ─── Networking ──────────────────────────────────────────────────────────────────

def make_ssl_context() -> tuple:
    """Generate a temporary self-signed cert and return (SSLContext, tmp_dir).
    Caller must keep tmp_dir alive for the server's lifetime."""
    tmp = tempfile.mkdtemp()
    cert = f"{tmp}/cert.pem"
    key  = f"{tmp}/key.pem"
    subprocess.run([
        "openssl", "req", "-x509",
        "-newkey", "rsa:2048",
        "-keyout", key,
        "-out", cert,
        "-days", "1",
        "-nodes",
        "-subj", "/CN=localhost",
    ], check=True, capture_output=True)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    return ctx, tmp


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


# ─── Main ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Mobile-friendly web app for triaging Safari tabs"
    )
    parser.add_argument("file", help="Markdown file with links (source — never modified)")
    parser.add_argument("-p", "--port", type=int, default=8080, help="Port (default: 8080)")
    args = parser.parse_args()

    global CARDS, DECISIONS, CACHE_FILE

    print(f"📄 Loading {args.file}...")
    CARDS = parse_summarized_markdown(args.file)
    if not CARDS:
        print("⚠️  No links found in the file.")
        sys.exit(1)
    print(f"🃏 Loaded {len(CARDS)} cards")

    CACHE_FILE = cache_path_for(args.file)
    DECISIONS  = load_cache(CACHE_FILE)
    if DECISIONS:
        decided = len(DECISIONS)
        remaining = sum(1 for c in CARDS if c["url"] not in DECISIONS)
        print(f"💾 Cache loaded: {decided} prior decisions, {remaining} remaining")

    local_ip = get_local_ip()
    ssl_ctx, _tmp = make_ssl_context()
    server = HTTPServer(("0.0.0.0", args.port), TriageHandler)
    server.socket = ssl_ctx.wrap_socket(server.socket, server_side=True)

    print(f"\n🚀 Triage app running (HTTPS)!")
    print(f"   Local:   https://localhost:{args.port}")
    print(f"   Network: https://{local_ip}:{args.port}  ← open this on your iPhone")
    print(f"   ⚠️  You'll need to accept the self-signed cert warning in your browser")
    print(f"\n   Keyboard shortcuts: ←/d=delete  →/k=keep  ↑/a=archive  ↓/r=read")
    print(f"   Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        if DECISIONS:
            save_cache(CACHE_FILE, DECISIONS)
            print(f"💾 Saved {len(DECISIONS)} decisions to {CACHE_FILE}")
        server.server_close()


if __name__ == "__main__":
    main()
