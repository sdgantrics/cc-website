#!/usr/bin/env python3
"""Construction Conversations website builder.

Fetches the Podbean RSS feed and regenerates the site from templates/:
  site/index.html      - homepage (latest 3 episodes injected)
  site/episodes.html   - full episode list with search
  site/sponsors.html   - sponsor page (static content, count injected)
  site/episodes/*.html - one page per episode, with PodcastEpisode JSON-LD

Design lives in the templates and site/assets/css/style.css; this script
only fills in episode data at the {{...}} markers.

Usage:
    python3 build.py            # fetch fresh feed + rebuild
    python3 build.py --offline  # rebuild from cached feed.xml
"""

import html
import json
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
# YouTube uploads feed for @ConstructionConversations; episode thumbnails
# live on YouTube (the Podbean feed has no per-episode art).
YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UC2NzKKnmKxtvlFRO6c3R1Aw"


def fetch_feed() -> str:
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "cc-site-builder"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read().decode("utf-8")
    FEED_CACHE.write_text(data)
    return data


def text(el, tag, ns=""):
    node = el.find(ns + tag)
    return (node.text or "").strip() if node is not None and node.text else ""


def strip_html(raw: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw)
    txt = html.unescape(txt)
    # Site copy rule: no em-dashes anywhere. Feed text is normalized too.
    txt = txt.replace(" — ", ", ").replace("—", ", ")
    return re.sub(r"\s+", " ", txt).strip()


def clip_chars(txt: str, limit: int) -> str:
    if len(txt) > limit:
        txt = txt[:limit].rsplit(" ", 1)[0] + "…"
    return txt


def clip_words(txt: str, limit: int = 150) -> str:
    words = txt.split()
    if len(words) > limit:
        return " ".join(words[:limit]) + "…"
    return txt


def parse_duration(raw: str) -> int:
    """Return duration in whole seconds."""
    if not raw:
        return 0
    if ":" in raw:
        secs = 0
        for p in raw.split(":"):
            secs = secs * 60 + int(p)
        return secs
    return int(raw)


def parse_episodes(xml_text: str):
    channel = ET.fromstring(xml_text).find("channel")
    episodes = []
    specials = 0
    for item in channel.findall("item"):
        title = text(item, "title")
        enclosure = item.find("enclosure")
        pub = text(item, "pubDate")
        try:
            dt = parsedate_to_datetime(pub)
            date, date_iso = dt.strftime("%b %-d, %Y"), dt.strftime("%Y-%m-%d")
        except Exception:
            date, date_iso = "", ""
        # Public numbering lives in the title ("Ep. 54 - ..."); Podbean's
        # itunes:episode counts specials too and drifts from it.
        m = re.match(r"Ep\.?\s*(\d+)", title)
        ep_num = m.group(1) if m else ""
        if not ep_num:
            specials += 1
        secs = parse_duration(text(item, "duration", ITUNES))
        desc = strip_html(text(item, "description") or text(item, "summary", ITUNES))
        item_img = item.find(ITUNES + "image")
        episodes.append({
            "title": title,
            "display_title": re.sub(r"^Ep\.?\s*\d+\s*[-–—:]\s*", "", title),
            "num": ep_num,
            "slug": f"ep-{int(ep_num):03d}" if ep_num else f"special-{specials}",
            "date": date,
            "date_iso": date_iso,
            "duration": f"{round(secs / 60)} min" if secs else "",
            "duration_iso": f"PT{round(secs / 60)}M" if secs else "",
            "desc": clip_chars(desc, 230),
            "desc_full": clip_words(desc, 150),
            "audio": enclosure.get("url") if enclosure is not None else "",
            "link": text(item, "link"),
            "image": item_img.get("href") if item_img is not None else "",
        })
    art = channel.find(ITUNES + "image")
    artwork = art.get("href") if art is not None else ""
    return episodes, artwork


def card(ep) -> str:
    # Site Gothic: stamp tag (mono on Crane) + DM Mono metadata, Anton title
    tag = f'EP {int(ep["num"]):03d}' if ep["num"] else "SPECIAL"
    meta = " · ".join(v for v in (ep["date"], ep["duration"]) if v)
    return f'''      <article class="ep-card">
        <div class="ep-meta"><span class="tag">{tag}</span><span class="stamp">{meta.upper()}</span></div>
        <h3><a href="episodes/{ep["slug"]}.html">{html.escape(ep["display_title"])}</a></h3>
        <p class="ep-desc">{html.escape(ep["desc"])}</p>
        <div class="ep-actions">
          <button class="play-btn">▶ Play</button>
          <a href="episodes/{ep["slug"]}.html">Show notes</a>
        </div>
        <div class="ep-player"><audio controls preload="none" data-src="{ep["audio"]}"></audio></div>
      </article>'''


