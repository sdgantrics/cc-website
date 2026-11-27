"""Editorial lesson pages.

Human-owned files live in content/episodes/<slug>.yml and are never
written by the build. Draft suggestions go to content/episodes/_drafts/
and are not published. The daily build does not call the Anthropic API.

A lesson number in the YAML points at data/lessons.json. Lessons and
tools that cite the episode are added even when the YAML omits them.
"""

import html
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import yaml

import extras

ROOT = Path(__file__).parent
CONTENT = ROOT / "content" / "episodes"
DRAFTS = CONTENT / "_drafts"
SITE = "https://constructionconversations.com"
ROLES = ("Super", "PM", "Exec", "Founder")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def esc(s: str) -> str:
    return extras.esc(s)


def norm_words(s: str) -> str:
    """Whitespace, punctuation, and case. Words stay in order."""
    s = unicodedata.normalize("NFKC", s or "")
    s = (s.replace("\u2019", "'").replace("\u2018", "'")
         .replace("\u201c", '"').replace("\u201d", '"'))
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip().casefold()
    return s


def word_stream(segments):
    words = []
    for seg in segments or []:
        raw = seg.get("start_sec", seg.get("start", 0))
        try:
            sec = int(raw)
        except (TypeError, ValueError):
            sec = 0
        for w in norm_words(seg.get("text") or "").split():
            words.append((w, sec))
    return words


def locate_quote(quote: str, segments):
    """Second where quote begins, or None. The model's sec is ignored."""
    words = word_stream(segments)
    q = norm_words(quote).split()
    if not q or not words:
        return None
    n = len(q)
    for i in range(len(words) - n + 1):
        if [w for w, _ in words[i:i + n]] == q:
            return words[i][1]
    return None


def _word_at(stream: str, frag: str):
    """Index of the first word of frag in stream, or None. Boundaries only."""
    start = 0
    while True:
        idx = stream.find(frag, start)
        if idx < 0:
            return None
        end = idx + len(frag)
        left_ok = idx == 0 or stream[idx - 1] == " "
        right_ok = end == len(stream) or stream[end] == " "
        if left_ok and right_ok:
            return 0 if idx == 0 else stream[:idx].count(" ") + (0 if stream[idx - 1] == " " else 1)
        start = idx + 1


def _longest_from(stream: str, q, offset: int, minimum: int):
    """Longest q[offset:] prefix that sits on a word boundary in stream."""
    hi = len(q) - offset
    best = 0
    lo = minimum
    while lo <= hi:
        mid = (lo + hi) // 2
        frag = " ".join(q[offset:offset + mid])
        if _word_at(stream, frag) is not None:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    if not best:
        return None
    frag = " ".join(q[offset:offset + best])
    return _word_at(stream, frag), best


def best_quote_sec(quote: str, segments, minimum: int = 6):
    """Where the quote's words actually start in the transcript.

    Deck quotes are sometimes tightened ('gonna', a repeated word). Prefer
    a match that begins at the first word of the quote.
    """
    words = word_stream(segments)
    q = norm_words(quote).split()
    if len(q) < minimum or not words:
        return None
    stream = " ".join(w for w, _ in words)
    secs = [sec for _, sec in words]
    found = _longest_from(stream, q, 0, minimum)
    if found:
        return secs[found[0]]
    # The opening words were edited. Take the earliest later run that matches.
    best = None
    for offset in range(1, min(len(q) - minimum + 1, 24)):
        hit = _longest_from(stream, q, offset, minimum)
        if hit and (best is None or (offset, -hit[1]) < (best[0], -best[1])):
            best = (offset, hit[1], secs[hit[0]])
    return best[2] if best else None


def segments_for(doc) -> list:
    cues = (doc or {}).get("cues") or []
    if cues:
        return [{"start_sec": int(c.get("start_sec") or 0), "text": c.get("text") or ""} for c in cues]
    return [
        {"start_sec": int(p.get("start_sec") or 0), "text": p.get("text") or ""}
        for p in ((doc or {}).get("transcript") or [])
    ]


