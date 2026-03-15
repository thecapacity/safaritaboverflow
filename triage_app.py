#!/usr/bin/env python3
"""
triage_app.py — Mobile-friendly web app for triaging Safari tabs

Serves a simple "dating profile" card interface where you can swipe through
your saved links, read summaries, and tag them for action.

Usage:
    python3 triage_app.py safari-tabs-summarized.md          # serve on localhost:8080
    python3 triage_app.py safari-tabs-summarized.md -p 9090  # custom port

Then open http://YOUR_MAC_IP:8080 on your iPhone (same Wi-Fi network).

Requirements:
    No pip packages needed — uses only Python stdlib (http.server)
"""

import re
import sys
import json
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import socket


LINK_RE = re.compile(r'^(\s*-\s+)\[([^\]]*)\]\(([^)]+)\)(.*)')
HEADER_RE = re.compile(r'^(#{1,6})\s+(.*)')
SUMMARY_RE = re.compile(r'^\s*>\s*(.+)')

# Global state
CARDS = []
DECISIONS = {}  # url -> {"action": "keep"|"archive"|"delete", "tag": str}


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
            title = link_match.group(2)
            url = link_match.group(3)
            suffix = link_match.group(4).strip()
            
            # Look ahead for summary lines (blockquotes)
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
                "id": len(cards),
                "title": title,
                "url": url,
                "domain": domain,
                "section": current_section,
                "suffix": suffix,
                "summary": "\n".join(summary_lines) if summary_lines else "",
            })
            
            i = j
            continue
        
        i += 1
    
    return cards


