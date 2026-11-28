"""Audience-site renderers for build.py (Phases 1.5, 2, 3).

Data in:
  data/chapters/<slug>.json  timestamped chapters, guest, mentions, quotes
  articles/<slug>.md         front matter + HTML body (Recaps, Insider Takes, Debriefs, Essays)
  data/tools.json            tools mentioned on the show, from the Episode Insights DB
  data/lessons.json          the 50 most expensive lessons (newsletter hook)
  data/reviews.json          Apple Podcasts reviews cache (refreshed online)
  data/upcoming.json         next guests for the Ask form
  stories/<slug>.md          listener-submitted field stories (moderated)
  data/translator.json       placeholder lines for the jobsite translator

Pages out:
  site/articles.html, site/articles/<slug>.html
  site/tools.html, site/assets/tools.csv
  site/lessons.html
  site/reviews.html
  site/join.html, site/stories.html
  site/translator.html       standalone, noindex, not in the nav
Plus per-episode blocks injected into episode pages.
"""

import csv
import html
import io
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
SITE = ROOT / "site"
SUBSTACK = "https://constructionbriefs.substack.com"
APPLE_ID = "1746691812"
APPLE_REVIEWS = f"https://itunes.apple.com/us/rss/customerreviews/id={APPLE_ID}/sortBy=mostRecent/json"
APPLE_RATE = f"https://podcasts.apple.com/us/podcast/construction-conversations/id{APPLE_ID}?see-all=reviews"


def nodash(s: str) -> str:
    return (s or "").replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").replace("–", ", ")


def esc(s: str) -> str:
    return html.escape(nodash(s or ""))


# ---------------------------------------------------------------------------
# Single-sourced nav + footer (applied to every generated page)

NAV_ITEMS = [
    ("start.html", "Start Here"),
    ("episodes.html", "Episodes"),
    ("articles.html", "Articles"),
    ("tools.html", "Tools"),
    ("join.html", "Join In"),
]
NAV_CTA = ("lessons.html", "The 50 Lessons")

# (group label, links). Each link is (href, text, plausible event or "").
FOOT_ITEMS = [
    ("Listen", [
        ("https://podcasts.apple.com/us/podcast/construction-conversations/id1746691812", "Apple", "Platform: Apple"),
        ("https://open.spotify.com/show/3TPc3EDgxGvmJoRwmffVL3", "Spotify", "Platform: Spotify"),
        ("https://www.youtube.com/@ConstructionConversations", "YouTube", "Platform: YouTube"),
    ]),
    ("Follow", [
        ("https://www.linkedin.com/company/construction-conversations/", "LinkedIn", ""),
        ("https://www.instagram.com/construction_conversations/", "Instagram", "Platform: Instagram"),
        (f"{SUBSTACK}/", "Briefs", ""),
    ]),
    ("Explore", [
        ("episodes.html?q=reviewed%20as%20noted", "Reviewed as Noted", ""),
        ("reviews.html", "Reviews", ""),
    ]),
    ("Work with us", [
        ("join.html#guest", "Be a Guest", ""),
        ("sponsors.html", "Tell your story", "Sponsor Link: Footer"),
    ]),
]


def nav_html(base: str) -> str:
    items = "".join(f'\n      <li><a href="{base}{h}">{t}</a></li>' for h, t in NAV_ITEMS)
    cta = f'\n      <li><a class="nav-cta" href="{base}{NAV_CTA[0]}" data-event="Nav: Lessons">{NAV_CTA[1]}</a></li>'
    return f'<ul class="nav-links">{items}{cta}\n    </ul>'


def nav_search_link(base: str) -> str:
    """Icon link. Pagefind is not loaded here; the search page loads it on use."""
    return (
        f'<a class="nav-search" href="{base}search.html" aria-label="Search the archive" data-event="Nav: Search">'
        '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">'
        '<circle cx="10.5" cy="10.5" r="6.25" fill="none" stroke="currentColor" stroke-width="2"></circle>'
        '<path d="M15.2 15.2 L20 20" fill="none" stroke="currentColor" stroke-width="2"></path>'
        '</svg></a>'
    )


def foot_html(base: str) -> str:
    groups = []
    for label, items in FOOT_ITEMS:
        links = []
        for h, t, ev in items:
            href = h if h.startswith("http") else base + h
            ext = ' target="_blank" rel="noopener"' if h.startswith("http") else ""
            evt = f' data-event="{ev}"' if ev else ""
            links.append(f'        <a href="{href}"{evt}{ext}>{t}</a>')
        groups.append(
            '      <div class="foot-group">\n'
            f'        <span class="foot-label">{label}</span>\n'
            + "\n".join(links) + "\n"
            "      </div>"
        )
    return '<div class="foot-links">\n' + "\n".join(groups) + "\n    </div>"


NAV_RE = re.compile(r'<ul class="nav-links">.*?</ul>', re.S)
# The menu button and the link list, so the search icon can sit with them.
NAV_CLUSTER_RE = re.compile(
    r'<button class="nav-toggle"[^>]*>.*?</button>\s*<ul class="nav-links">.*?</ul>',
    re.S,
)
# Templates (and rebuilt pages) nest group divs inside .foot-links, so stop at
# the </div> that closes the list, the one sitting just before the copyright.
FOOT_RE = re.compile(r'<div class="foot-links">.*?</div>(?=\s*<small>)', re.S)