def load_editorial():
    """Published YAML only. _drafts/ is never read."""
    out = {}
    if not CONTENT.exists():
        return out
    for path in sorted(CONTENT.glob("*.yml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"WARNING editorial {path.name}: {e}")
            continue
        if not isinstance(data, dict):
            print(f"WARNING editorial {path.name}: expected a mapping")
            continue
        data["slug"] = path.stem
        out[path.stem] = data
    return out


def index_lessons(data):
    by_n, by_ep = {}, {}
    for lesson in (data or {}).get("lessons") or []:
        by_n[lesson["n"]] = lesson
        by_ep.setdefault(lesson.get("episode") or "", []).append(lesson)
    for bucket in by_ep.values():
        bucket.sort(key=lambda l: l["n"])
    return by_n, by_ep


def tool_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "tool"


def index_tools(data):
    by_slug, by_ep = {}, {}
    for tool in (data or {}).get("tools") or []:
        slug = tool_slug(tool.get("name") or "")
        by_slug[slug] = tool
        seen = set()
        for mention in tool.get("mentions") or []:
            ep = mention.get("episode") or ""
            if not ep or ep in seen:
                continue
            seen.add(ep)
            by_ep.setdefault(ep, []).append((slug, tool))
    return by_slug, by_ep


def resolved_lessons(slug, ed, by_n, by_ep):
    """YAML order first, then lessons.json entries that cite the episode."""
    out, seen = [], set()
    for item in (ed or {}).get("lessons") or []:
        if isinstance(item, bool):
            continue
        if isinstance(item, int) or (isinstance(item, str) and str(item).isdigit()):
            n = int(item)
            lesson = by_n.get(n)
            if not lesson:
                print(f"WARNING {slug}: no lesson {n} in data/lessons.json")
                continue
            if lesson.get("episode") and lesson["episode"] != slug:
                print(f"WARNING {slug}: lesson {n} is filed under {lesson['episode']}")
            if n in seen:
                continue
            seen.add(n)
            out.append(("deck", lesson))
            continue
        if isinstance(item, dict):
            out.append(("inline", item))
            continue
        print(f"WARNING {slug}: lesson entry {item!r} skipped")
    for lesson in by_ep.get(slug) or []:
        if lesson["n"] in seen:
            continue
        seen.add(lesson["n"])
        out.append(("deck", lesson))
    return out


def resolved_tools(slug, ed, by_slug, by_ep):
    out, seen = [], set()
    for name in (ed or {}).get("tools") or []:
        tool = by_slug.get(str(name))
        if not tool:
            print(f"WARNING {slug}: unknown tool slug {name}")
            continue
        if name in seen:
            continue
        seen.add(str(name))
        out.append((str(name), tool))
    for name, tool in by_ep.get(slug) or []:
        if name in seen:
            continue
        seen.add(name)
        out.append((name, tool))
    return out


def guest_phrase(g: dict) -> str:
    name = (g.get("name") or "").strip()
    title = (g.get("title") or "").strip()
    firm = (g.get("firm") or "").strip()
    if not name:
        return ""
    if title and firm:
        return f"{name}, {title} at {firm}"
    if title:
        return f"{name}, {title}"
    if firm:
        return f"{name} at {firm}"
    return name


def join_phrases(phrases):
    phrases = [p for p in phrases if p]
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    if len(phrases) == 2:
        return f"{phrases[0]} and {phrases[1]}"
    return ", ".join(phrases[:-1]) + ", and " + phrases[-1]


def episode_title(ep) -> str:
    """The <h1>. The episode title only, same as before the editorial layer."""
    return ep.get("display_title") or ep.get("title") or ""


def document_title(ep, ed) -> str:
    """<title> and Open Graph. Guest, title, and firm lead the episode title."""
    title = episode_title(ep)
    guests = [guest_phrase(g) for g in ((ed or {}).get("guests") or [])]
    lead = join_phrases(guests)
    if lead:
        return f"{lead}: {title}"
    return title


def byline_html(ed, hand) -> str:
    """Stamp under the h1. YAML guests replace the chapter-file byline."""
    phrases = []
    for g in (ed or {}).get("guests") or []:
        name = (g.get("name") or "").strip()
        if not name:
            continue
        bits = [name]
        for key in ("title", "firm"):
            value = (g.get(key) or "").strip()
            if value:
                bits.append(value)
        phrases.append(" · ".join(bits))
    if phrases:
        lines = []
        for i, phrase in enumerate(phrases):
            meta = ' data-pagefind-meta="guest"' if i == 0 else ""
            lines.append(f'<p class="stamp guest-line"{meta}>{esc(phrase)}</p>')
        return "\n".join(lines)
    line = extras.guest_line(hand)
    if not line:
        return ""
    return f'<p class="stamp guest-line" data-pagefind-meta="guest">{line}</p>'


def quote_sec_for_deck(lesson, segments):
    quote = lesson.get("quote") or ""
    sec = locate_quote(quote, segments) if quote else None
    if sec is None and quote:
        sec = best_quote_sec(quote, segments)
    if sec is None and lesson.get("quote_time"):
        try:
            sec = extras.t2s(lesson["quote_time"])
        except (TypeError, ValueError):
            sec = None
    return sec


def social_description(lessons, pull_quotes, summary, fallback: str) -> str:
    for kind, lesson in lessons:
        headline = lesson.get("headline") if kind == "inline" else lesson.get("lesson")
        if headline:
            return headline
    for q in pull_quotes or []:
        if q.get("text"):
            return q["text"]
    if (summary or "").strip():
        return summary.strip()
    return fallback or ""


def _chips(roles):
    return "".join(
        f'<span class="pill">{html.escape(extras.ROLE_LABEL.get(r, r))}</span>'
        for r in (roles or []) if r
    )


def _time_link(sec, event: str) -> str:
    if sec is None:
        return ""
    label = extras.clock(sec)
    return (
        f'<a class="chapter" href="#t={sec}" data-t="{sec}" data-event="{html.escape(event)}">'
        f'{esc(label)}</a>'
    )


def lesson_cards(slug, lessons, segments):
    if not lessons:
        return ""
    cards = []
    for i, (kind, lesson) in enumerate(lessons, 1):
        if kind == "deck":
            n = lesson["n"]
            num = f"{n:02d}"
            anchor = f"l{n}"
            headline = lesson.get("lesson") or ""
            story = lesson.get("story") or lesson.get("detail") or ""
            quote = lesson.get("quote") or ""
            speaker = lesson.get("guest") or ""
            move = lesson.get("move") or ""
            roles = lesson.get("roles") or []
            sec = quote_sec_for_deck(lesson, segments)
            stamp = (
                f'<a class="stamp" href="../lessons.html#l{n}">{esc(extras.ep_label(slug))}</a>'
            )
        else:
            num = f"{i:02d}"
            raw_id = re.sub(r"[^a-z0-9-]+", "-", str(lesson.get("id") or i).lower()).strip("-") or str(i)
            anchor = f"lesson-{raw_id}"
            headline = lesson.get("headline") or ""
            story = lesson.get("what_it_cost") or ""
            quote = lesson.get("quote") or ""
            speaker = lesson.get("quote_speaker") or ""
            move = lesson.get("the_move") or ""
            roles = lesson.get("roles") or []
            sec = locate_quote(quote, segments) if quote else None
            stamp = f'<span class="stamp">{esc(extras.ep_label(slug))}</span>'
        quote_html = ""
        if quote:
            cite = esc(speaker)
            link = _time_link(sec, "Lesson Seek")
            if link:
                cite = f"{cite} · {link}" if cite else link
            quote_html = (
                f'<blockquote class="ep-quote"><p>"{esc(quote)}"</p>'
                f'<cite>{cite}</cite></blockquote>'
            )
        move_html = (
            f'<p class="l-move"><span class="stamp orange">The move</span> {esc(move)}</p>'
            if move else ""
        )
        story_html = f'<p class="l-story">{esc(story)}</p>' if story else ""
        cards.append(
            f'<article class="lesson" id="{anchor}">\n'
            f'  <div class="lesson-n">{num}</div>\n'
            f'  <div>\n'
            f'    <div class="ep-meta">{_chips(roles)}{stamp}</div>\n'
            f'    <h3 data-pagefind-weight="10">{esc(headline)}</h3>\n'
            f'    {story_html}\n'
            f'    {quote_html}\n'
            f'    {move_html}\n'
            f'  </div>\n'
            f'</article>'
        )
    return (
        '<div class="sec-label" style="margin-top:40px;">The lessons</div>\n'
        '<div class="lessons">\n' + "\n".join(cards) + "\n</div>"
    )


def who_block(ed, paths):
    if not ed:
        return ""
    roles = [r for r in (ed.get("roles") or []) if r]
    wanted = [p for p in (ed.get("paths") or []) if p]
    summary = (ed.get("summary") or "").strip()
    by_slug = {p["slug"]: p for p in paths or []}
    badges = []
    for slug in wanted:
        p = by_slug.get(slug)
        if not p:
            print(f"WARNING {ed.get('slug')}: unknown path {slug}")
            continue
        badges.append(
            f'<a class="path-pill" href="../start/{html.escape(slug)}.html" '
            f'data-event="Path: {esc(p.get("tag") or p.get("title") or "")}">'
            f'{esc(p.get("title") or slug)}</a>'
        )
    if not roles and not badges and not summary:
        return ""
    parts = ['<div class="sec-label" style="margin-top:40px;">Who this is for</div>']
    if roles or badges:
        parts.append(f'<div class="ep-meta">{_chips(roles)}</div>')
    if badges:
        parts.append(f'<div class="path-pills">{"".join(badges)}</div>')
    if summary:
        parts.append(f'<p class="ep-body">{esc(summary)}</p>')
    return "\n".join(parts)


def worth_writing_down(quotes, segments):
    """Pull quotes under the existing heading, with times from the transcript.

    Used only when the YAML lists pull_quotes. The hand-written quotes in
    data/chapters stay on disk and still render for episodes with no YAML.
    """
    kept = []
    for q in quotes or []:
        text = (q.get("text") or "").strip()
        if not text:
            continue
        kept.append((q, locate_quote(text, segments)))
    if not kept:
        return ""
    parts = []
    for q, sec in kept:
        link = _time_link(sec, "Quote Seek")
        who = esc(q.get("speaker") or "")
        cite = f"{who}{(' · ' + link) if link else ''}" if who else link
        parts.append(
            f'<blockquote class="ep-quote"><p>"{esc(q.get("text") or "")}"</p>'
            f'<cite>{cite}</cite></blockquote>'
        )
    return (
        '<div data-pagefind-ignore>'
        '<div class="sec-label" style="margin-top:40px;">Worth writing down</div>'
        + "".join(parts) + '</div>'
    )


_TOOL_ANCHORS = None


def published_tool_anchors():
    """Ids on tools.html. Majors in radar_exclude.json are not given an entry."""
    global _TOOL_ANCHORS
    if _TOOL_ANCHORS is not None:
        return _TOOL_ANCHORS
    radar = extras.load_radar()
    exclude = extras.load_radar_exclude()
    seen = {}
    anchors = set()
    for co in sorted(radar.get("companies") or [], key=lambda c: (c.get("name") or "").lower()):
        if co.get("name") in exclude:
            continue
        anchors.add(extras.tool_anchor(co.get("name") or "", seen))
    _TOOL_ANCHORS = anchors
    return anchors


def tools_block(slug, tools):
    if not tools:
        return ""
    anchors = published_tool_anchors()
    cards = []
    for name, tool in tools:
        mention = next((m for m in (tool.get("mentions") or []) if m.get("episode") == slug), None)
        ctx = ""
        if mention and mention.get("context"):
            ctx = f'<p class="ep-desc">{esc(mention["context"])}</p>'
        cat = tool.get("category") or "Tool"
        href = f"../tools.html#tool-{name}" if name in anchors else "../tools.html"
        cards.append(
            f'<article class="ep-card tool-card">'
            f'<div class="ep-meta"><span class="tag">{esc(cat)}</span></div>'
            f'<h3><a href="{href}">{esc(tool.get("name") or name)}</a></h3>'
            f'{ctx}</article>'
        )
    return (
        '<div class="sec-label" style="margin-top:40px;">Tools mentioned</div>\n'
        + "\n".join(cards)
    )


def guests_block(guests):
    rows = []
    for g in guests or []:
        line = guest_phrase(g)
        if not line:
            continue
        url = (g.get("linkedin_url") or "").strip()
        link = ""
        if url:
            link = (
                f'<p class="stamp dim"><a href="{esc(url)}" style="color:var(--crane);" '
                f'target="_blank" rel="noopener">{esc(g.get("name") or "Guest")} on LinkedIn →</a></p>'
            )
        rows.append(f'<p class="ep-body">{esc(line)}</p>\n{link}')
    if not rows:
        return ""
    return (
        '<div class="sec-label" style="margin-top:40px;">Guests</div>\n'
        + "\n".join(rows)
    )


def _ep_link(ep, event="Related Episode Click"):
    label = extras.ep_label(ep["slug"])
    return (
        f'<a class="path-pill" href="{html.escape(ep["slug"])}.html" data-event="{event}">'
        f'{esc(label)} · {esc(ep.get("display_title") or ep.get("title") or "")} →</a>'
    )


def keep_going(slug, ed, paths, by_slug):
    related = []
    for rel in (ed or {}).get("related") or []:
        ep = by_slug.get(rel)
        if not ep or rel == slug:
            if rel and not ep:
                print(f"WARNING {slug}: unknown related episode {rel}")
            continue
        related.append(ep)
    nxt = []
    for p in paths or []:
        items = p.get("items") or []
        slugs = [it["ep"]["slug"] for it in items]
        if slug not in slugs:
            continue
        i = slugs.index(slug)
        if i + 1 >= len(slugs):
            continue
        nxt.append((p, items[i + 1]["ep"]))
    if not related and not nxt:
        return ""
    parts = ['<div class="sec-label" style="margin-top:40px;">Keep going</div>']
    if related:
        parts.append('<div class="path-pills">' + "".join(_ep_link(ep) for ep in related) + "</div>")
    for p, ep in nxt:
        parts.append(
            f'<p class="stamp dim" style="margin-top:14px;">Next in {esc(p.get("title") or "this path")}</p>'
        )
        parts.append('<div class="path-pills">' + _ep_link(ep) + "</div>")
    return "\n".join(parts)


def newsletter_section():
    return (
        '<section class="block" id="newsletter" data-pagefind-ignore>\n'
        '  <div class="wrap">\n'
        '    <div class="sec-label">Construction Briefs</div>\n'
        f'    {extras.newsletter_block("../")}\n'
        '  </div>\n'
        '</section>'
    )


def social_tags(title: str, description: str, url: str) -> str:
    t, d, u = esc(title), esc(description), esc(url)
    return "\n".join([
        '<meta property="og:type" content="article">',
        f'<meta property="og:site_name" content="Construction Conversations">',
        f'<meta property="og:title" content="{t}">',
        f'<meta property="og:description" content="{d}">',
        f'<meta property="og:url" content="{u}">',
        '<meta name="twitter:card" content="summary">',
        f'<meta name="twitter:title" content="{t}">',
        f'<meta name="twitter:description" content="{d}">',
    ])


def iso_duration(secs: int) -> str:
    secs = max(0, int(secs or 0))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    out = "PT"
    if h:
        out += f"{h}H"
    if m:
        out += f"{m}M"
    if s or not (h or m):
        out += f"{s}S"
    return out


def people_for_jsonld(ep_slug, ed, hand):
    guests = (ed or {}).get("guests") or []
    people = []
    for g in guests:
        name = (g.get("name") or "").strip()
        if not name:
            continue
        person = {"@type": "Person", "name": name}
        if (g.get("title") or "").strip():
            person["jobTitle"] = g["title"].strip()
        if (g.get("firm") or "").strip():
            person["worksFor"] = {"@type": "Organization", "name": g["firm"].strip()}
        url = (g.get("linkedin_url") or "").strip()
        if url:
            person["sameAs"] = url
        people.append(person)
    if people:
        return people
    g = (hand or {}).get("guest") or {}
    if g.get("name"):
        person = {"@type": "Person", "name": g["name"]}
        if g.get("title"):
            person["jobTitle"] = g["title"]
        if g.get("firm"):
            person["worksFor"] = {"@type": "Organization", "name": g["firm"]}
        return [person]
    return []


def jsonld(ep, ed, hand, has_transcript: bool) -> str:
    page = f"{SITE}/episodes/{ep['slug']}.html"
    data = {
        "@context": "https://schema.org",
        "@type": "PodcastEpisode",
        "name": ep["title"],
        "datePublished": ep["date_iso"],
        "description": ep["desc_full"],
        "url": page,
        "associatedMedia": {"@type": "MediaObject", "contentUrl": ep["audio"]},
        "partOfSeries": {
            "@type": "PodcastSeries",
            "name": "Construction Conversations",
            "url": f"{SITE}/",
        },
    }
    if ep.get("num"):
        data["episodeNumber"] = int(ep["num"])
    if ep.get("secs"):
        data["duration"] = iso_duration(ep["secs"])
    if ep.get("duration_iso"):
        data["timeRequired"] = ep["duration_iso"]
    people = people_for_jsonld(ep["slug"], ed, hand)
    if people:
        data["actor"] = people
        data["contributor"] = people
    if has_transcript:
        data["transcript"] = f"{SITE}/episodes/{ep['slug']}.txt"
    return json.dumps(data, indent=2)


def page_parts(ep, ed, hand, lessons, tools, paths, by_slug, segments):
    """HTML snippets for one episode. Empty editorial sections are empty strings."""
    title = document_title(ep, ed)
    pulls = (ed or {}).get("pull_quotes") or []
    summary = (ed or {}).get("summary") or ""
    desc = social_description(lessons, pulls, summary, ep.get("desc") or "")
    url = f"{SITE}/episodes/{ep['slug']}.html"
    return {
        "title": title,
        "h1": episode_title(ep),
        "byline": byline_html(ed, hand),
        "quotes": worth_writing_down(pulls, segments) if pulls else "",
        "description": desc,
        "social": social_tags(title, desc, url),
        "who": who_block(ed, paths),
        "lessons": lesson_cards(ep["slug"], lessons, segments),
        "tools": tools_block(ep["slug"], tools),
        "guests": guests_block((ed or {}).get("guests")),
        "keep": keep_going(ep["slug"], ed, paths, by_slug),
        "newsletter": newsletter_section(),
        "jsonld": jsonld(ep, ed, hand, bool(segments)),
    }


def check_published(editorial, docs):
    """Every pull quote and inline lesson quote must be in the transcript.

    Prints one line per quote. Returns the number that failed. A missing
    transcript is a warning, not a failure, so an offline rebuild of an
    episode that was not cached can still write the page.
    """
    failed = 0
    checked = 0
    for slug, ed in sorted(editorial.items()):
        doc = docs.get(slug)
        segments = segments_for(doc)
        items = []
        for q in ed.get("pull_quotes") or []:
            if (q.get("text") or "").strip():
                items.append(("pull quote", q.get("text")))
        for lesson in ed.get("lessons") or []:
            if isinstance(lesson, dict) and (lesson.get("quote") or "").strip():
                items.append((f"lesson {lesson.get('id') or ''}".strip(), lesson.get("quote")))
        if not items:
            print(f"OK {slug}: no inline quotes to check")
            continue
        if not segments:
            print(f"WARNING {slug}: no transcript in this build, quotes not checked")
            continue
        for kind, text in items:
            checked += 1
            sec = locate_quote(text, segments)
            if sec is None:
                failed += 1
                print(f"INVALID {slug} {kind}: not in the transcript: {text[:90]}")
            else:
                print(f"OK {slug} {kind} sec={sec} ({extras.clock(sec)})")
    print(f"Editorial quotes: {checked - failed} ok, {failed} invalid")
    return failed


def episode_markdown(ep, ed, lessons, segments) -> str:
    lines = [f"# {episode_title(ep)}", ""]
    meta = " · ".join(v for v in (ep.get("date"), ep.get("duration")) if v)
    if meta:
        lines.append(meta)
        lines.append("")
    guests = [guest_phrase(g) for g in ((ed or {}).get("guests") or [])]
    if guests:
        lines.append("Guests: " + "; ".join(guests))
        lines.append("")
    summary = ((ed or {}).get("summary") or "").strip()
    if summary:
        lines.append(summary)
        lines.append("")
    if lessons:
        lines.append("## Lessons")
        lines.append("")
        for kind, lesson in lessons:
            if kind == "deck":
                headline = lesson.get("lesson") or ""
                story = lesson.get("story") or lesson.get("detail") or ""
                quote = lesson.get("quote") or ""
                speaker = lesson.get("guest") or ""
                move = lesson.get("move") or ""
                sec = quote_sec_for_deck(lesson, segments)
            else:
                headline = lesson.get("headline") or ""
                story = lesson.get("what_it_cost") or ""
                quote = lesson.get("quote") or ""
                speaker = lesson.get("quote_speaker") or ""
                move = lesson.get("the_move") or ""
                sec = locate_quote(quote, segments) if quote else None
            lines.append(f"### {headline}")
            lines.append("")
            if story:
                lines.append(story)
                lines.append("")
            if quote:
                stamp = f", {extras.clock(sec)}" if sec is not None else ""
                who = f" {speaker}{stamp}" if speaker or stamp else ""
                lines.append(f"> {quote}")
                if who.strip():
                    lines.append(f"> {who.strip()}")
                lines.append("")
            if move:
                lines.append(f"The move: {move}")
                lines.append("")
    txt = f"{SITE}/episodes/{ep['slug']}.txt"
    page = f"{SITE}/episodes/{ep['slug']}.html"
    lines.append("## Transcript")
    lines.append("")
    lines.append(f"Full transcript: {txt}")
    lines.append(f"Episode page: {page}")
    lines.append("")
    return "\n".join(lines)


def llms_text(episodes, editorial, hand_chapters, has_txt) -> str:
    lines = [
        "# Construction Conversations",
        "",
        "> Field lessons from the people who build. Each episode page has the lessons, the chapters, and a full transcript.",
        "",
        f"- [Start here]({SITE}/start.html): listening paths",
        f"- [The 50 lessons]({SITE}/lessons.html): what it cost, the quote, and the move",
        f"- [Tools]({SITE}/tools.html): tools mentioned on the show",
        "",
        "## Episodes",
        "",
    ]
    for ep in episodes:
        ed = editorial.get(ep["slug"]) or {}
        guests = [guest_phrase(g) for g in (ed.get("guests") or [])]
        if not guests:
            g = ((hand_chapters.get(ep["slug"]) or {}).get("guest") or {})
            if g.get("name"):
                guests = [guest_phrase(g)]
        guest = "; ".join(guests)
        page = f"{SITE}/episodes/{ep['slug']}.html"
        title = ep.get("title") or ep["slug"]
        bit = f"- [{title}]({page})"
        if guest:
            bit += f": {guest}."
        if has_txt.get(ep["slug"]):
            bit += f" Transcript: {SITE}/episodes/{ep['slug']}.txt"
        lines.append(bit)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Drafts. Called only from `build.py --draft`. Never from the site build.

def draft_env():
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    model = (os.environ.get("DRAFT_MODEL") or "").strip()
    missing = []
    if not key:
        missing.append("ANTHROPIC_API_KEY")
    if not model:
        missing.append("DRAFT_MODEL")
    if missing:
        joined = " and ".join(missing)
        raise SystemExit(
            f"ERROR: --draft needs {joined} set in the environment. "
            "The site build does not call the API. Export both and run the command again."
        )
    return key, model


def anthropic_complete(prompt: str, key: str, model: str) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"ERROR: Anthropic API returned HTTP {e.code}. {detail}") from e
    except Exception as e:
        raise SystemExit(f"ERROR: Anthropic API request failed: {e}") from e
    parts = []
    for block in payload.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    text = "\n".join(parts).strip()
    if not text:
        raise SystemExit("ERROR: Anthropic API returned no text.")
    return text


def parse_model_json(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"ERROR: draft response was not JSON ({e}).") from e
    if not isinstance(data, dict):
        raise SystemExit("ERROR: draft response JSON was not an object.")
    return data


def apply_model_draft(data: dict, segments) -> tuple:
    """Keep quotes that match the transcript and set sec from the match.

    Returns (draft_dict, log_lines). Invented quotes are dropped and logged.
    """
    log = []

    def keep_quote(text, speaker):
        sec = locate_quote(text or "", segments)
        if sec is None:
            shown = (text or "").strip().replace("\n", " ")
            log.append(f"DROPPED quote not in transcript: {shown[:140]}")
            return None
        log.append(f"KEPT quote sec={sec} ({extras.clock(sec)}): {(text or '')[:80]}")
        return {"text": text.strip(), "speaker": (speaker or "").strip(), "sec": sec}

    lessons = []
    for lesson in data.get("lessons") or []:
        if isinstance(lesson, int) or (isinstance(lesson, str) and str(lesson).isdigit()):
            lessons.append(int(lesson))
            log.append(f"KEPT lesson reference {int(lesson)}")
            continue
        if not isinstance(lesson, dict):
            continue
        quote = keep_quote(lesson.get("quote") or "", lesson.get("quote_speaker") or "")
        if quote is None:
            log.append(f"DROPPED lesson {lesson.get('id') or lesson.get('headline') or ''} (quote did not match)")
            continue
        lessons.append({
            "id": str(lesson.get("id") or f"lesson-{len(lessons) + 1}"),
            "headline": (lesson.get("headline") or "").strip(),
            "what_it_cost": (lesson.get("what_it_cost") or "").strip(),
            "quote": quote["text"],
            "quote_speaker": quote["speaker"],
            "quote_sec": quote["sec"],
            "the_move": (lesson.get("the_move") or "").strip(),
            "roles": [r for r in (lesson.get("roles") or []) if r in ROLES],
        })
    pulls = []
    for q in data.get("pull_quotes") or []:
        if not isinstance(q, dict):
            continue
        kept = keep_quote(q.get("text") or "", q.get("speaker") or "")
        if kept:
            pulls.append(kept)
    draft = {
        "guests": data.get("guests") or [],
        "summary": (data.get("summary") or "").strip(),
        "roles": [r for r in (data.get("roles") or []) if r in ROLES],
        "paths": [p for p in (data.get("paths") or []) if p],
        "tools": [t for t in (data.get("tools") or []) if t],
        "related": [r for r in (data.get("related") or []) if r],
        "lessons": lessons,
        "pull_quotes": pulls,
    }
    return draft, log


def draft_prompt(ep, segments, chapters, paths, lesson_numbers) -> str:
    lines = []
    for seg in segments:
        sec = int(seg.get("start_sec") or 0)
        lines.append(f"[{extras.clock(sec)}] {seg.get('text') or ''}")
    ch_lines = []
    for c in chapters or []:
        if "start_sec" in c:
            ch_lines.append(f"{extras.clock(int(c['start_sec']))} {c.get('title') or ''}")
        else:
            ch_lines.append(f"{c.get('time') or ''} {c.get('title') or ''}")
    path_lines = [f"{p['slug']}: {p.get('title') or ''}" for p in paths or []]
    known = ", ".join(str(n) for n in lesson_numbers) or "none"
    return f"""You are drafting show notes for Construction Conversations, a podcast for people who build.

Episode: {ep.get('title')}
Slug: {ep.get('slug')}
Description: {ep.get('desc_full') or ''}

Chapters:
{chr(10).join(ch_lines) or '(none)'}

Transcript:
{chr(10).join(lines)}

Lessons already in the field deck for this episode, by number: {known}.
Reference those by number. Do not rewrite them.

Return one JSON object and nothing else. Schema:
{{
  "summary": "2 or 3 sentences on who this episode is for and what they walk away with",
  "roles": ["Super" or "PM" or "Exec" or "Founder"],
  "paths": ["path slug from the list below"],
  "tools": ["tool slug, lowercase hyphenated name such as document-crunch"],
  "related": ["episode slug such as ep-045"],
  "lessons": [
    {{
      "id": "short-slug",
      "headline": "one sentence a superintendent could repeat",
      "what_it_cost": "the cost the guest actually described",
      "quote": "verbatim words from the transcript",
      "quote_speaker": "the person who said it",
      "quote_sec": 0,
      "the_move": "what to do next time",
      "roles": ["Super"]
    }}
  ],
  "pull_quotes": [{{"text": "verbatim", "speaker": "name", "sec": 0}}]
}}

Rules:
- 2 to 4 lessons. 3 pull quotes.
- Every quote is copied from the transcript. Do not clean up, paraphrase, or stitch lines that are not adjacent.
- quote_sec and sec are hints only. They will be replaced from the transcript.
- Paths, pick from: {', '.join(p['slug'] for p in paths or [])}
- No em dashes.
"""


def write_draft_yaml(slug: str, draft: dict) -> Path:
    DRAFTS.mkdir(parents=True, exist_ok=True)
    path = DRAFTS / f"{slug}.yml"
    header = (
        "# Draft. Not published. Move the file to content/episodes/ and edit it before it goes on the site.\n"
    )
    body = yaml.safe_dump(draft, sort_keys=False, allow_unicode=True, width=88)
    path.write_text(header + body, encoding="utf-8")
    return path


def run_draft(argv, complete=None):
    """`python3 build.py --draft ep-069` or `--draft all`.

    `complete` is the HTTP call. Tests pass a fake. The real call reads
    ANTHROPIC_API_KEY and DRAFT_MODEL and is not used by the site build.
    """
    if complete is None:
        key, model = draft_env()

        def complete(prompt):
            return anthropic_complete(prompt, key, model)

    import build

    slugs = []
    if "--draft" in argv:
        i = argv.index("--draft")
        for arg in argv[i + 1:]:
            if arg.startswith("-"):
                break
            slugs.append(arg)
    if not slugs:
        raise SystemExit(
            "ERROR: --draft needs one or more episode slugs, or all. "
            "Example: python3 build.py --draft ep-069"
        )
    offline = "--offline" in argv
    if offline and build.FEED_CACHE.exists():
        xml_text = build.FEED_CACHE.read_text(encoding="utf-8")
    elif offline:
        raise SystemExit("ERROR: --draft --offline needs a cached feed.xml.")
    else:
        xml_text = build.fetch_feed()
    episodes, _artwork = build.parse_episodes(xml_text)
    by_slug = {e["slug"]: e for e in episodes}
    published = load_editorial()
    if slugs == ["all"]:
        slugs = [e["slug"] for e in episodes if e["slug"] not in published]
        if not slugs:
            print("No episodes without a YAML file.")
            return
        print(f"Drafting {len(slugs)} episodes with no YAML file")
    chapters = extras.load_chapters()
    _first, paths = build.load_paths(episodes)
    lessons = extras.load_lessons()
    _by_n, by_ep = index_lessons(lessons)
    for slug in slugs:
        ep = by_slug.get(slug)
        if not ep:
            print(f"ERROR: {slug} is not in the feed")
            continue
        if slug in published:
            print(f"{slug}: content/episodes/{slug}.yml already exists, skipped")
            continue
        doc, warnings, _h, _d = __import__("transcripts").prepare_episode(
            ep, chapters.get(slug), offline, ROOT
        )
        for w in warnings:
            print(f"WARNING {w}")
        segments = segments_for(doc)
        if not segments:
            print(f"ERROR: {slug} has no transcript, draft not written")
            continue
        hand = chapters.get(slug) or {}
        ch = hand.get("chapters") or [
            {"start_sec": c["start_sec"], "title": c.get("title") or ""}
            for c in (doc.get("chapters") or [])
        ]
        known = [l["n"] for l in by_ep.get(slug) or []]
        raw = complete(draft_prompt(ep, segments, ch, paths, known))
        data = parse_model_json(raw)
        draft, log = apply_model_draft(data, segments)
        for line in log:
            print(f"{slug}: {line}")
        path = write_draft_yaml(slug, draft)
        print(f"Wrote {path.relative_to(ROOT)}")
