#!/usr/bin/env python3
"""Construction Conversations website builder.

Fetches the Podbean RSS feed and regenerates the site from templates/:
  site/index.html      - homepage (latest 3 episodes injected)
  site/episodes.html   - full episode list with search
  site/sponsors.html   - sponsor page (static content, count injected)
  site/episodes/*.html - one page per episode, with PodcastEpisode JSON-LD
  site/start.html      - Start Here hub (listening paths from paths.json)
  site/start/*.html    - one page per listening path

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

import extras

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
            "secs": secs,
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


def card(ep, base: str = "", why: str = "", step: int = 0) -> str:
    """Episode card. `base` prefixes links for pages in subfolders ("../").
    `why`/`step` render the Start Here path variant (numbered, curator note
    in place of the feed description)."""
    # Site Gothic: stamp tag (mono on Crane) + DM Mono metadata, Anton title
    tag = f'EP {int(ep["num"]):03d}' if ep["num"] else "SPECIAL"
    meta = " · ".join(v for v in (ep["date"], ep["duration"]) if v)
    step_html = f'<span class="step">{step:02d}</span>' if step else ""
    desc = why or ep["desc"]
    cls = "ep-card path-card" if why else "ep-card"
    return f'''      <article class="{cls}">
        <div class="ep-meta">{step_html}<span class="tag">{tag}</span><span class="stamp">{meta.upper()}</span></div>
        <h3><a href="{base}episodes/{ep["slug"]}.html">{html.escape(ep["display_title"])}</a></h3>
        <p class="ep-desc">{html.escape(desc)}</p>
        <div class="ep-actions">
          <button class="play-btn">▶ Play</button>
          <a href="{base}episodes/{ep["slug"]}.html">Show notes</a>
        </div>
        <div class="ep-player"><audio controls preload="none" data-src="{ep["audio"]}"></audio></div>
      </article>'''


# ---------------------------------------------------------------------------
# Start Here listening paths (paths.json)

def load_paths(episodes):
    """Read paths.json and resolve episode slugs. Unknown slugs are dropped
    with a warning so a typo never breaks the build."""
    by_slug = {e["slug"]: e for e in episodes}
    data = json.loads((ROOT / "paths.json").read_text())

    def resolve(items, where):
        out = []
        for it in items:
            ep = by_slug.get(it["slug"])
            if not ep:
                print(f"WARNING paths.json [{where}]: unknown episode {it['slug']}, skipped")
                continue
            out.append({"ep": ep, "why": it.get("why", "")})
        return out

    first = data.get("first_three", {})
    first["items"] = resolve(first.get("episodes", []), "first_three")
    paths = []
    for p in data.get("paths", []):
        p["items"] = resolve(p.get("episodes", []), p["slug"])
        secs = sum(it["ep"]["secs"] for it in p["items"])
        hrs = secs / 3600
        p["time"] = f"about {hrs:.0f} hours" if hrs >= 1.5 else f"about {round(secs/60)} minutes"
        paths.append(p)
    return first, paths


def path_door(p, base: str = "") -> str:
    n = len(p["items"])
    return f'''      <a class="door path-door" href="{base}start/{p["slug"]}.html" data-event="Path: {html.escape(p["tag"])}">
        <span class="tag">{html.escape(p["tag"])}</span>
        <h3>{html.escape(p["title"])}</h3>
        <p>{html.escape(p["blurb"])}</p>
        <span class="door-link">{n} episodes · {html.escape(p["time"])} →</span>
      </a>'''


def path_jsonld(p) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": f'{p["title"]} | Construction Conversations',
        "description": p["blurb"],
        "itemListOrder": "https://schema.org/ItemListOrderAscending",
        "numberOfItems": len(p["items"]),
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1,
             "name": it["ep"]["title"],
             "url": f'https://constructionconversations.com/episodes/{it["ep"]["slug"]}.html'}
            for i, it in enumerate(p["items"])
        ],
    }
    return json.dumps(data, indent=2)


def build_paths(first, paths, count: int):
    """Write site/start.html and site/start/<slug>.html."""
    start_dir = ROOT / "site" / "start"
    start_dir.mkdir(exist_ok=True)

    hub = (ROOT / "templates" / "start.html").read_text()
    for k, v in {
        "{{EPISODE_COUNT}}": str(count),
        "{{FIRST_THREE_TITLE}}": html.escape(first.get("title", "If you only listen to three")),
        "{{FIRST_THREE_BLURB}}": html.escape(first.get("blurb", "")),
        "{{FIRST_THREE}}": "\n".join(card(it["ep"], why=it["why"], step=i + 1)
                                     for i, it in enumerate(first["items"])),
        "{{PATH_CARDS}}": "\n".join(path_door(p) for p in paths),
    }.items():
        hub = hub.replace(k, v)
    (ROOT / "site" / "start.html").write_text(extras.apply_chrome(extras.apply_newsletter(hub, ""), ""))
    print("Wrote site/start.html")

    tpl = (ROOT / "templates" / "path.html").read_text()
    for i, p in enumerate(paths):
        nxt = [paths[(i + 1) % len(paths)], paths[(i + 2) % len(paths)]] if len(paths) > 2 else []
        page = tpl
        for k, v in {
            "{{PATH_TITLE}}": html.escape(p["title"]),
            "{{PATH_TAG}}": html.escape(p["tag"]),
            "{{PATH_WHO}}": html.escape(p["who"]),
            "{{PATH_BLURB}}": html.escape(p["blurb"]),
            "{{PATH_COUNT}}": str(len(p["items"])),
            "{{PATH_TIME}}": html.escape(p["time"]),
            "{{PATH_EPISODES}}": "\n".join(card(it["ep"], base="../", why=it["why"], step=j + 1)
                                           for j, it in enumerate(p["items"])),
            "{{NEXT_PATHS}}": "\n".join(path_door(n, base="../") for n in nxt),
            "{{JSONLD}}": path_jsonld(p),
        }.items():
            page = page.replace(k, v)
        (start_dir / f'{p["slug"]}.html').write_text(extras.apply_chrome(extras.apply_newsletter(page, "../"), "../"))
    print(f"Wrote {len(paths)} path pages to site/start/")


def episode_paths_block(ep, paths) -> str:
    """'Part of these paths' links for an episode page (empty if none)."""
    hits = [p for p in paths if any(it["ep"]["slug"] == ep["slug"] for it in p["items"])]
    if not hits:
        return ""
    links = "".join(
        f'<a class="path-pill" href="../start/{p["slug"]}.html" data-event="Path: {html.escape(p["tag"])}">'
        f'{html.escape(p["title"])} →</a>' for p in hits)
    return f'''<div class="sec-label" style="margin-top:40px;">Part of these listening paths</div>
  <div class="path-pills">{links}</div>'''


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

    first, paths = load_paths(episodes)
    extras.set_episode_index(episodes)
    chapters = extras.load_chapters()
    articles = extras.load_articles()
    tools = extras.load_tools()

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
        out = extras.apply_chrome(extras.apply_newsletter(out, ""), "")
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
            "{{PATHS}}": episode_paths_block(ep, paths),
            "{{GUEST_LINE}}": (f'<p class="stamp guest-line">{gl}</p>' if (gl := extras.guest_line(chapters.get(ep["slug"]))) else ""),
            "{{CHAPTERS}}": extras.chapters_block(chapters.get(ep["slug"])),
            "{{QUOTES}}": extras.quotes_block(chapters.get(ep["slug"])),
            "{{MENTIONS}}": extras.mentions_block(chapters.get(ep["slug"])),
            "{{ARTICLES}}": extras.episode_articles_block(ep["slug"], articles),
            "{{TOOLS}}": extras.episode_tools_block(ep["slug"], tools),
        }.items():
            page = page.replace(k, v)
        (ep_dir / f'{ep["slug"]}.html').write_text(extras.apply_chrome(page, "../"))
    print(f"Wrote {len(episodes)} episode pages to site/episodes/")

    build_paths(first, paths, len(episodes))
    tpl_dir = ROOT / "templates"
    extras.build_articles(articles, episodes, tpl_dir)
    extras.build_tools(tools, tpl_dir)
    extras.build_lessons(extras.load_lessons(), tpl_dir)
    extras.build_reviews(extras.load_reviews(offline), tpl_dir)
    extras.build_join(extras.load_upcoming(), extras.load_stories(), tpl_dir)

    print(f"Built {datetime.now():%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    build()