def apply_chrome(page: str, base: str) -> str:
    def cluster(m):
        raw = m.group(0)
        button = re.match(r'<button class="nav-toggle".*?</button>', raw, re.S).group(0)
        # Links, then the search icon, then the menu button. On small screens
        # the list is taken out of flow, so the icon stays beside the button.
        return '<div class="nav-cluster">' + nav_html(base) + nav_search_link(base) + button + '</div>'

    if 'class="nav-search"' in page:
        page = NAV_RE.sub(lambda m: nav_html(base), page, count=1)
    else:
        page = NAV_CLUSTER_RE.sub(cluster, page, count=1)
    page = FOOT_RE.sub(lambda m: foot_html(base), page, count=1)
    return page


# ---------------------------------------------------------------------------
# Newsletter hook (Phase 1.5): the form promises a deliverable, not a subscription

def newsletter_block(base: str = "", compact: bool = False) -> str:
    head = "" if compact else '<h2 class="display">Get the 50 most expensive lessons</h2>'
    return f'''<div class="newsletter-inner">
      {head}
      <p class="lede">The Expensive Lessons Field Deck: 50 cards with what it cost, the exact quote from the person who paid it, and the move to make next time. Print-ready for toolbox talks, in Superintendent, PM, and Exec editions. Free, delivered by the Construction Briefs welcome email, and a new lesson lands with each episode.</p>
      <form class="nl-form" action="{SUBSTACK}/subscribe" method="get" data-event="Newsletter Submit">
        <input type="email" name="email" required placeholder="you@company.com" aria-label="Email address">
        <button type="submit" class="btn btn-primary">Send me the 50 lessons</button>
      </form>
      <p class="stamp dim"><a href="{base}lessons.html" style="color:var(--grey-2);">Or read them on the site →</a></p>
    </div>'''


NL_RE = re.compile(r'<div class="newsletter-inner">.*?</form>\s*</div>', re.S)


def apply_newsletter(page: str, base: str) -> str:
    return NL_RE.sub(lambda m: newsletter_block(base), page)


# ---------------------------------------------------------------------------
# Chapters (Phase 1.5)

def load_chapters():
    out = {}
    for f in sorted((ROOT / "data" / "chapters").glob("*.json")):
        try:
            d = json.loads(f.read_text())
            out[d["slug"]] = d
        except Exception as e:
            print(f"WARNING chapters {f.name}: {e}")
    return out


def t2s(t: str) -> int:
    s = 0
    for p in t.split(":"):
        s = s * 60 + int(p)
    return s


def clock(secs: int) -> str:
    """00:00 under an hour, H:MM:SS at an hour and beyond. Round-trips through t2s."""
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def clock_words(secs: int) -> str:
    secs = max(0, int(secs))
    if secs == 0:
        return "the start"
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append("1 hour" if h == 1 else f"{h} hours")
    if m:
        parts.append("1 minute" if m == 1 else f"{m} minutes")
    if s or not parts:
        parts.append("1 second" if s == 1 else f"{s} seconds")
    return " ".join(parts)


def feed_chapter_doc(doc) -> dict:
    """Shape feed chapters like a hand-written chapters file, for chapters_block."""
    chs = (doc or {}).get("chapters") or []
    if not chs:
        return {}
    return {"chapters": [{"time": clock(c["start_sec"]), "title": c.get("title") or ""} for c in chs]}


def chapters_block(ch) -> str:
    if not ch or not ch.get("chapters"):
        return ""
    rows = []
    used = set()
    for c in ch["chapters"]:
        try:
            sec = t2s(c["time"])
        except (TypeError, ValueError):
            continue
        while sec in used:
            sec += 1
        used.add(sec)
        title = esc(c.get("title") or "")
        # id + data-pagefind-title makes this list item its own sub-result.
        # Weight 10 (the max) puts the chapter title above transcript prose.
        rows.append(
            f'<li id="ch-{sec}" data-pagefind-title="{title}" data-pagefind-weight="10">'
            f'<a class="chapter" href="#t={sec}" data-t="{sec}" data-event="Chapter Seek">'
            f'<span class="stamp" data-pagefind-ignore>{esc(c["time"])}</span><span>{title}</span></a></li>'
        )
    return f'''<div class="sec-label" style="margin-top:40px;">In this episode</div>
  <ol class="chapters">{"".join(rows)}</ol>
  <p class="stamp dim">Timestamps are from the recording and may drift a minute or two from the published edit.</p>'''


def chapter_title_at(ch, sec: int) -> str:
    best_t, best = -1, ""
    for c in (ch or {}).get("chapters") or []:
        try:
            t = t2s(c["time"])
        except (TypeError, ValueError):
            continue
        if t <= sec and t >= best_t:
            best_t, best = t, c.get("title") or ""
    return best


