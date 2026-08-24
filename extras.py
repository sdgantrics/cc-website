"""Audience-site renderers for build.py (Phases 1.5, 2, 3).

Data in:
  data/chapters/<slug>.json  timestamped chapters, guest, mentions, quotes
  articles/<slug>.md         front matter + HTML body (Recaps, Insider Takes, Debriefs, Essays)
  data/tools.json            tools mentioned on the show, from the Episode Insights DB
  data/lessons.json          the 50 most expensive lessons (newsletter hook)
  data/reviews.json          Apple Podcasts reviews cache (refreshed online)
  data/upcoming.json         next guests for the Ask form
  stories/<slug>.md          listener-submitted field stories (moderated)

Pages out:
  site/articles.html, site/articles/<slug>.html
  site/tools.html, site/assets/tools.csv
  site/lessons.html
  site/reviews.html
  site/join.html, site/stories.html
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

FOOT_ITEMS = [
    ("https://podcasts.apple.com/us/podcast/construction-conversations/id1746691812", "Apple", "Platform: Apple"),
    ("https://open.spotify.com/show/3TPc3EDgxGvmJoRwmffVL3", "Spotify", "Platform: Spotify"),
    ("https://www.youtube.com/@ConstructionConversations", "YouTube", "Platform: YouTube"),
    ("https://www.linkedin.com/company/construction-conversations/", "LinkedIn", ""),
    (f"{SUBSTACK}/", "Briefs", ""),
    ("episodes.html?q=reviewed%20as%20noted", "Reviewed as Noted", ""),
    ("reviews.html", "Reviews", ""),
    ("join.html#guest", "Be a Guest", ""),
    ("sponsors.html", "Sponsor the show", "Sponsor Link: Footer"),
]


def nav_html(base: str) -> str:
    items = "".join(f'\n      <li><a href="{base}{h}">{t}</a></li>' for h, t in NAV_ITEMS)
    cta = f'\n      <li><a class="nav-cta" href="{base}{NAV_CTA[0]}" data-event="Nav: Lessons">{NAV_CTA[1]}</a></li>'
    return f'<ul class="nav-links">{items}{cta}\n    </ul>'


def foot_html(base: str) -> str:
    out = []
    for h, t, ev in FOOT_ITEMS:
        href = h if h.startswith("http") else base + h
        ext = ' target="_blank" rel="noopener"' if h.startswith("http") else ""
        evt = f' data-event="{ev}"' if ev else ""
        out.append(f'      <a href="{href}"{evt}{ext}>{t}</a>')
    return '<div class="foot-links">\n' + "\n".join(out) + "\n    </div>"


NAV_RE = re.compile(r'<ul class="nav-links">.*?</ul>', re.S)
FOOT_RE = re.compile(r'<div class="foot-links">.*?</div>', re.S)


def apply_chrome(page: str, base: str) -> str:
    page = NAV_RE.sub(lambda m: nav_html(base), page, count=1)
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


def chapters_block(ch) -> str:
    if not ch or not ch.get("chapters"):
        return ""
    rows = "".join(
        f'<li><a class="chapter" href="#t={t2s(c["time"])}" data-t="{t2s(c["time"])}">'
        f'<span class="stamp">{esc(c["time"])}</span><span>{esc(c["title"])}</span></a></li>'
        for c in ch["chapters"])
    return f'''<div class="sec-label" style="margin-top:40px;">In this episode</div>
  <ol class="chapters">{rows}</ol>
  <p class="stamp dim">Timestamps are from the recording and may drift a minute or two from the published edit.</p>'''


def quotes_block(ch) -> str:
    if not ch or not ch.get("quotes"):
        return ""
    q = "".join(
        f'<blockquote class="ep-quote"><p>"{esc(x["text"])}"</p><cite>{esc(x.get("who", ""))}'
        + (f' · <a class="chapter" href="#t={t2s(x["time"])}" data-t="{t2s(x["time"])}">{esc(x["time"])}</a>' if x.get("time") else "")
        + "</cite></blockquote>"
        for x in ch["quotes"])
    return f'<div class="sec-label" style="margin-top:40px;">Worth writing down</div>{q}'


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
            ep_block = f'<div class="sec-label" style="margin-top:40px;">Listen to the episode</div>{cards}'
        page = tpl
        for k, v in {
            "{{TITLE}}": esc(a["title"]),
            "{{SUBTITLE}}": esc(a.get("subtitle", "")),
            "{{TYPE}}": esc(a.get("type", "Article")),
            "{{DATE}}": esc(fmt_date(a.get("date", "")).upper()),
            "{{AUTHOR}}": esc(a.get("author", "")),
            "{{BODY}}": a["body"],
            "{{EPISODE_BLOCK}}": ep_block,
            "{{SUBSTACK_URL}}": a.get("substack", SUBSTACK),
            "{{JSONLD}}": article_jsonld(a),
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


def build_tools(tools_data, tpl_dir: Path, radar=None):
    radar = radar or load_radar()
    exclude = load_radar_exclude()
    proven_rows, radar_rows, csv_rows = [], [], []
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
        if heard:
            n_proven += 1
            ctx = "".join(
                f'<li><span class="stamp"><a href="episodes/{m["episode"]}.html">{esc(ep_label(m["episode"]))}</a> · {esc(m["guest"])}</span> {esc(m["context"])}</li>'
                for m in mentions[:3])
            ep_links = " ".join(f'<a href="episodes/{e}.html">{esc(ep_label(e))}</a>' for e in eps)
            proven_rows.append(f'''      <article class="ep-card tool-card" data-cat="{cat_attr}" data-name="{esc(co["name"].lower())}">
        <div class="ep-meta"><span class="tag">{esc(co["categories"][0] if co.get("categories") else "Contech")}</span>{ttw_badge}<span class="stamp">{esc(" · ".join(meta_bits)).upper()}</span></div>
        <h3>{esc(co["name"])}</h3>
        <p class="ep-desc">{esc(co.get("oneliner", ""))}</p>
        {f'<ul class="tool-ctx">{ctx}</ul>' if ctx else ""}
        <div class="ep-actions"><span class="stamp">Heard in:</span> {ep_links} {site_link}</div>
      </article>''')
        else:
            chips = "".join(f'<span class="pill">{esc(c)}</span>' for c in co.get("categories", []))
            radar_rows.append(f'''      <article class="radar-row" data-cat="{cat_attr}" data-name="{esc(co["name"].lower())}">
        <div class="radar-head"><h3>{esc(co["name"])}</h3>{ttw_badge}<span class="stamp">{esc(" · ".join(meta_bits)).upper()}</span></div>
        <p>{esc(co.get("oneliner", ""))}</p>
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


def lesson_card(l, base: str = "") -> str:
    roles = l.get("roles", [])
    ep = l["episode"]
    t = l.get("quote_time", "")
    hear = f'{base}episodes/{ep}.html'
    if t:
        hear += f"#t={t2s(t)}"
    story = f'<p class="l-story">{esc(l.get("story") or l.get("detail", ""))}</p>'
    quote = ""
    if l.get("quote"):
        cite = esc(l.get("guest", "")) + ((" · " + esc(t)) if t else "")
        quote = f'<blockquote class="ep-quote"><p>"{esc(l["quote"])}"</p><cite>{cite}</cite></blockquote>'
    move = f'<p class="l-move"><span class="stamp orange">The move</span> {esc(l["move"])}</p>' if l.get("move") else ""
    chips = "".join(f'<span class="pill">{html.escape(ROLE_LABEL.get(r, r))}</span>' for r in roles)
    hear_txt = "Hear it" + ((" at " + esc(t)) if t else "")
    return (
        f'      <article class="lesson" id="l{l["n"]}" data-roles="{" ".join(roles)}">\n'
        f'        <div class="lesson-n">{l["n"]:02d}</div>\n'
        f'        <div>\n'
        f'          <div class="ep-meta">{chips}<a class="stamp" href="{hear}">{esc(ep_label(ep))}</a></div>\n'
        f'          <h3>{esc(l["lesson"])}</h3>\n'
        f'          {story}\n'
        f'          {quote}\n'
        f'          {move}\n'
        f'          <p class="stamp">{esc(l.get("guest", ""))}{(" · " + esc(l["role"])) if l.get("role") else ""} · <a href="{hear}" style="color:var(--crane);">{hear_txt} →</a></p>\n'
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
            f'      <div class="sec-label">{i:02d} / {esc(meta["title"])} · {esc(meta["sub"])}</div>\n'
            f'      <div class="lessons">\n{cards}\n      </div>\n    </div>')
    return "\n".join(out)


def build_lessons(data, tpl_dir: Path):
    lessons = data.get("lessons", [])
    if not lessons:
        print("lessons.json missing or empty; skipped site/lessons.html")
        return
    n_eps = len({l["episode"] for l in lessons})
    page = (tpl_dir / "lessons.html").read_text()
    page = page.replace("{{LESSONS}}", lessons_sections(data))
    page = page.replace("{{LESSON_COUNT}}", str(n_eps))
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
