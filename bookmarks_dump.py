#!/usr/bin/env python3
"""
bookmarks_dump.py — Export Safari bookmarks and Reading List to Markdown

Parses ~/Library/Safari/Bookmarks.plist (a binary plist file) to extract:
  - All bookmark folders and their contents (preserving folder hierarchy)
  - The Reading List with dates

Usage:
    python3 bookmarks_dump.py                    # dump to auto-named file
    python3 bookmarks_dump.py -o bookmarks.md    # dump to specific file
    python3 bookmarks_dump.py --reading-list     # dump only the Reading List
    python3 bookmarks_dump.py --folders           # dump only bookmark folders

Requirements:
    - macOS (uses Python's built-in plistlib)
    - Full Disk Access may be needed for Terminal
      (System Settings → Privacy & Security → Full Disk Access)
"""

import plistlib
import os
import sys
import argparse
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path


DEFAULT_PLIST = os.path.expanduser("~/Library/Safari/Bookmarks.plist")


def load_bookmarks_plist(path: str) -> dict:
    """Load and parse the Safari Bookmarks.plist file."""
    path = os.path.expanduser(path)
    
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Bookmarks.plist not found at {path}\n"
            "Make sure you're on macOS and Safari has been used."
        )
    
    try:
        with open(path, "rb") as f:
            return plistlib.load(f)
    except PermissionError:
        raise PermissionError(
            f"Permission denied reading {path}\n"
            "Grant Full Disk Access to Terminal:\n"
            "  System Settings → Privacy & Security → Full Disk Access → add Terminal/iTerm"
        )


def extract_bookmarks(node: dict, depth: int = 0) -> list[dict]:
    """
    Recursively walk the bookmarks plist tree.
    
    Returns a flat list of items, each with:
      - type: "folder" | "bookmark" | "reading_list_item"
      - title: str
      - url: str (for bookmarks)
      - depth: int (nesting level)
      - date_added: datetime or None
      - folder_type: str or None (e.g., "BookmarksBar", "BookmarksMenu")
    """
    results = []
    
    web_bookmark_type = node.get("WebBookmarkType", "")
    title = node.get("Title", "") or node.get("URIDictionary", {}).get("title", "")
    
    if web_bookmark_type == "WebBookmarkTypeList":
        # This is a folder
        folder_title = title
        
        # Identify special folders
        special_id = node.get("WebBookmarkIdentifier", "")
        if special_id:
            # Map internal IDs to friendly names
            friendly = {
                "BookmarksBar": "Favorites",
                "BookmarksMenu": "Bookmarks Menu",
            }
            folder_title = friendly.get(special_id, folder_title or special_id)
        
        # Check if this is the Reading List
        is_reading_list = (title == "com.apple.ReadingList")
        
        if is_reading_list:
            folder_title = "Reading List"
        
        # Don't emit the root node as a folder
        if depth > 0 or is_reading_list:
            results.append({
                "type": "folder",
                "title": folder_title,
                "depth": depth,
                "is_reading_list": is_reading_list,
            })
        
        # Recurse into children
        children = node.get("Children", [])
        for child in children:
            child_depth = depth + 1 if (depth > 0 or is_reading_list or title) else depth
            results.extend(extract_bookmarks(child, child_depth))
    
    elif web_bookmark_type == "WebBookmarkTypeLeaf":
        # This is an actual bookmark
        url = node.get("URLString", "")
        uri_dict = node.get("URIDictionary", {})
        bm_title = uri_dict.get("title", title or url)
        
        # Reading List items have extra metadata
        reading_list_data = node.get("ReadingList", {})
        date_added = reading_list_data.get("DateAdded")
        preview_text = reading_list_data.get("PreviewText", "")
        
        item_type = "reading_list_item" if reading_list_data else "bookmark"
        
        results.append({
            "type": item_type,
            "title": bm_title,
            "url": url,
            "depth": depth,
            "date_added": date_added,
            "preview": preview_text[:200] if preview_text else "",
        })
    
    elif web_bookmark_type == "WebBookmarkTypeProxy":
        # These are internal Safari things (like the History proxy), skip
        pass
    
    else:
        # Unknown type, recurse into children if present
        children = node.get("Children", [])
        for child in children:
            results.extend(extract_bookmarks(child, depth))
    
    return results


