#!/usr/bin/env python3
"""Construction Conversations website builder.

Fetches the Podbean RSS feed and regenerates site/index.html and
site/episodes.html from the files in templates/. Design lives in the
templates and site/assets/css/style.css; this script only fills in
episode data at the {{...}} markers.

Usage:
    python3 build.py            # fetch fresh feed + rebuild
    python3 build.py --offline  # rebuild from cached feed.xml
"""

import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).parent
FEED_URL = "https://feed.podbean.com/constructionconversations/feed.xml"
FEED_CACHE = ROOT / "feed.xml"
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def fetch_feed() -> str:
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "cc-site-builder"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read().decode("utf-8")
    FEED_CACHE.write_text(data)
    return data


def text(el, tag, ns=""):
    node = el.find(ns + tag)
    return (node.text or "").strip() if node is not None and node.text else ""


def clean_desc(raw: str, limit: int = 230) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw)
    txt = html.unescape(txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    if len(txt) > limit:
        txt = txt[:limit].rsplit(" ", 1)[0] + "…"
    return txt


def fmt_duration(raw: str) -> str:
    if not raw:
        return ""
    if ":" in raw:
        parts = [int(p) for p in raw.split(":")]
        secs = 0
        for p in parts:
            secs = secs * 60 + p
    else:
        secs = int(raw)
    m = round(secs / 60)
    return f"{m} min"


def parse_episodes(xml_text: str):
    channel = ET.fromstring(xml_text).find("channel")
    episodes = []
    for item in channel.findall("item"):
        title = text(item, "title")
        enclosure = item.find("enclosure")
        pub = text(item, "pubDate")
        try:
            date = parsedate_to_datetime(pub).strftime("%b %-d, %Y")
        except Exception:
            date = ""
# Public numbering lives in the title ("Ep. 54 - ..."); Podbean's
        # itunes:episode counts specials too and drifts from it.
        m = re.match(r"Ep\.?\s*(\d+)", title)
        ep_num = m.group(1) if m else ""
        episodes.append({
            "title": title,
            "num": ep_num,
            "date": date,
            "duration": fmt_duration(text(item, "duration", ITUNES)),
            "desc": clean_desc(text(item, "description") or text(item, "summary", ITUNES)),
            "audio": enclosure.get("url") if enclosure is not None else "",
            "link": text(item, "link"),
        })
    art = channel.find(ITUNES + "image")
    artwork = art.get("href") if art is not None else ""
    return episodes, artwork


def card(ep) -> str:
    # Site Gothic: stamp tag (mono on Crane) + DM Mono metadata, Anton title
    tag = f'EP {int(ep["num"]):03d}' if ep["num"] else "SPECIAL"
    meta = " · ".join(v for v in (ep["date"], ep["duration"]) if v)
    display_title = re.sub(r"^Ep\.?\s*\d+\s*[-–—:]\s*", "", ep["title"])
    return f'''      <article class="ep-card">
        <div class="ep-meta"><span class="tag">{tag}</span><span class="stamp">{meta.upper()}</span></div>
        <h3><a href="{ep["link"]}">{html.escape(display_title)}</a></h3>
        <p class="ep-desc">{html.escape(ep["desc"])}</p>
        <div class="ep-actions">
          <button class="play-btn">▶ Play</button>
          <a href="{ep["link"]}">Show notes</a>
        </div>
        <div class="ep-player"><audio controls preload="none" data-src="{ep["audio"]}"></audio></div>
      </article>'''


def build():
    offline = "--offline" in sys.argv
    if offline and FEED_CACHE.exists():
        xml_text = FEED_CACHE.read_text()
    else:
        xml_text = fetch_feed()

    episodes, artwork = parse_episodes(xml_text)
    print(f"Parsed {len(episodes)} episodes from feed")

    if artwork:
        try:
            req = urllib.request.Request(artwork, headers={"User-Agent": "cc-site-builder"})
            (ROOT / "site/assets/img/cover-art.jpg").write_bytes(
                urllib.request.urlopen(req, timeout=30).read())
            print("Downloaded cover art")
        except Exception as e:
            print(f"Cover art skipped: {e}")

    replacements = {
        "{{EPISODE_COUNT}}": str(len(episodes)),
        "{{LATEST_EPISODES}}": "\n".join(card(e) for e in episodes[:3]),
        "{{ALL_EPISODES}}": "\n".join(card(e) for e in episodes),
    }
    for name in ("index.html", "episodes.html"):
        out = (ROOT / "templates" / name).read_text()
        for k, v in replacements.items():
            out = out.replace(k, v)
        (ROOT / "site" / name).write_text(out)
        print(f"Wrote site/{name}")

    print(f"Built {datetime.now():%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    build()
