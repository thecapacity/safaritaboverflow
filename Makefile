# SafariTabOverflow Makefile
# Run these commands from the project directory on your Mac

.PHONY: help fast dump bookmarks clean summarize triage all

# Set PROFILE on the command line: make fast PROFILE=Work
PROFILE ?=

help:
	@echo "SafariTabOverflow — manage your Safari tab overload"
	@echo ""
	@echo "  make fast                    — Quick dump of all open Safari tabs"
	@echo "  make fast PROFILE=Work       — Dump + tag as 'Work' profile"
	@echo "  make fast-meta PROFILE=Work  — Dump + page descriptions from DOM"
	@echo "  make dump PROFILE=Work       — Dump + close tabs (with confirmation)"
	@echo "  make dump KEEP=gmail.com     — Dump + close, but keep Gmail tabs"
	@echo "  make append PROFILE=Personal — Append another profile to latest dump"
	@echo "  make bookmarks               — Export bookmarks and Reading List"
	@echo "  make clean                   — Deduplicate the latest export"
	@echo "  make clean-flat              — Deduplicate + regroup by domain"
	@echo "  make summarize               — AI summaries (needs ANTHROPIC_API_KEY)"
	@echo "  make all                     — Full pipeline: dump + bookmarks + clean"
	@echo ""
	@echo "  Options:  PROFILE=<n>  KEEP=gmail.com,slack.com  EXCLUDE=notion.so"

# Get the latest generated files
LATEST_TABS := $(shell ls -t safari-tabs-*.md 2>/dev/null | head -1)
LATEST_CLEAN := $(shell ls -t *-clean.md 2>/dev/null | head -1)
LATEST_SUMMARIZED := $(shell ls -t *-summarized.md 2>/dev/null | head -1)
LATEST_ANY := $(shell ls -t safari-*.md 2>/dev/null | head -1)

# Build profile flag if PROFILE is set
ifdef PROFILE
  PROFILE_FLAG := --profile "$(PROFILE)"
else
  PROFILE_FLAG :=
endif

# Optional flags: KEEP=gmail.com, EXCLUDE=notion.so (comma-separated)
KEEP ?=
EXCLUDE ?=

# Helpers for comma-separated parsing
comma := ,
space := $(subst ,, )

ifdef KEEP
  KEEP_FLAGS := $(foreach d,$(subst $(comma),$(space),$(KEEP)),--keep $(d))
else
  KEEP_FLAGS :=
endif

ifdef EXCLUDE
  EXCLUDE_FLAGS := $(foreach d,$(subst $(comma),$(space),$(EXCLUDE)),--exclude $(d))
else
  EXCLUDE_FLAGS :=
endif

fast:
	python3 safari_dump.py $(PROFILE_FLAG) $(EXCLUDE_FLAGS)

fast-meta:
	python3 safari_dump.py $(PROFILE_FLAG) $(EXCLUDE_FLAGS) --meta

dump:
	python3 safari_dump.py $(PROFILE_FLAG) $(EXCLUDE_FLAGS) $(KEEP_FLAGS) --close

dump-meta:
	python3 safari_dump.py $(PROFILE_FLAG) $(EXCLUDE_FLAGS) $(KEEP_FLAGS) --meta --close

append:
ifndef PROFILE
	@echo "❌ Usage: make append PROFILE=<name>"
	@echo "   Appends to the latest dump file with the given profile tag."
	@exit 1
endif
	@if [ -z "$(LATEST_TABS)" ]; then \
		echo "❌ No existing dump to append to. Run 'make fast PROFILE=...' first."; \
		exit 1; \
	fi
	python3 safari_dump.py --profile "$(PROFILE)" --append "$(LATEST_TABS)"

bookmarks:
	python3 bookmarks_dump.py

clean:
	@if [ -z "$(LATEST_TABS)" ]; then \
		echo "No tab export found. Run 'make fast' first."; \
		exit 1; \
	fi
	python3 cleanup.py $(LATEST_TABS) --sort

clean-flat:
	@if [ -z "$(LATEST_TABS)" ]; then \
		echo "No tab export found. Run 'make fast' first."; \
		exit 1; \
	fi
	python3 cleanup.py $(LATEST_TABS) --flat

summarize:
	@if [ -z "$(LATEST_CLEAN)" ]; then \
		if [ -z "$(LATEST_TABS)" ]; then \
			echo "No export found. Run 'make fast' first."; \
			exit 1; \
		fi; \
		python3 summarize.py $(LATEST_TABS); \
	else \
		python3 summarize.py $(LATEST_CLEAN); \
	fi

all: fast bookmarks
	python3 cleanup.py safari-tabs-*.md safari-bookmarks-*.md --sort -o safari-all-clean.md
	@echo ""
	@echo "💡 Multi-profile workflow:"
	@echo "   make fast PROFILE=Work"
	@echo "   make append PROFILE=Personal"
	@echo "   make append PROFILE=Shopping"
	@echo "   make clean"