def transcript_block(paragraphs, ch, cues=None) -> str:
    """Collapsed transcript. Paragraphs are already in the HTML; JS only seeks and opens.

    Caption cues are indexed separately (visually hidden) so a search hit can
    seek to that caption, not the start of a 20-45s paragraph.
    """
    if not paragraphs:
        return ""
    chapters = []
    for c in (ch or {}).get("chapters") or []:
        try:
            chapters.append((t2s(c["time"]), c.get("title") or ""))
        except (TypeError, ValueError, KeyError):
            continue
    chapters.sort(key=lambda x: x[0])

    def chapter_at(start: int):
        idx = -1
        for i, (t, _name) in enumerate(chapters):
            if t <= start:
                idx = i
            else:
                break
        return idx

    groups = []
    for p in paragraphs:
        idx = chapter_at(int(p["start_sec"]))
        if not groups or groups[-1][0] != idx:
            title = chapters[idx][1] if idx >= 0 else ""
            groups.append((idx, title, []))
        groups[-1][2].append(p)

    cue_list = sorted(
        (c for c in (cues or []) if (c.get("text") or "").strip()),
        key=lambda c: int(c["start_sec"]),
    )
    flat = [p for _i, _t, paras in groups for p in paras]
    body = []
    cue_at = 0
    flat_i = 0
    cue_ids = set()
    para_ids = set()
    for _idx, title, paras in groups:
        # The chapter list item is the searchable chapter title. Ignore this
        # visible heading so it is not indexed a second time.
        if title:
            body.append(f'<h2 class="tx-ch" data-pagefind-ignore>{esc(title)}</h2>')
        ch_title = esc(title or "Transcript")
        for p in paras:
            start = int(p["start_sec"])
            end = int(p["end_sec"])
            anchor = start
            while anchor in para_ids:
                anchor += 1
            para_ids.add(anchor)
            nxt = flat[flat_i + 1]["start_sec"] if flat_i + 1 < len(flat) else 10**9
            flat_i += 1
            mine = []
            while cue_at < len(cue_list) and int(cue_list[cue_at]["start_sec"]) < int(nxt):
                c = cue_list[cue_at]
                cue_at += 1
                sec = int(c["start_sec"])
                while sec in cue_ids:
                    sec += 1
                cue_ids.add(sec)
                mine.append(
                    f'<span class="tx-cue" aria-hidden="true" id="c-{sec}" '
                    f'data-pagefind-title="{ch_title}" data-pagefind-weight="0.3">'
                    f'{esc(c["text"])}</span>'
                )
            words = clock_words(start)
            # Visible text is one paragraph. Pagefind reads the caption cues
            # instead, so a hit seeks to that caption.
            body.append(
                f'<p class="tx-p" id="t-{anchor}" data-start="{start}" data-end="{end}">'
                f'<a class="tx-time stamp" href="#t={start}" data-t="{start}" data-event="Transcript Seek" '
                f'data-pagefind-ignore aria-label="Seek to {esc(words)}">{esc(clock(start))}</a>'
                f'<span class="tx-text" data-pagefind-ignore>{esc(p["text"])}</span>'
                f'{"".join(mine)}'
                f'<button type="button" class="tx-copy" data-t="{anchor}" data-event="Moment Link Copied" '
                f'data-pagefind-ignore aria-label="Copy link to this moment, {esc(words)}">Copy link to this moment</button>'
                f'</p>'
            )
    inner = "\n".join(body)
    return (
        '<details class="transcript" id="transcript">\n'
        '  <summary data-event="Transcript Open">'
        '<span class="when-closed">Show full transcript</span>'
        '<span class="when-open">Hide transcript</span></summary>\n'
        '  <p class="stamp dim tx-note">Machine-generated transcript; may contain errors.</p>\n'
        f'{inner}\n'
        '</details>'
    )


def quotes_block(ch) -> str:
    if not ch or not ch.get("quotes"):
        return ""
    parts = []
    used = set()
    for x in ch["quotes"]:
        sec = None
        if x.get("time"):
            try:
                sec = t2s(x["time"])
            except (TypeError, ValueError):
                sec = None
        attrs = ""
        if sec is not None:
            while sec in used:
                sec += 1
            used.add(sec)
            ch_title = esc(chapter_title_at(ch, sec) or "Quote")
            attrs = f' id="q-{sec}" data-pagefind-title="{ch_title}" data-pagefind-weight="4"'
        link = ""
        if sec is not None and x.get("time"):
            link = (
                f' · <a class="chapter" href="#t={t2s(x["time"])}" data-t="{t2s(x["time"])}" '
                f'data-event="Chapter Seek" data-pagefind-ignore>{esc(x["time"])}</a>'
            )
        parts.append(
            f'<blockquote class="ep-quote"{attrs}><p>"{esc(x["text"])}"</p>'
            f'<cite>{esc(x.get("who", ""))}{link}</cite></blockquote>'
        )
    # The hand-written quote clock is not always the transcript cue. Keep the
    # quotes on the page, but let the transcript paragraph be the searchable moment.
    return (
        '<div data-pagefind-ignore>'
        '<div class="sec-label" style="margin-top:40px;">Worth writing down</div>'
        + "".join(parts) + '</div>'
    )


def mentions_block(ch) -> str:
    if not ch or not ch.get("mentions"):
        return ""
    pills = "".join(f'<span class="pill">{esc(m["name"])}</span>' for m in ch["mentions"])
    return f'<div class="sec-label" style="margin-top:40px;">Mentioned</div><div class="pills">{pills}</div>'


def guest_line(ch) -> str:
    g = (ch or {}).get("guest") or {}
    if not g.get("name"):
        return ""
    bits = [g["name"]] + [v for v in (g.get("title"), g.get("firm")) if v]
    return esc(" · ".join(bits))


def guest_name(ch) -> str:
    return ((ch or {}).get("guest") or {}).get("name") or ""


# slug -> [path title, ...]. Set from build.py before lessons are rendered.
_PATHS_BY_SLUG = {}


def set_path_index(paths):
    _PATHS_BY_SLUG.clear()
    for p in paths or []:
        title = p.get("title") or ""
        if not title:
            continue
        for it in p.get("items") or []:
            slug = (it.get("ep") or {}).get("slug")
            if not slug:
                continue
            bucket = _PATHS_BY_SLUG.setdefault(slug, [])
            if title not in bucket:
                bucket.append(title)


