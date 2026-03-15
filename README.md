# safaritaboverflow
Written by AI - Inspired by https://github.com/swyxio/chrometaboverflow

# SafariTabOverflow

A macOS toolkit for managing Safari tab overload — inspired by [chrometaboverflow](https://github.com/swyxio/chrometaboverflow), adapted for Safari's unique architecture.

## The Problem

You have hundreds of tabs across Safari profiles and tab groups. Some are research gems, some are "I'll read this later" articles from 6 months ago, and some are duplicates you opened three times. You need a way to extract, organize, and triage them.

## What This Does

`Note: Apple still hasn't added AppleScript support for Safari profiles (there's a 109-upvote feedback request from 2023). So we can't programmatically enumerate which window belongs to which profile. But we can get all open tabs via AppleScript, read bookmarks/reading list from Bookmarks.plist, and the workaround for profiles is to either run the dump with one profile's windows visible, or tag windows manually after export.`

### Phase 1: Ingest
- **`safari_dump.py`** — Extracts all open Safari tabs (grouped by window) via AppleScript, exports to Markdown
  - `--profile NAME` — Tag all windows with a profile name (run once per Safari profile)
  - `--append FILE` — Merge into an existing dump (multi-profile workflow)
  - `--meta` — Extract page descriptions, author, date, og:image from the loaded DOM (free, no re-fetching)
  - `--close` — Close captured tabs after saving (with confirmation)
  - `--keep DOMAIN` — With `--close`: protect tabs on these domains (e.g., `--keep gmail.com`)
  - `--exclude DOMAIN` — Skip tabs on these domains entirely (e.g., `--exclude notion.so`)
- **`bookmarks_dump.py`** — Parses `~/Library/Safari/Bookmarks.plist` to extract bookmarks by folder, plus your Reading List
- Both scripts output clean Markdown files with `[title](url)` links

### Phase 2: Cleanup
- **`cleanup.py`** — Deduplicates URLs, optionally sorts by domain within groups, and produces a cleaned Markdown file

### Phase 3: Augment (future / separate scripts)
- **`summarize.py`** — AI-powered page summaries using the Anthropic API
- **`triage_app.py`** — A lightweight Flask app for mobile "swipe to keep/archive" triage (future)

## Quick Start

```bash
# No dependencies needed for Phase 1 & 2 — uses only Python stdlib + osascript

# 1. Dump all open Safari tabs (switch to a profile first, then tag it)
python3 safari_dump.py --profile Work
python3 safari_dump.py --profile Personal --append safari-tabs-Work-*.md

# 1b. With page descriptions (reads from already-loaded DOM, no extra fetching)
python3 safari_dump.py --profile Work --meta

# 1c. Dump and close tabs, but keep Gmail and Slack open
python3 safari_dump.py --profile Work --close --keep gmail.com --keep slack.com

# 2. Dump bookmarks and Reading List
python3 bookmarks_dump.py

# 3. Clean up (dedup + sort) any of the generated files
python3 cleanup.py safari-tabs-*.md

# 4. (Optional) AI-powered summaries — requires ANTHROPIC_API_KEY
pip3 install anthropic httpx
python3 summarize.py safari-tabs-*.md
```

## Safari Profiles: The `--profile` Workflow

Safari profiles (introduced in macOS Sonoma) don't have AppleScript support — this is a [known gap with 100+ upvotes](https://github.com/feedback-assistant/reports/issues/399) on Apple's feedback tracker.

The workaround: **switch to a profile in Safari, then run the script with `--profile NAME`**. All captured windows get tagged with that profile. Use `--append` to build up a single multi-profile file:

```bash
# Step 1: Switch to your Work profile in Safari, then:
python3 safari_dump.py --profile Work

# Step 2: Switch to your Personal profile in Safari, then:
python3 safari_dump.py --profile Personal --append safari-tabs-Work-*.md

# Step 3: (optional) Switch to another profile...
python3 safari_dump.py --profile Shopping --append safari-tabs-Work-*.md

# Or dump + close tabs for each profile as you go:
python3 safari_dump.py --profile Work --close
python3 safari_dump.py --profile Personal --close --append safari-tabs-Work-*.md
```

The resulting file will have a merged header with stats across all profiles:

```markdown
# Safari Tabs — 2026-02-07 14:30:00

142 tabs across 8 windows · profiles: Work, Personal, Shopping

## Work — Window 1 (12 tabs)
<!-- profile: Work -->
...

## Personal — Window 1 (8 tabs)
<!-- profile: Personal -->
...
```

Tab Groups *within* a profile similarly aren't exposed to AppleScript, but the bookmarks dump captures bookmark folders, which are the persistent equivalent.

## File Locations (for reference)

| Data | Location |
|------|----------|
| Bookmarks & Reading List | `~/Library/Safari/Bookmarks.plist` |
| History | `~/Library/Safari/History.db` (SQLite) |
| Last Session | `~/Library/Safari/LastSession.plist` |
| Profile data | Per-profile directories under Safari's container |

## Permissions

Your terminal app needs Automation permission for Safari:
- **System Settings → Privacy & Security → Automation** → allow Terminal (or iTerm) to control Safari

For `--meta` (page metadata extraction):
- **Safari → Develop menu → Allow JavaScript from Apple Events**
- (If you don't see the Develop menu: Safari → Settings → Advanced → Show features for web developers)

For bookmarks, you may also need:
- **System Settings → Privacy & Security → Full Disk Access** → allow Terminal/Python

## Output Format

### Tab Dump (`safari-tabs-TIMESTAMP.md`)
```markdown
# Safari Tabs [Work] — 2026-02-07 14:30:00

142 tabs across 8 windows

## Work — Window 1 (12 tabs)
<!-- profile: Work -->

- [How to Build a Rocket](https://example.com/rocket) — example.com
- [Python Docs](https://docs.python.org/3/) — docs.python.org

## Work — Window 2 (8 tabs)
...
```

### With `--meta` (page metadata extracted from loaded DOM)
```markdown
- [Why Rust Is the Future](https://blog.example.com/rust-future) — blog.example.com
  > A deep dive into Rust's ownership model and why it matters for systems programming · By Jane Smith · Mar 15, 2026
  > ![](https://blog.example.com/images/rust-og.png)
- [Tailwind CSS Docs](https://tailwindcss.com/docs) — tailwindcss.com
  > Rapidly build modern websites without ever leaving your HTML.
```

The `--meta` flag uses Safari's `do JavaScript` to read the page's `<meta>` tags
directly from the DOM — no network requests. Requires enabling:
**Safari → Develop menu → Allow JavaScript from Apple Events**

### Bookmarks Dump (`safari-bookmarks-TIMESTAMP.md`)
```markdown
# Safari Bookmarks — 2026-02-07 14:32:00

## Favorites
- [Apple](https://www.apple.com)

## Shopping
- [Amazon](https://www.amazon.com)

## Reading List
- [Great Article](https://example.com/article) — *added 2025-12-01*
```

## Requirements

- macOS (Sonoma or later recommended, works on older versions too)
- Python 3.9+ (ships with macOS)
- Safari running (for tab dump)
- No pip packages needed for core functionality