def get_local_ip() -> str:
    """Get the local IP address for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Safari Tab Triage</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: #1a1a2e;
            color: #eee;
            min-height: 100vh;
            overflow-x: hidden;
        }
        .header {
            padding: 16px 20px;
            background: #16213e;
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 { font-size: 18px; font-weight: 600; }
        .counter { font-size: 14px; color: #888; }
        
        .card-container {
            display: flex;
            justify-content: center;
            padding: 20px;
            min-height: calc(100vh - 200px);
            align-items: flex-start;
        }
        .card {
            background: #16213e;
            border-radius: 16px;
            padding: 24px;
            max-width: 420px;
            width: 100%;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            transition: transform 0.3s ease, opacity 0.3s ease;
        }
        .card.swiped-left { transform: translateX(-150%) rotate(-10deg); opacity: 0; }
        .card.swiped-right { transform: translateX(150%) rotate(10deg); opacity: 0; }
        .card.swiped-up { transform: translateY(-150%); opacity: 0; }
        
        .card-domain {
            font-size: 12px;
            color: #0a84ff;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .card-section {
            font-size: 11px;
            color: #666;
            margin-bottom: 12px;
        }
        .card-title {
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 12px;
            line-height: 1.3;
        }
        .card-title a {
            color: #fff;
            text-decoration: none;
        }
        .card-title a:hover { text-decoration: underline; }
        .card-summary {
            font-size: 14px;
            color: #bbb;
            line-height: 1.6;
            margin-bottom: 16px;
        }
        .card-url {
            font-size: 12px;
            color: #555;
            word-break: break-all;
            margin-bottom: 20px;
        }
        
        .actions {
            display: flex;
            gap: 12px;
            justify-content: center;
            padding: 0 20px 20px;
        }
        .action-btn {
            flex: 1;
            padding: 14px;
            border: none;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            transition: transform 0.1s;
        }
        .action-btn:active { transform: scale(0.95); }
        .action-btn .emoji { font-size: 24px; }
        
        .btn-archive { background: #2d1f00; color: #ffa500; }
        .btn-keep { background: #002d0a; color: #30d158; }
        .btn-read { background: #00162d; color: #0a84ff; }
        .btn-delete { background: #2d0000; color: #ff453a; }
        
        .tag-input {
            display: flex;
            gap: 8px;
            padding: 8px 20px;
            flex-wrap: wrap;
            justify-content: center;
        }
        .tag-chip {
            padding: 6px 14px;
            border-radius: 20px;
            background: #222;
            color: #aaa;
            font-size: 13px;
            border: 1px solid #333;
            cursor: pointer;
            transition: all 0.2s;
        }
        .tag-chip:hover, .tag-chip.active {
            background: #0a84ff;
            color: #fff;
            border-color: #0a84ff;
        }
        
        .done {
            text-align: center;
            padding: 60px 20px;
        }
        .done h2 { font-size: 24px; margin-bottom: 16px; }
        .done p { color: #888; margin-bottom: 20px; }
        .done button {
            padding: 12px 24px;
            background: #0a84ff;
            color: #fff;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            cursor: pointer;
        }
        
        .stats {
            display: flex;
            justify-content: center;
            gap: 20px;
            padding: 8px;
            font-size: 12px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🗂️ Tab Triage</h1>
        <span class="counter" id="counter"></span>
    </div>
    
    <div class="stats" id="stats"></div>
    
    <div class="card-container" id="card-container"></div>
    
    <div class="tag-input" id="tag-input">
        <span class="tag-chip" data-tag="Shopping">🛍 Shopping</span>
        <span class="tag-chip" data-tag="Research">🔬 Research</span>
        <span class="tag-chip" data-tag="Read Later">📖 Read Later</span>
        <span class="tag-chip" data-tag="Project">🔧 Project</span>
    </div>
    
    <div class="actions" id="actions">
        <button class="action-btn btn-delete" onclick="decide('delete')">
            <span class="emoji">🗑️</span>
            Skip
        </button>
        <button class="action-btn btn-archive" onclick="decide('archive')">
            <span class="emoji">📦</span>
            Archive
        </button>
        <button class="action-btn btn-read" onclick="decide('read')">
            <span class="emoji">📖</span>
            Read
        </button>
        <button class="action-btn btn-keep" onclick="decide('keep')">
            <span class="emoji">✅</span>
            Keep
        </button>
    </div>
    
    <script>
    let cards = [];
    let current = 0;
    let decisions = {};
    let selectedTag = "";
    
    async function loadCards() {
        const resp = await fetch('/api/cards');
        cards = await resp.json();
        decisions = {};
        current = 0;
        renderCard();
    }
    
    function renderCard() {
        const container = document.getElementById('card-container');
        const counter = document.getElementById('counter');
        const stats = document.getElementById('stats');
        
        // Stats
        const kept = Object.values(decisions).filter(d => d.action === 'keep').length;
        const archived = Object.values(decisions).filter(d => d.action === 'archive').length;
        const deleted = Object.values(decisions).filter(d => d.action === 'delete').length;
        const toRead = Object.values(decisions).filter(d => d.action === 'read').length;
        stats.innerHTML = `✅ ${kept} · 📦 ${archived} · 📖 ${toRead} · 🗑️ ${deleted}`;
        
        if (current >= cards.length) {
            counter.textContent = 'All done!';
            container.innerHTML = `
                <div class="done">
                    <h2>🎉 All caught up!</h2>
                    <p>${cards.length} links triaged</p>
                    <button onclick="exportResults()">📥 Export Results</button>
                </div>
            `;
            document.getElementById('actions').style.display = 'none';
            document.getElementById('tag-input').style.display = 'none';
            return;
        }
        
        const card = cards[current];
        counter.textContent = `${current + 1} / ${cards.length}`;
        
        let summaryHTML = '';
        if (card.summary) {
            // Clean up the summary (remove emoji prefixes from the summarizer)
            let summary = card.summary
                .replace(/^[📖📌📦⏭️]\s*\*\*\w+\*\*:\s*/gm, '')
                .replace(/^Tags:\s*.*$/gm, '')
                .trim();
            summaryHTML = `<div class="card-summary">${summary}</div>`;
        }
        
        container.innerHTML = `
            <div class="card" id="current-card">
                <div class="card-domain">${card.domain}</div>
                <div class="card-section">from: ${card.section}</div>
                <div class="card-title"><a href="${card.url}" target="_blank">${card.title}</a></div>
                ${summaryHTML}
                <div class="card-url">${card.url}</div>
            </div>
        `;
    }
    
    async function decide(action) {
        if (current >= cards.length) return;
        
        const card = cards[current];
        decisions[card.url] = { action, tag: selectedTag, id: card.id };
        
        // Animate card
        const el = document.getElementById('current-card');
        if (el) {
            const cls = {
                'delete': 'swiped-left',
                'archive': 'swiped-up',
                'keep': 'swiped-right',
                'read': 'swiped-right'
            }[action] || 'swiped-right';
            el.classList.add(cls);
        }
        
        // Save to server
        await fetch('/api/decide', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ url: card.url, action, tag: selectedTag })
        });
        
        setTimeout(() => {
            current++;
            renderCard();
        }, 300);
    }
    
    // Tag selection
    document.querySelectorAll('.tag-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            const tag = chip.dataset.tag;
            if (selectedTag === tag) {
                selectedTag = "";
                chip.classList.remove('active');
            } else {
                document.querySelectorAll('.tag-chip').forEach(c => c.classList.remove('active'));
                selectedTag = tag;
                chip.classList.add('active');
            }
        });
    });
    
    async function exportResults() {
        const resp = await fetch('/api/export');
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'triage-results.md';
        a.click();
    }
    
    // Keyboard shortcuts
    document.addEventListener('keydown', e => {
        if (e.key === 'ArrowLeft' || e.key === 'd') decide('delete');
        if (e.key === 'ArrowRight' || e.key === 'k') decide('keep');
        if (e.key === 'ArrowUp' || e.key === 'a') decide('archive');
        if (e.key === 'ArrowDown' || e.key === 'r') decide('read');
    });
    
    loadCards();
    </script>
</body>
</html>"""


class TriageHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        """Suppress default request logging."""
        pass
    
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode())
        
        elif self.path == "/api/cards":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(CARDS).encode())
        
        elif self.path == "/api/export":
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown")
            self.send_header("Content-Disposition", "attachment; filename=triage-results.md")
            self.end_headers()
            md = export_decisions()
            self.wfile.write(md.encode())
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        if self.path == "/api/decide":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            DECISIONS[body["url"]] = {
                "action": body["action"],
                "tag": body.get("tag", ""),
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        else:
            self.send_response(404)
            self.end_headers()


def export_decisions() -> str:
    """Export triage decisions as organized Markdown."""
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    sections = {"keep": [], "read": [], "archive": [], "delete": []}
    
    for card in CARDS:
        decision = DECISIONS.get(card["url"])
        if decision:
            action = decision["action"]
            tag = decision.get("tag", "")
            entry = {"card": card, "tag": tag}
            if action in sections:
                sections[action].append(entry)
    
    lines = [f"# Tab Triage Results — {now}", ""]
    
    for action, emoji, label in [
        ("keep", "✅", "Keep"),
        ("read", "📖", "Read Later"),
        ("archive", "📦", "Archive"),
        ("delete", "🗑️", "Skip/Delete"),
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


def main():
    parser = argparse.ArgumentParser(
        description="Mobile-friendly web app for triaging Safari tabs"
    )
    parser.add_argument("file", help="Markdown file with links (ideally summarized)")
    parser.add_argument("-p", "--port", type=int, default=8080, help="Port (default: 8080)")
    args = parser.parse_args()
    
    global CARDS
    print(f"📄 Loading {args.file}...")
    CARDS = parse_summarized_markdown(args.file)
    print(f"🃏 Loaded {len(CARDS)} cards")
    
    if not CARDS:
        print("⚠️  No links found in the file.")
        sys.exit(1)
    
    local_ip = get_local_ip()
    
    server = HTTPServer(("0.0.0.0", args.port), TriageHandler)
    print(f"\n🚀 Triage app running!")
    print(f"   Local:   http://localhost:{args.port}")
    print(f"   Network: http://{local_ip}:{args.port}  ← open this on your iPhone")
    print(f"\n   Keyboard shortcuts: ←/d=delete  →/k=keep  ↑/a=archive  ↓/r=read")
    print(f"   Press Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        if DECISIONS:
            out_path = args.file.replace(".md", "-triage.md")
            md = export_decisions()
            with open(out_path, "w") as f:
                f.write(md)
            print(f"📝 Saved {len(DECISIONS)} decisions to {out_path}")
        server.server_close()


if __name__ == "__main__":
    main()