def paths_for(slug: str):
    return list(_PATHS_BY_SLUG.get(slug) or [])


def pf_clean(s: str) -> str:
    """Attribute-safe field. `%%` is the sub-result title delimiter."""
    return esc(s or "").replace("%", "")


def pf_record(label, guest="", slug="", year="", roles=None, paths=None, seconds="") -> str:
    """Pack display fields into data-pagefind-title.

    Pagefind metadata is one value per page, so a lesson card's guest and
    roles travel on the sub-result title. The search UI splits on ` %% `.
    The title string is not indexed as body text.
    """
    role_s = ",".join(pf_clean(r) for r in (roles or []))
    path_s = ";".join(pf_clean(p) for p in (paths or []))
    parts = [
        pf_clean(label),
        pf_clean(guest),
        pf_clean(slug),
        pf_clean(str(year or "")),
        role_s,
        path_s,
        pf_clean(str(seconds if seconds != "" else "")),
    ]
    return " %% ".join(parts)


def episode_search_head(ep, hand, roles, path_titles) -> str:
    """Pagefind meta and filters for one episode page. Not visible."""
    kind = "Episode" if ep.get("num") else "Roundtable"
    bits = [
        f'<meta data-pagefind-meta="kind:{kind}">',
        f'<meta data-pagefind-filter="type:{kind}">',
    ]
    iso = ep.get("date_iso") or ""
    if len(iso) >= 4 and iso[:4].isdigit():
        bits.append(f'<meta data-pagefind-filter="year:{iso[:4]}">')
    if ep.get("date"):
        bits.append(f'<meta data-pagefind-meta="date:{esc(ep["date"])}">')
    name = guest_name(hand)
    if name:
        bits.append(f'<meta data-pagefind-filter="guest:{esc(name)}">')
    for r in roles or []:
        bits.append(f'<meta data-pagefind-filter="role:{esc(r)}">')
    for title in path_titles or []:
        bits.append(f'<meta data-pagefind-filter="path:{esc(title)}">')
    return "\n".join(bits)


# ---------------------------------------------------------------------------
# Articles (Phase 2)

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_md(path: Path):
    raw = path.read_text()
    m = FM_RE.match(raw)
    meta, body = {}, raw
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = raw[m.end():]
    meta["slug"] = path.stem
    meta["body"] = nodash(body.strip())
    meta["episodes"] = [e.strip() for e in meta.get("episode", "").split(",") if e.strip()]
    return meta


def load_articles():
    arts = [parse_md(f) for f in (ROOT / "articles").glob("*.md")]
    arts.sort(key=lambda a: a.get("date", ""), reverse=True)
    return arts


def fmt_date(iso: str) -> str:
    try:
        from datetime import date
        y, mo, d = (int(x) for x in iso.split("-"))
        return date(y, mo, d).strftime("%b %-d, %Y")
    except Exception:
        return iso


def article_card(a, base: str = "") -> str:
    ep = a["episodes"][0] if a["episodes"] else ""
    ep_tag = f'<span class="stamp">From {esc(ep_label(ep)).replace("EP 0", "Ep ").replace("EP ", "Ep ")}</span>' if ep else ""
    sub = f'<p class="ep-desc">{esc(a.get("subtitle", ""))}</p>' if a.get("subtitle") else ""
    return f'''      <article class="ep-card art-card" data-type="{esc(a.get("type", ""))}">
        <div class="ep-meta"><span class="tag">{esc(a.get("type", "Article"))}</span><span class="stamp">{esc(fmt_date(a.get("date", "")).upper())}</span>{ep_tag}</div>
        <h3><a href="{base}articles/{a["slug"]}.html">{esc(a["title"])}</a></h3>
        {sub}
        <div class="ep-actions"><a href="{base}articles/{a["slug"]}.html">Read →</a><span class="stamp">By {esc(a.get("author", ""))}</span></div>
      </article>'''


_EP_INDEX = {}


def set_episode_index(episodes):
    _EP_INDEX.clear()
    for e in episodes:
        _EP_INDEX[e["slug"]] = e


def ep_label(slug: str) -> str:
    e = _EP_INDEX.get(slug)
    if not e:
        return slug
    if e["num"]:
        return f'EP {int(e["num"]):03d}'
    try:
        from datetime import date
        y, mo, _ = (int(x) for x in e["date_iso"].split("-"))
        return f'RAN {date(y, mo, 1).strftime("%b %Y")}'
    except Exception:
        return "Reviewed as Noted"


def article_heading_ids(body: str) -> str:
    """Give article sections stable ids so Pagefind can link a match to them."""
    n = 0

    def repl(m):
        nonlocal n
        if "id=" in m.group(0):
            return m.group(0)
        n += 1
        rest = m.group(0)[1 + len(m.group(1)):]
        return f'<{m.group(1)} id="s-{n}"{rest}'

    return re.sub(r"<(h[2-4])\b[^>]*", repl, body)


def article_jsonld(a) -> str:
    d = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": a["title"], "datePublished": a.get("date", ""),
        "author": {"@type": "Person", "name": a.get("author", "")},
        "publisher": {"@type": "Organization", "name": "Construction Conversations"},
        "mainEntityOfPage": f"https://constructionconversations.com/articles/{a['slug']}.html",
    }
    if a.get("subtitle"):
        d["description"] = a["subtitle"]
    return json.dumps(d, indent=2)