def domain_from_url(url: str) -> str:
    """Extract short domain from URL."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def format_markdown(items: list[dict], include_folders=True, include_reading_list=True) -> str:
    """Format extracted bookmarks as Markdown."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Count items
    bookmark_count = sum(1 for i in items if i["type"] == "bookmark")
    rl_count = sum(1 for i in items if i["type"] == "reading_list_item")
    folder_count = sum(1 for i in items if i["type"] == "folder")
    
    lines = [
        f"# Safari Bookmarks — {now}",
        "",
        f"{bookmark_count} bookmarks in {folder_count} folders, {rl_count} reading list items",
        "",
    ]
    
    in_reading_list = False
    
    for item in items:
        if item["type"] == "folder":
            is_rl = item.get("is_reading_list", False)
            
            if is_rl and not include_reading_list:
                in_reading_list = True
                continue
            if not is_rl and not include_folders:
                in_reading_list = False
                continue
            
            in_reading_list = is_rl
            
            # Use heading depth based on nesting (cap at h4)
            heading_level = min(item["depth"] + 1, 4)
            heading = "#" * heading_level
            lines.append(f"{heading} {item['title']}")
            lines.append("")
        
        elif item["type"] == "bookmark":
            if not include_folders:
                continue
            if in_reading_list:
                continue
            
            title = item["title"] or "(untitled)"
            url = item.get("url", "")
            title = title.replace("[", "\\[").replace("]", "\\]")
            
            if url:
                domain = domain_from_url(url)
                domain_suffix = f" — {domain}" if domain else ""
                lines.append(f"- [{title}]({url}){domain_suffix}")
            else:
                lines.append(f"- {title}")
        
        elif item["type"] == "reading_list_item":
            if not include_reading_list:
                continue
            
            title = item["title"] or "(untitled)"
            url = item.get("url", "")
            title = title.replace("[", "\\[").replace("]", "\\]")
            
            date_str = ""
            if item.get("date_added"):
                try:
                    date_str = f" — *added {item['date_added'].strftime('%Y-%m-%d')}*"
                except Exception:
                    pass
            
            preview = ""
            if item.get("preview"):
                preview = f"\n  > {item['preview']}"
            
            if url:
                lines.append(f"- [{title}]({url}){date_str}{preview}")
            else:
                lines.append(f"- {title}{date_str}{preview}")
        
        # Add spacing after sections
    
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Export Safari bookmarks and Reading List to Markdown"
    )
    parser.add_argument(
        "-o", "--output",
        help="Output file path (default: auto-generated with timestamp)",
    )
    parser.add_argument(
        "--plist",
        default=DEFAULT_PLIST,
        help=f"Path to Bookmarks.plist (default: {DEFAULT_PLIST})",
    )
    parser.add_argument(
        "--reading-list",
        action="store_true",
        help="Export only the Reading List",
    )
    parser.add_argument(
        "--folders",
        action="store_true",
        help="Export only bookmark folders (exclude Reading List)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Also output JSON alongside Markdown",
    )
    args = parser.parse_args()
    
    print(f"📖 Loading bookmarks from {args.plist}...")
    
    try:
        plist_data = load_bookmarks_plist(args.plist)
    except (FileNotFoundError, PermissionError) as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    
    print("🔍 Extracting bookmarks and Reading List...")
    items = extract_bookmarks(plist_data)
    
    bookmark_count = sum(1 for i in items if i["type"] == "bookmark")
    rl_count = sum(1 for i in items if i["type"] == "reading_list_item")
    folder_count = sum(1 for i in items if i["type"] == "folder")
    print(f"✅ Found {bookmark_count} bookmarks, {rl_count} reading list items, {folder_count} folders")
    
    # Determine what to include
    include_folders = not args.reading_list
    include_reading_list = not args.folders
    
    # Generate output filename
    timestamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    if args.output:
        out_path = args.output
    elif args.reading_list:
        out_path = f"safari-reading-list-{timestamp}.md"
    else:
        out_path = f"safari-bookmarks-{timestamp}.md"
    
    md = format_markdown(items, include_folders=include_folders, include_reading_list=include_reading_list)
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"📝 Written to {out_path}")
    
    # Optionally write JSON
    if args.json:
        import json
        json_path = out_path.replace(".md", ".json")
        # Serialize datetime objects
        def default_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return str(obj)
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, default=default_serializer, ensure_ascii=False)
        print(f"📝 JSON written to {json_path}")
    
    print("Done! 🎉")


if __name__ == "__main__":
    main()
