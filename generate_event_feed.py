#!/usr/bin/env python3
"""
This is Visalia — Event Feed Generator (free X posting pipeline)
====================================================================
Fetches the Beehiiv RSS feed (whole newsletter issues), splits each issue
into individual events, and writes out a NEW RSS feed file (events_feed.xml)
containing one <item> per event instead of one per issue.

This generated feed is what gets hosted (e.g. via GitHub Pages) and watched
by a free tool like IFTTT, which posts each new item to X automatically.

Duplicate prevention is built in two ways:
  1. Each event gets a stable <guid> based on issue link + event text, so
     the same event is never assigned a new ID across runs.
  2. IFTTT's own "new feed item" trigger only fires on GUIDs it hasn't seen
     before, so even if this script re-runs and regenerates the whole feed,
     already-seen events won't be re-posted.

Usage:
    python3 generate_event_feed.py
    -> writes events_feed.xml in the current directory
"""

import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime

import feedparser
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

SOURCE_FEED_URL = "https://rss.beehiiv.com/feeds/O11OkDDEKj.xml"
OUTPUT_FILE = "events_feed.xml"

# Feed metadata for the generated XML — edit to match your branding.
FEED_TITLE = "This is Visalia — Individual Events"
FEED_LINK = "https://this-is-visalia.beehiiv.com/"
FEED_DESCRIPTION = "Auto-generated feed: one item per event, exploded from the This is Visalia newsletter."

SKIP_SECTION_HEADERS = [
    "header", "opener", "from the community", "sponsor", "footer",
    "subscribe", "follow",
    "coming up next friday",  # preview-only teaser, not a full event post
]

MIN_ITEM_LENGTH = 8


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def make_event_guid(issue_link, event_title):
    raw = f"{issue_link}::{event_title}".lower().strip()
    return re.sub(r"[^a-z0-9:]+", "-", raw)


def xml_escape(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# FETCH + EXTRACT (same logic as the direct-post script)
# ---------------------------------------------------------------------------

def fetch_feed():
    feed = feedparser.parse(SOURCE_FEED_URL)
    if feed.bozo and not feed.entries:
        print(f"ERROR: could not parse feed at {SOURCE_FEED_URL}", file=sys.stderr)
        sys.exit(1)
    return feed


def extract_events_from_issue(entry):
    # Try summary first (usually HTML), then content
    html = entry.get("summary", "") or entry.get("content", [{}])[0].get("value", "")
    
    # If we still don't have content, try description
    if not html:
        html = entry.get("description", "")
    
    soup = BeautifulSoup(html, "html.parser")
    issue_link = entry.get("link", "")
    issue_title = entry.get("title", "")
    pub_date = entry.get("published", "") or entry.get("updated", "")

    events = []
    current_section = ""

    print(f"[DEBUG] Entry title: {issue_title}", file=sys.stderr)
    print(f"[DEBUG] HTML content length: {len(html)}", file=sys.stderr)

    # Try parsing HTML elements first
    found_elements = soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "strong"])
    
    if found_elements:
        print(f"[DEBUG] Found {len(found_elements)} HTML elements", file=sys.stderr)
        for el in found_elements:
            text = el.get_text(strip=True)
            if not text:
                continue

            if el.name in ("h1", "h2", "h3", "h4"):
                current_section = text.lower()
                continue

            if any(skip in current_section for skip in SKIP_SECTION_HEADERS):
                continue

            if el.name in ("li", "strong", "p") and len(text) > MIN_ITEM_LENGTH:
                events.append({
                    "title": text[:120],
                    "detail": text,
                    "section": current_section,
                    "issue_title": issue_title,
                    "issue_link": issue_link,
                    "pub_date": pub_date,
                })
    else:
        # Fallback: if no HTML elements found, treat the entire content as text
        # and split by newlines or sentences
        print(f"[DEBUG] No HTML elements found, treating as plain text", file=sys.stderr)
        text_content = soup.get_text()
        
        if text_content and len(text_content) > MIN_ITEM_LENGTH:
            # Split by newlines and filter empty lines
            lines = [line.strip() for line in text_content.split('\n') if line.strip() and len(line.strip()) > MIN_ITEM_LENGTH]
            
            print(f"[DEBUG] Found {len(lines)} text lines", file=sys.stderr)
            
            for line in lines:
                # Skip metadata-like lines (dates, issue numbers)
                if any(skip in line.lower() for skip in SKIP_SECTION_HEADERS):
                    continue
                
                events.append({
                    "title": line[:120],
                    "detail": line,
                    "section": "",
                    "issue_title": issue_title,
                    "issue_link": issue_link,
                    "pub_date": pub_date,
                })

    print(f"[DEBUG] Extracted {len(events)} events from this entry", file=sys.stderr)
    return events


# ---------------------------------------------------------------------------
# RSS GENERATION
# ---------------------------------------------------------------------------

def build_rss(all_events):
    now = format_datetime(datetime.now(timezone.utc))

    items_xml = []
    for event in all_events:
        guid = make_event_guid(event["issue_link"], event["title"])
        title = xml_escape(event["title"])
        link = xml_escape(event["issue_link"])
        description = xml_escape(event["detail"])
        pub_date = event["pub_date"] or now

        items_xml.append(f"""    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid isPermaLink="false">{guid}</guid>
      <description>{description}</description>
      <pubDate>{pub_date}</pubDate>
    </item>""")

    items_block = "\n".join(items_xml)

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{xml_escape(FEED_TITLE)}</title>
    <link>{xml_escape(FEED_LINK)}</link>
    <description>{xml_escape(FEED_DESCRIPTION)}</description>
    <lastBuildDate>{now}</lastBuildDate>
{items_block}
  </channel>
</rss>
"""
    return rss


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    feed = fetch_feed()
    print(f"[DEBUG] Feed has {len(feed.entries)} entries", file=sys.stderr)

    all_events = []
    for entry in feed.entries:
        all_events.extend(extract_events_from_issue(entry))

    if not all_events:
        print("No events extracted — check feed/parsing logic.", file=sys.stderr)
        sys.exit(1)

    rss_xml = build_rss(all_events)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(rss_xml)

    print(f"Wrote {len(all_events)} event item(s) to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