def build_articles(arts, episodes, tpl_dir: Path):
    out_dir = SITE / "articles"
    out_dir.mkdir(exist_ok=True)
    tpl = (tpl_dir / "article.html").read_text()
    for a in arts:
        eps = [e for e in (_EP_INDEX.get(s) for s in a["episodes"]) if e]
        ep_block = ""
        if eps:
            cards = "".join(
                f'<div class="ep-card"><div class="ep-meta"><span class="tag">{ep_label(e["slug"])}</span>'
                f'<span class="stamp">{esc(e["date"]).upper()}</span></div>'
                f'<h3><a href="../episodes/{e["slug"]}.html">{esc(e["display_title"])}</a></h3>'
                f'<audio controls preload="none" data-src="{e["audio"]}"></audio></div>' for e in eps)
            ep_block = (
                '<div data-pagefind-ignore>'
                '<div class="sec-label" style="margin-top:40px;">Listen to the episode</div>'
                f'{cards}</div>'
            )
        page = tpl
        year = (a.get("date") or "")[:4]
        pf = [
            '<meta data-pagefind-meta="kind:Article">',
            '<meta data-pagefind-filter="type:Article">',
        ]
        if len(year) == 4 and year.isdigit():
            pf.append(f'<meta data-pagefind-filter="year:{year}">')
            pf.append(f'<meta data-pagefind-meta="date:{esc(fmt_date(a.get("date", "")))}">')
        for k, v in {
            "{{TITLE}}": esc(a["title"]),
            "{{SUBTITLE}}": esc(a.get("subtitle", "")),
            "{{TYPE}}": esc(a.get("type", "Article")),
            "{{DATE}}": esc(fmt_date(a.get("date", "")).upper()),
            "{{AUTHOR}}": esc(a.get("author", "")),
            "{{BODY}}": article_heading_ids(a["body"]),
            "{{EPISODE_BLOCK}}": ep_block,
            "{{SUBSTACK_URL}}": a.get("substack", SUBSTACK),
            "{{JSONLD}}": article_jsonld(a),
            "{{PAGEFIND_HEAD}}": "\n".join(pf),
            "{{NEWSLETTER}}": newsletter_block("../"),
        }.items():
            page = page.replace(k, v)
        (out_dir / f'{a["slug"]}.html').write_text(apply_chrome(page, "../"))
    index = (tpl_dir / "articles.html").read_text()
    types = sorted({a.get("type", "") for a in arts})
    filters = "".join(f'<button class="filter" data-type="{esc(t)}">{esc(t)}</button>' for t in types)
    index = index.replace("{{ARTICLE_COUNT}}", str(len(arts)))
    index = index.replace("{{FILTERS}}", filters)
    index = index.replace("{{ARTICLES}}", "\n".join(article_card(a) for a in arts))
    index = index.replace("{{NEWSLETTER}}", newsletter_block(""))
    (SITE / "articles.html").write_text(apply_chrome(index, ""))
    print(f"Wrote site/articles.html + {len(arts)} article pages")


def episode_articles_block(slug: str, arts) -> str:
    hits = [a for a in arts if slug in a["episodes"]]
    if not hits:
        return ""
    links = "".join(
        f'<a class="path-pill" href="../articles/{a["slug"]}.html">{esc(a.get("type", "Article"))}: {esc(a["title"])} →</a>'
        for a in hits)
    return f'<div class="sec-label" style="margin-top:40px;">Read the written version</div><div class="path-pills">{links}</div>'


# ---------------------------------------------------------------------------
# Tools database (Phase 2)

def load_tools():
    p = ROOT / "data" / "tools.json"
    return json.loads(p.read_text()) if p.exists() else {"tools": [], "sponsors": []}


def load_radar():
    p = ROOT / "data" / "radar.json"
    return json.loads(p.read_text()) if p.exists() else {"companies": []}


def load_radar_exclude():
    """Majors that never belong on a discovery page. Editable list."""
    p = ROOT / "data" / "radar_exclude.json"
    return set(json.loads(p.read_text())) if p.exists() else set()


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


EP_REF = re.compile(r"[Ee]p\.?\s*(\d+)")


def radar_matches(company, tools_data):
    """Practitioner mentions from the insights pipeline matching this company."""
    cn = _norm(company["name"])
    out = []
    for t in tools_data.get("tools", []):
        tn = _norm(t["name"])
        if tn == cn or (len(tn) > 5 and (tn in cn or cn in tn)):
            out += [m for m in t["mentions"] if m["source"] == "Practitioner"]
    return out


def coverage_episodes(company):
    return [f"ep-{int(n):03d}" for n in EP_REF.findall(company.get("coverage", ""))]


def tool_anchor(name: str, seen: dict) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "tool"
    n = seen.get(base, 0) + 1
    seen[base] = n
    return base if n == 1 else f"{base}-{n}"