def youtube_thumb_url(ep) -> str:
    """Find the episode's YouTube thumbnail by matching video titles.

    Prefers an exact "Ep. NN" prefix match, then falls back to word overlap.
    Returns "" when nothing matches (caller falls back to Podbean art).
    """
    try:
        req = urllib.request.Request(YT_FEED, headers={"User-Agent": "cc-site-builder"})
        root = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        print(f"YouTube feed skipped: {e}")
        return ""
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    videos = [(v.find("a:title", ns).text or "", v.find("yt:videoId", ns).text)
              for v in root.findall("a:entry", ns)]

    vid = ""
    if ep["num"]:
        pat = re.compile(rf"^Ep\.?\s*0*{int(ep['num'])}\b", re.I)
        vid = next((v for t, v in videos if pat.match(t)), "")
    if not vid:
        words = {w for w in re.findall(r"[a-z']+", ep["title"].lower()) if len(w) > 3}
        best, best_score = "", 0.0
        for t, v in videos:
            vw = {w for w in re.findall(r"[a-z']+", t.lower()) if len(w) > 3}
            score = len(words & vw) / max(len(words), 1)
            if score > best_score:
                best, best_score = v, score
        if best_score >= 0.5:
            vid = best
    return f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg" if vid else ""


def jsonld(ep) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "PodcastEpisode",
        "name": ep["title"],
        "datePublished": ep["date_iso"],
        "description": ep["desc_full"],
        "url": ep["link"],
        "associatedMedia": {"@type": "MediaObject", "contentUrl": ep["audio"]},
        "partOfSeries": {
            "@type": "PodcastSeries",
            "name": "Construction Conversations",
            "url": "https://constructionconversations.com/",
        },
    }
    if ep["num"]:
        data["episodeNumber"] = int(ep["num"])
    if ep["duration_iso"]:
        data["timeRequired"] = ep["duration_iso"]
    return json.dumps(data, indent=2)


def build():
    offline = "--offline" in sys.argv
    if offline and FEED_CACHE.exists():
        xml_text = FEED_CACHE.read_text()
    else:
        xml_text = fetch_feed()

    episodes, artwork = parse_episodes(xml_text)
    print(f"Parsed {len(episodes)} episodes from feed")

    def download(url, dest):
        req = urllib.request.Request(url, headers={"User-Agent": "cc-site-builder"})
        (ROOT / dest).write_bytes(urllib.request.urlopen(req, timeout=30).read())

    if artwork:
        try:
            download(artwork, "site/assets/img/cover-art.jpg")
        except Exception as e:
            print(f"Cover art skipped: {e}")

    # Hero card thumbnail: the episode's YouTube thumbnail, falling back to
    # Podbean episode art, then the show cover. Refreshed every rebuild so
    # the card tracks the newest episode.
    latest = episodes[0]
    yt = youtube_thumb_url(latest)
    for src in (yt, yt.replace("maxresdefault", "hqdefault") if yt else "",
                latest["image"], artwork):
        if not src:
            continue
        try:
            download(src, "site/assets/img/latest-episode.jpg")
            print(f"Latest thumbnail: {src[:70]}")
            break
        except Exception:
            continue

    latest_tag = f'EP {int(latest["num"]):03d}' if latest["num"] else "SPECIAL"
    latest_meta = " · ".join(v for v in (latest["date"], latest["duration"]) if v).upper()
    replacements = {
        "{{EPISODE_COUNT}}": str(len(episodes)),
        "{{LATEST_EPISODES}}": "\n".join(card(e) for e in episodes[:3]),
        "{{ALL_EPISODES}}": "\n".join(card(e) for e in episodes),
        "{{LATEST_TITLE}}": html.escape(latest["display_title"]),
        "{{LATEST_META}}": f"{latest_tag} · {latest_meta}",
        "{{LATEST_AUDIO}}": latest["audio"],
        "{{LATEST_SLUG}}": latest["slug"],
    }
    for name in ("index.html", "episodes.html", "sponsors.html"):
        out = (ROOT / "templates" / name).read_text()
        for k, v in replacements.items():
            out = out.replace(k, v)
        (ROOT / "site" / name).write_text(out)
        print(f"Wrote site/{name}")

    # Per-episode pages
    ep_dir = ROOT / "site" / "episodes"
    ep_dir.mkdir(exist_ok=True)
    ep_template = (ROOT / "templates" / "episode.html").read_text()
    for ep in episodes:
        tag = f'EP {int(ep["num"]):03d}' if ep["num"] else "SPECIAL"
        meta = " · ".join(v for v in (ep["date"], ep["duration"]) if v).upper()
        page = ep_template
        for k, v in {
            "{{TITLE}}": html.escape(ep["display_title"]),
            "{{TAG}}": tag,
            "{{META}}": meta,
            "{{DESC_SHORT}}": html.escape(ep["desc"]),
            "{{DESC_FULL}}": html.escape(ep["desc_full"]),
            "{{AUDIO}}": ep["audio"],
            "{{LINK}}": ep["link"],
            "{{JSONLD}}": jsonld(ep),
        }.items():
            page = page.replace(k, v)
        (ep_dir / f'{ep["slug"]}.html').write_text(page)
    print(f"Wrote {len(episodes)} episode pages to site/episodes/")

    print(f"Built {datetime.now():%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    build()