def build_tools(tools_data, tpl_dir: Path, radar=None):
    radar = radar or load_radar()
    exclude = load_radar_exclude()
    proven_rows, radar_rows, csv_rows = [], [], []
    seen_anchors = {}
    cats = sorted({c for co in radar.get("companies", []) for c in co.get("categories", [])})
    n_proven = 0
    for co in sorted(radar.get("companies", []), key=lambda c: c["name"].lower()):
        if co["name"] in exclude:
            continue
        mentions = radar_matches(co, tools_data)
        eps = sorted(set([m["episode"] for m in mentions] + coverage_episodes(co)))
        heard = bool(eps)
        cat_attr = esc("|".join(co.get("categories", [])))
        meta_bits = [b for b in (co.get("stage") if co.get("stage") not in ("", "Unknown") else "", co.get("hq", "")) if b]
        ttw_badge = ""
        if co.get("ttw"):
            issue = f" · CB {esc(co['ttw_issue'])}" if co.get("ttw_issue") else ""
            ttw_badge = f'<span class="tag">Tech to Watch{issue}</span>'
        site_link = f'<a href="{esc(co["website"])}" target="_blank" rel="noopener">{esc(co["website"].replace("https://", "").replace("http://", "").rstrip("/"))}</a>' if co.get("website") else ""
        csv_rows.append([co["name"], "; ".join(co.get("categories", [])), co.get("stage", ""), co.get("hq", ""),
                        "yes" if heard else "", "yes" if co.get("ttw") else "", co.get("website", ""), co.get("oneliner", "")])
        anchor = tool_anchor(co["name"], seen_anchors)
        if heard:
            n_proven += 1
            ctx = "".join(
                f'<li><span class="stamp"><a href="episodes/{m["episode"]}.html">{esc(ep_label(m["episode"]))}</a> · {esc(m["guest"])}</span> {esc(m["context"])}</li>'
                for m in mentions[:3])
            ep_links = " ".join(f'<a href="episodes/{e}.html">{esc(ep_label(e))}</a>' for e in eps)
            proven_rows.append(f'''      <article class="ep-card tool-card" id="tool-{anchor}" data-pagefind-title="{esc(co["name"])}" data-cat="{cat_attr}" data-name="{esc(co["name"].lower())}">
        <div class="ep-meta"><span class="tag">{esc(co["categories"][0] if co.get("categories") else "Contech")}</span>{ttw_badge}<span class="stamp">{esc(" · ".join(meta_bits)).upper()}</span></div>
        <h3 data-pagefind-weight="6">{esc(co["name"])}</h3>
        <p class="ep-desc" data-pagefind-weight="2">{esc(co.get("oneliner", ""))}</p>
        {f'<ul class="tool-ctx">{ctx}</ul>' if ctx else ""}
        <div class="ep-actions"><span class="stamp">Heard in:</span> {ep_links} {site_link}</div>
      </article>''')
        else:
            chips = "".join(f'<span class="pill">{esc(c)}</span>' for c in co.get("categories", []))
            radar_rows.append(f'''      <article class="radar-row" id="radar-{anchor}" data-pagefind-title="{esc(co["name"])}" data-cat="{cat_attr}" data-name="{esc(co["name"].lower())}">
        <div class="radar-head"><h3 data-pagefind-weight="3">{esc(co["name"])}</h3>{ttw_badge}<span class="stamp">{esc(" · ".join(meta_bits)).upper()}</span></div>
        <p data-pagefind-weight="1">{esc(co.get("oneliner", ""))}</p>
        <div class="radar-foot">{chips} {site_link}</div>
      </article>''')
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Company", "Categories", "Stage", "HQ", "Heard on the show", "Tech to Watch", "Website", "What they do"])
    w.writerows(csv_rows)
    (SITE / "assets").mkdir(exist_ok=True)
    (SITE / "assets" / "tools.csv").write_text(buf.getvalue())
    page = (tpl_dir / "tools.html").read_text()
    page = page.replace("{{PROVEN_COUNT}}", str(n_proven))
    page = page.replace("{{RADAR_COUNT}}", str(len(radar_rows)))
    page = page.replace("{{FILTERS}}", "".join(f'<button class="filter" data-type="{esc(c)}">{esc(c)}</button>' for c in cats))
    page = page.replace("{{PROVEN}}", "\n".join(proven_rows))
    page = page.replace("{{RADAR}}", "\n".join(radar_rows))
    page = page.replace("{{NEWSLETTER}}", newsletter_block(""))
    (SITE / "tools.html").write_text(apply_chrome(page, ""))
    print(f"Wrote site/tools.html ({n_proven} proven on the show, {len(radar_rows)} on the radar, {len(exclude)} majors excluded) + assets/tools.csv")


def episode_tools_block(slug: str, data) -> str:
    names = sorted({t["name"] for t in data.get("tools", [])
                    if any(m["episode"] == slug and m["source"] == "Practitioner" for m in t["mentions"])})
    if not names:
        return ""
    return (f'<p class="stamp dim" style="margin-top:16px;">Tools this guest actually uses: {esc(", ".join(names))}. '
            f'<a href="../tools.html" style="color:var(--crane);">See the database →</a></p>')


# ---------------------------------------------------------------------------
# Lessons (Phase 1.5 hook + Phase 2 database)

def load_lessons():
    p = ROOT / "data" / "lessons.json"
    return merge_deck(json.loads(p.read_text())) if p.exists() else {"lessons": []}


def merge_deck(data):
    """Fold data/deck/out_*.json enrichment (story, quote, quote_time, move) into lessons."""
    enrich = {}
    for f in sorted((ROOT / "data" / "deck").glob("out_*.json")):
        try:
            for r in json.loads(f.read_text()):
                enrich[r["n"]] = r
        except Exception as e:
            print(f"WARNING deck {f.name}: {e}")
    for l in data.get("lessons", []):
        e = enrich.get(l["n"])
        if e:
            l.setdefault("story", e.get("story", ""))
            l.setdefault("quote", e.get("quote", ""))
            l.setdefault("quote_time", e.get("quote_time", ""))
            l.setdefault("move", e.get("move", ""))
    return data


ROLE_LABEL = {"Super": "Supers", "PM": "PMs", "Exec": "Execs & Owners", "Founder": "Founders"}


def lesson_seconds(l) -> str:
    t = l.get("quote_time") or ""
    if not t:
        return ""
    try:
        return str(t2s(t))
    except (TypeError, ValueError):
        return ""


def lesson_year(slug: str) -> str:
    ep = _EP_INDEX.get(slug) or {}
    iso = ep.get("date_iso") or ""
    return iso[:4] if len(iso) >= 4 and iso[:4].isdigit() else ""


def lesson_card(l, base: str = "") -> str:
    roles = l.get("roles", [])
    ep = l["episode"]
    t = l.get("quote_time", "")
    hear = f'{base}episodes/{ep}.html'
    if t:
        try:
            hear += f"#t={t2s(t)}"
        except (TypeError, ValueError):
            pass
    story = f'<p class="l-story" data-pagefind-weight="1.5">{esc(l.get("story") or l.get("detail", ""))}</p>'
    quote = ""
    if l.get("quote"):
        cite = esc(l.get("guest", "")) + ((" · " + esc(t)) if t else "")
        quote = f'<blockquote class="ep-quote" data-pagefind-weight="1.5"><p>"{esc(l["quote"])}"</p><cite>{cite}</cite></blockquote>'
    move = f'<p class="l-move" data-pagefind-weight="1.5"><span class="stamp orange">The move</span> {esc(l["move"])}</p>' if l.get("move") else ""
    # Role filter values are Super / PM / Exec / Founder. The pill text stays
    # the longer label ("Supers", "PMs"). The inline filter syntax does not
    # index the value as extra body copy.
    chips = "".join(
        f'<span class="pill" data-pagefind-filter="role:{esc(r)}">{html.escape(ROLE_LABEL.get(r, r))}</span>'
        for r in roles)
    hear_txt = "Hear it" + ((" at " + esc(t)) if t else "")
    guest = l.get("guest") or ""
    guest_attr = f' data-pagefind-filter="guest:{esc(guest)}"' if guest else ""
    title = pf_record(
        l.get("lesson") or "",
        guest=guest,
        slug=ep,
        year=lesson_year(ep),
        roles=roles,
        paths=paths_for(ep),
        seconds=lesson_seconds(l),
    )
    return (
        f'      <article class="lesson" id="l{l["n"]}" data-roles="{" ".join(roles)}" data-pagefind-title="{title}">\n'
        f'        <div class="lesson-n">{l["n"]:02d}</div>\n'
        f'        <div>\n'
        f'          <div class="ep-meta">{chips}<a class="stamp" href="{hear}">{esc(ep_label(ep))}</a></div>\n'
        f'          <h3 data-pagefind-weight="10">{esc(l["lesson"])}</h3>\n'
        f'          {story}\n'
        f'          {quote}\n'
        f'          {move}\n'
        f'          <p class="stamp"{guest_attr}>{esc(guest)}{(" · " + esc(l["role"])) if l.get("role") else ""} · <a href="{hear}" style="color:var(--crane);">{hear_txt} →</a></p>\n'
        f'        </div>\n'
        f'      </article>')


SIT_ORDER = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]


def lessons_sections(data, base: str = "", role: str = "") -> str:
    sits = data.get("situations", {})
    out = []
    for i, sid in enumerate(SIT_ORDER, 1):
        group = [l for l in data["lessons"] if l.get("situation") == sid
                 and (not role or role in l.get("roles", []))]
        if not group:
            continue
        meta = sits.get(sid, {"title": sid, "sub": ""})
        cards = "\n".join(lesson_card(l, base) for l in group)
        out.append(
            f'    <div class="sit-block" id="{sid.lower()}">\n'
            f'      <div class="sec-label" data-pagefind-ignore>{i:02d} / {esc(meta["title"])} · {esc(meta["sub"])}</div>\n'
            f'      <div class="lessons">\n{cards}\n      </div>\n    </div>')
    return "\n".join(out)


def lesson_pagefind_head(data) -> str:
    """Page-level year and path filters. Role and guest come from each card."""
    years, paths = set(), set()
    for l in data.get("lessons") or []:
        y = lesson_year(l.get("episode") or "")
        if y:
            years.add(y)
        for title in paths_for(l.get("episode") or ""):
            paths.add(title)
    bits = [
        '<meta data-pagefind-meta="title:The 50 most expensive lessons">',
        '<meta data-pagefind-meta="kind:Lesson">',
        '<meta data-pagefind-filter="type:Lesson">',
    ]
    for y in sorted(years):
        bits.append(f'<meta data-pagefind-filter="year:{esc(y)}">')
    for title in sorted(paths):
        bits.append(f'<meta data-pagefind-filter="path:{esc(title)}">')
    return "\n".join(bits)


def build_lessons(data, tpl_dir: Path):
    lessons = data.get("lessons", [])
    if not lessons:
        print("lessons.json missing or empty; skipped site/lessons.html")
        return
    n_eps = len({l["episode"] for l in lessons})
    page = (tpl_dir / "lessons.html").read_text()
    page = page.replace("{{LESSONS}}", lessons_sections(data))
    page = page.replace("{{LESSON_COUNT}}", str(n_eps))
    page = page.replace("{{PAGEFIND_HEAD}}", lesson_pagefind_head(data))
    page = page.replace("{{NEWSLETTER}}", newsletter_block("", compact=True))
    (SITE / "lessons.html").write_text(apply_chrome(page, ""))
    enriched = sum(1 for l in lessons if l.get("story"))
    print(f"Wrote site/lessons.html ({len(lessons)} lessons, {enriched} enriched)")


# ---------------------------------------------------------------------------
# Reviews (Phase 1.5)

def load_reviews(offline: bool):
    cache = ROOT / "data" / "reviews.json"
    reviews = json.loads(cache.read_text()) if cache.exists() else []
    if not offline:
        try:
            req = urllib.request.Request(APPLE_REVIEWS, headers={"User-Agent": "cc-site-builder"})
            feed = json.loads(urllib.request.urlopen(req, timeout=20).read())
            entries = feed.get("feed", {}).get("entry", [])
            if isinstance(entries, dict):
                entries = [entries]
            fresh = [{
                "title": e["title"]["label"], "text": e["content"]["label"],
                "rating": int(e["im:rating"]["label"]), "author": e["author"]["name"]["label"],
                "source": "Apple Podcasts",
            } for e in entries if "im:rating" in e]
            # keep any hand-added (LinkedIn etc.) reviews from the cache
            keep = [r for r in reviews if r.get("source") != "Apple Podcasts"]
            reviews = fresh + keep
            cache.write_text(json.dumps(reviews, indent=1))
        except Exception as e:
            print(f"Apple reviews skipped: {e}")
    return reviews


def build_reviews(reviews, tpl_dir: Path):
    cards = "".join(
        f'''      <article class="ep-card review">
        <div class="ep-meta"><span class="tag">{"★" * int(r.get("rating", 5))}</span><span class="stamp">{esc(r.get("source", ""))}</span></div>
        <h3>{esc(r.get("title", ""))}</h3>
        <p class="ep-desc">{esc(r.get("text", ""))}</p>
        <p class="stamp">{esc(r.get("author", ""))}</p>
      </article>''' for r in reviews)
    page = (tpl_dir / "reviews.html").read_text()
    page = page.replace("{{REVIEWS}}", cards).replace("{{RATE_URL}}", APPLE_RATE)
    page = page.replace("{{NEWSLETTER}}", newsletter_block(""))
    (SITE / "reviews.html").write_text(apply_chrome(page, ""))
    print(f"Wrote site/reviews.html ({len(reviews)} reviews)")


# ---------------------------------------------------------------------------
# Join In + stories (Phase 3)

def load_stories():
    stories = [parse_md(f) for f in (ROOT / "stories").glob("*.md")]
    stories.sort(key=lambda s: s.get("date", ""), reverse=True)
    return stories


def build_join(stories, tpl_dir: Path):
    page = (tpl_dir / "join.html").read_text()
    page = page.replace("{{NEWSLETTER}}", newsletter_block(""))
    (SITE / "join.html").write_text(apply_chrome(page, ""))

    cards = "".join(
        f'''      <article class="ep-card story">
        <div class="ep-meta"><span class="tag">{esc(s.get("theme", "From the field"))}</span><span class="stamp">{esc(fmt_date(s.get("date", "")).upper())}</span></div>
        <h3>{esc(s["title"])}</h3>
        <div class="ep-body">{s["body"]}</div>
        <p class="stamp">{esc(s.get("author", "Anonymous"))}{(", " + esc(s["role"])) if s.get("role") else ""}</p>
      </article>''' for s in stories)
    sp = (tpl_dir / "stories.html").read_text()
    sp = sp.replace("{{STORIES}}", cards or '<p class="lede">The first stories are being reviewed. Yours could be here.</p>')
    sp = sp.replace("{{STORY_COUNT}}", str(len(stories)))
    sp = sp.replace("{{NEWSLETTER}}", newsletter_block(""))
    (SITE / "stories.html").write_text(apply_chrome(sp, ""))
    print(f"Wrote site/join.html + site/stories.html ({len(stories)} stories)")


def build_translator(tpl_dir: Path):
    """Standalone /translator.html. Copy stays in data/translator.json."""
    data = json.loads((ROOT / "data" / "translator.json").read_text())
    if data.get("placeholder") is not True:
        raise SystemExit("data/translator.json: placeholder must stay true until copy is approved")
    templates = data.get("templates") or []
    if len(templates) < 25:
        raise SystemExit(f"data/translator.json: need at least 25 templates, found {len(templates)}")
    for i, line in enumerate(templates):
        if not isinstance(line, str) or "PLACEHOLDER" not in line or "{phrase}" not in line:
            raise SystemExit(f"data/translator.json: template {i} must include PLACEHOLDER and {{phrase}}")
    url = data.get("subscribe_url") or ""
    if not url.startswith("https://constructionbriefs.substack.com/"):
        raise SystemExit("data/translator.json: subscribe_url must be the Construction Briefs URL")
    if len(data.get("buzzwords") or []) < 10:
        raise SystemExit("data/translator.json: buzzword list is missing")
    page = (tpl_dir / "translator.html").read_text()
    if "{{TRANSLATOR_JSON}}" not in page or "{{SUBSCRIBE_URL}}" not in page:
        raise SystemExit("templates/translator.html is missing placeholders")
    if 'rel="noopener"' not in page:
        raise SystemExit("templates/translator.html subscribe link needs rel=\"noopener\"")
    lowered = page.lower()
    if "noreferrer" in lowered or "referrerpolicy" in lowered or "referrer-policy" in lowered:
        raise SystemExit("translator page must not set a stricter referrer policy")
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    page = page.replace("{{TRANSLATOR_JSON}}", blob)
    page = page.replace("{{SUBSCRIBE_URL}}", html.escape(url, quote=True))
    if "{{" in page:
        raise SystemExit("translator template has an unfilled placeholder")
    (SITE / "translator.html").write_text(apply_chrome(page, ""))
    print(f"Wrote site/translator.html ({len(templates)} placeholder templates, noindex)")
