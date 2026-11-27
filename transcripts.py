"""Chapters and transcripts from the Podbean feed.

build.py calls build_episode_docs() for every item. For each episode we
download the Podcasting 2.0 chapters JSON and transcript (WebVTT or SRT),
merge caption cues into paragraphs, and write:

  data/episodes/<slug>.json   normalized record (build output)
  site/episodes/<slug>.txt    plain-text transcript with [mm:ss] stamps

Raw downloads are cached in cache/media/<slug>.json so the next build
reuses them when the feed URL has not changed. A failure for one episode
is logged and returned as empty chapters or an empty transcript; it does
not raise.

Stdlib only.
"""

import html
import json
import math
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MIN_SEC = 20
MAX_SEC = 45

# Tokens whose trailing period is not the end of a sentence.
ABBREV = {
    "mr", "mrs", "ms", "dr", "jr", "sr", "st", "vs", "etc", "inc", "ltd",
    "co", "fig", "vol", "gen", "col", "sgt", "rep", "sen", "gov", "prof",
    "approx", "dept", "est", "ave", "blvd", "rd", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "eg", "ie",
    "am", "pm", "mt", "ft",
}

TS_RE = re.compile(
    r"((?:\d{1,3}:)?\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d{1,3}:)?\d{2}:\d{2}[.,]\d{1,3})"
)
TAG_RE = re.compile(r"<[^>]+>")
INITIALS_RE = re.compile(r"(?:[A-Za-z]+\.){2,}")


def nodash(s: str) -> str:
    return (s or "").replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").replace("–", ", ")


def t2s(t: str) -> int:
    s = 0
    for p in str(t).split(":"):
        s = s * 60 + int(p)
    return s


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cc-site-builder"})
    err = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return resp.read()
        except Exception as e:
            err = e
            if attempt == 0:
                time.sleep(1.2)
    raise err


def short_err(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    msg = str(e).strip().split("\n", 1)[0]
    return msg[:180] or e.__class__.__name__


def parse_ts(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        return 0.0
    return int(h) * 3600 + int(m) * 60 + float(s)


def clean_cue(text: str) -> str:
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = nodash(text)
    return re.sub(r"\s+", " ", text).strip()


# Whole-cue captions that are not speech. A long "[Music]" bed should not
# become a paragraph, and it should not glue the sentences on either side.
NONSPEECH_RE = re.compile(
    r"^(?:[\[\(]?\s*(?:music|applause|laughter|laughs|laughing|inaudible|silence|blank audio|noise)\s*[\]\)]?\.?|♪+|♫+)$",
    re.I,
)


def parse_cues(text: str) -> list:
    """WebVTT and SRT, including cue ids and timestamp settings."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    cues = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        m = TS_RE.search(line)
        if not m and line and not line.startswith(("NOTE", "STYLE", "WEBVTT")) and i + 1 < n:
            m2 = TS_RE.search(lines[i + 1].strip())
            if m2:
                i += 1
                line = lines[i].strip()
                m = m2
        if not m:
            i += 1
            continue
        start, end = parse_ts(m.group(1)), parse_ts(m.group(2))
        i += 1
        buf = []
        while i < n and lines[i].strip() != "":
            buf.append(lines[i].strip())
            i += 1
        raw = clean_cue(" ".join(buf))
        if not raw or NONSPEECH_RE.match(raw):
            continue
        if cues and cues[-1]["text"] == raw:
            cues[-1]["end"] = max(cues[-1]["end"], end)
            continue
        cues.append({"start": start, "end": max(end, start), "text": raw})
    return cues


def parse_chapter_list(obj) -> list:
    if isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict):
        items = obj.get("chapters") or []
    else:
        return []
    out = []
    for c in items:
        if not isinstance(c, dict):
            continue
        title = nodash(str(c.get("title") or "")).strip()
        if not title:
            continue
        raw = c.get("startTime", c.get("start_time", 0))
        try:
            start = int(round(float(raw)))
        except (TypeError, ValueError):
            continue
        if start < 0:
            continue
        out.append({"start_sec": start, "title": title})
    out.sort(key=lambda c: (c["start_sec"], c["title"]))
    deduped = []
    for c in out:
        if deduped and deduped[-1]["start_sec"] == c["start_sec"]:
            continue
        deduped.append(c)
    return deduped


def _ends_sentence(word: str, nxt: str) -> bool:
    core = word
    while core and core[-1] in "\"'”’)\\]":
        core = core[:-1]
    if not core or core[-1] not in ".!?":
        return False
    if core.endswith("...") or core.endswith("…"):
        return bool(nxt) and nxt[0].isupper()
    if INITIALS_RE.fullmatch(core):
        return False
    if core[-1] in "!?":
        return True
    body = core.rstrip(".")
    if re.fullmatch(r"[A-Za-z]", body):
        return False
    # "2026." and "exhibit 12." end a sentence. "2." followed by "0" is a split decimal.
    if re.fullmatch(r"\d+", body):
        nxt_core = (nxt or "").rstrip(".,")
        if nxt_core and re.fullmatch(r"\d+", nxt_core):
            return False
        return True
    if body.lower() in ABBREV:
        return False
    return True


def _split_overlong(sent: dict) -> list:
    """A caption run with no period can last over a minute.

    Break that run at commas (then word boundaries) so the pieces can be
    packed back into the 20-45s range. Sentences that already fit are left
    whole, so a real sentence is never cut.
    """
    dur = sent["end"] - sent["start"]
    if dur <= MAX_SEC:
        return [sent]
    words = sent["text"].split()
    if len(words) < 12:
        return [sent]
    span = dur / len(words)

    def clause_cut(start_i, i):
        """Index where the next piece starts, or None.

        Commas stay with the piece they close. A conjunction starts the
        next piece, so a paragraph does not end on "and".
        """
        w = words[i]
        if w.endswith((",", ";", ":")):
            return i + 1
        bare = w.strip(",.;:").lower()
        if bare in {"and", "but", "so", "because", "or"} and i > start_i:
            return i
        return None

    def cut_after(start_i, limit):
        # Latest clause break that still lands near the 45s cap.
        # No break means the caller keeps the rest intact rather than
        # cutting a phrase in half.
        window = min(len(words) - 1, limit + 8)
        for i in range(window, start_i, -1):
            chosen = clause_cut(start_i, i)
            if not chosen or chosen <= start_i:
                continue
            end_i = chosen - 1
            if (end_i + 1 - start_i) * span <= MAX_SEC + 6:
                return chosen
        return None

    pieces = []
    start_i = 0
    while start_i < len(words):
        remain_dur = (len(words) - start_i) * span
        if remain_dur <= MAX_SEC:
            pieces.append((start_i, len(words)))
            break
        limit = start_i
        for i in range(start_i, len(words)):
            if (i + 1 - start_i) * span <= MAX_SEC or i == start_i:
                limit = i
            else:
                break
        chosen = cut_after(start_i, limit)
        if not chosen or chosen <= start_i:
            pieces.append((start_i, len(words)))
            break
        pieces.append((start_i, chosen))
        start_i = chosen
    out = []
    for n, (a, b) in enumerate(pieces):
        out.append({
            "start": sent["start"] + a * span,
            "end": sent["end"] if b == len(words) else sent["start"] + b * span,
            "text": " ".join(words[a:b]),
        })
    if out:
        out[0]["start"] = sent["start"]
        out[-1]["end"] = sent["end"]
    return out or [sent]


def sentences_from_cues(cues: list) -> list:
    words = []
    for cue in cues:
        tokens = cue["text"].split()
        if not tokens:
            continue
        span = max(cue["end"] - cue["start"], 0.001)
        n = len(tokens)
        for i, tok in enumerate(tokens):
            words.append((
                cue["start"] + span * i / n,
                cue["start"] + span * (i + 1) / n,
                tok,
            ))
    out = []
    buf = []
    start = end = None
    for i, (t0, t1, tok) in enumerate(words):
        nxt = words[i + 1][2] if i + 1 < len(words) else ""
        if start is None:
            start = t0
        buf.append(tok)
        end = t1
        if _ends_sentence(tok, nxt):
            out.append({"start": start, "end": end, "text": " ".join(buf)})
            buf = []
            start = end = None
    if buf:
        out.append({"start": start, "end": end, "text": " ".join(buf)})
    return out


def _hits_boundary(para_start: float, sent_start: float, boundaries: list) -> bool:
    for b in boundaries:
        if para_start < b <= sent_start + 1e-6:
            return True
    return False


def merge_paragraphs(cues: list, boundaries: list) -> list:
    """Pack sentences into ~20-45s paragraphs.

    Break before a sentence that would cross a chapter boundary, and before
    a sentence that would push a paragraph already at least 20s past 45s.
    A sentence is never split, so a single long sentence can run past 45s,
    and a chapter break can leave a shorter paragraph.
    """
    bounds = sorted({int(b) for b in boundaries if b and int(b) > 0})
    sents = []
    for sent in sentences_from_cues(cues):
        sents.extend(_split_overlong(sent))
    groups = []
    cur = []

    def flush():
        if not cur:
            return
        text = re.sub(r"\s+", " ", " ".join(s["text"] for s in cur)).strip()
        if text:
            groups.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": text})

    for sent in sents:
        if cur and _hits_boundary(cur[0]["start"], sent["start"], bounds):
            flush()
            cur = []
        if not cur:
            cur = [sent]
            continue
        cur_dur = cur[-1]["end"] - cur[0]["start"]
        new_dur = sent["end"] - cur[0]["start"]
        incoming = sent["end"] - sent["start"]
        # Don't glue a short opener onto a chunk that is already its own paragraph.
        if new_dur > MAX_SEC and (cur_dur >= MIN_SEC or incoming >= MIN_SEC):
            flush()
            cur = [sent]
        else:
            cur.append(sent)
    flush()
    return _absorb_short(_number_paragraphs(groups), bounds)


def _absorb_short(paras: list, bounds: list) -> list:
    """Fold a tiny fragment into the previous paragraph when it stays readable.

    Chapter boundaries stay put, so a short chapter is not swallowed.
    """
    if len(paras) < 2:
        return paras
    out = [dict(paras[0])]
    for raw in paras[1:]:
        p = dict(raw)
        prev = out[-1]
        dur = p["end_sec"] - p["start_sec"]
        crosses = any(prev["start_sec"] < b <= p["start_sec"] for b in bounds)
        combined = p["end_sec"] - prev["start_sec"]
        if dur < 12 and not crosses and combined <= MAX_SEC + 4:
            prev["end_sec"] = p["end_sec"]
            prev["text"] = (prev["text"].rstrip() + " " + p["text"]).strip()
        else:
            out.append(p)
    return out


def _number_paragraphs(groups: list) -> list:
    paras = []
    for g in groups:
        start = int(math.floor(g["start"] + 1e-6))
        end = int(math.ceil(g["end"] - 1e-6))
        if end <= start:
            end = start + 1
        paras.append({"start_sec": start, "end_sec": end, "text": g["text"]})
    for i in range(1, len(paras)):
        prev, cur = paras[i - 1], paras[i]
        if cur["start_sec"] < prev["end_sec"]:
            prev["end_sec"] = cur["start_sec"]
        if prev["end_sec"] <= prev["start_sec"]:
            prev["end_sec"] = prev["start_sec"] + 1
            cur["start_sec"] = max(cur["start_sec"], prev["end_sec"])
        if cur["end_sec"] <= cur["start_sec"]:
            cur["end_sec"] = cur["start_sec"] + 1
    # Close gaps of a couple of seconds so a timestamp between two
    # paragraphs still lands in one of them.
    for i in range(len(paras) - 1):
        gap = paras[i + 1]["start_sec"] - paras[i]["end_sec"]
        if 0 < gap <= 2:
            paras[i]["end_sec"] = paras[i + 1]["start_sec"]
    return paras


def hand_starts(hand) -> list:
    out = []
    for c in (hand or {}).get("chapters") or []:
        raw = c.get("time")
        if not raw:
            continue
        try:
            out.append(t2s(raw))
        except (TypeError, ValueError):
            continue
    return out


def skeleton(ep: dict) -> dict:
    num = int(ep["num"]) if ep.get("num") else None
    return {
        "slug": ep["slug"],
        "number": num,
        "type": "episode" if ep.get("num") else "roundtable",
        "title": ep.get("title") or "",
        "date": ep.get("date_iso") or "",
        "duration_sec": int(ep.get("secs") or 0),
        "audio_url": ep.get("audio") or "",
        "podbean_url": ep.get("link") or "",
        "chapters": [],
        "transcript": [],
    }


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(path: Path, cache: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def prepare_episode(ep: dict, hand, offline: bool, root: Path):
    """Return (doc, warnings, cache_hits, downloads)."""
    warnings = []
    hits = downloads = 0
    slug = ep["slug"]
    cache_path = root / "cache" / "media" / f"{slug}.json"
    cache = _load_cache(cache_path)
    dirty = False

    chapters = []
    ch_url = ep.get("chapters_url") or ""
    if ch_url and cache.get("chapters_url") == ch_url and isinstance(cache.get("chapters"), list):
        chapters = cache["chapters"]
        hits += 1
    elif not ch_url:
        warnings.append(f"{slug}: no podcast:chapters url")
    elif offline:
        warnings.append(f"{slug}: chapters not in cache (offline)")
    else:
        try:
            payload = json.loads(http_get(ch_url).decode("utf-8", "replace"))
            chapters = parse_chapter_list(payload)
            cache["chapters_url"] = ch_url
            cache["chapters"] = chapters
            dirty = True
            downloads += 1
            if not chapters:
                warnings.append(f"{slug}: chapters file had no entries")
        except Exception as e:
            warnings.append(f"{slug}: chapters fetch failed ({short_err(e)})")

    transcript_text = None
    tr_url = ep.get("transcript_url") or ""
    tr_type = ep.get("transcript_type") or ""
    if tr_url and cache.get("transcript_url") == tr_url and isinstance(cache.get("transcript"), str):
        transcript_text = cache["transcript"]
        hits += 1
    elif not tr_url:
        warnings.append(f"{slug}: no podcast:transcript url")
    elif offline:
        warnings.append(f"{slug}: transcript not in cache (offline)")
    else:
        try:
            transcript_text = http_get(tr_url).decode("utf-8", "replace")
            cache["transcript_url"] = tr_url
            cache["transcript_type"] = tr_type
            cache["transcript"] = transcript_text
            dirty = True
            downloads += 1
        except Exception as e:
            warnings.append(f"{slug}: transcript fetch failed ({short_err(e)})")

    if dirty:
        try:
            _save_cache(cache_path, cache)
        except Exception as e:
            warnings.append(f"{slug}: could not write media cache ({short_err(e)})")

    doc = skeleton(ep)
    doc["chapters"] = chapters
    if transcript_text:
        try:
            cues = parse_cues(transcript_text)
            if not cues:
                warnings.append(f"{slug}: transcript parsed to no cues")
            else:
                bounds = [c["start_sec"] for c in chapters] + hand_starts(hand)
                doc["transcript"] = merge_paragraphs(cues, bounds)
                doc["cues"] = [
                    {
                        "start_sec": int(math.floor(c["start"] + 1e-6)),
                        "text": (c.get("text") or "").strip(),
                    }
                    for c in cues
                    if (c.get("text") or "").strip()
                ]
                if not doc["transcript"]:
                    warnings.append(f"{slug}: transcript produced no paragraphs")
        except Exception as e:
            warnings.append(f"{slug}: transcript parse failed ({short_err(e)})")
            doc["transcript"] = []
    return doc, warnings, hits, downloads


def write_txt(path: Path, paragraphs: list):
    chunks = []
    for p in paragraphs:
        sec = int(p["start_sec"])
        stamp = f"{sec // 60:02d}:{sec % 60:02d}"
        chunks.append(f"[{stamp}] {p['text']}")
    path.write_text("\n\n".join(chunks) + "\n", encoding="utf-8")


def build_episode_docs(episodes, hand_by_slug, offline: bool, root: Path) -> dict:
    """Fetch, normalize, and write every episode. Never raises for one item."""
    hand_by_slug = hand_by_slug or {}
    results = {}
    warnings = []
    hits = downloads = 0

    def run(ep):
        try:
            return prepare_episode(ep, hand_by_slug.get(ep["slug"]), offline, root)
        except Exception as e:
            return skeleton(ep), [f"{ep['slug']}: pipeline failed ({short_err(e)})"], 0, 0

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(run, ep): ep for ep in episodes}
        for fut in as_completed(futures):
            ep = futures[fut]
            try:
                doc, warns, h, d = fut.result()
            except Exception as e:
                doc, warns, h, d = skeleton(ep), [f"{ep['slug']}: pipeline failed ({short_err(e)})"], 0, 0
            results[ep["slug"]] = doc
            warnings.extend(warns)
            hits += h
            downloads += d

    out_dir = root / "data" / "episodes"
    txt_dir = root / "site" / "episodes"
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    n_para = n_with = bad_end = max_dur = 0
    ordered = {}
    for ep in episodes:
        doc = results.get(ep["slug"]) or skeleton(ep)
        ordered[ep["slug"]] = doc
        (out_dir / f"{ep['slug']}.json").write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        txt_path = txt_dir / f"{ep['slug']}.txt"
        if doc["transcript"]:
            write_txt(txt_path, doc["transcript"])
            n_with += 1
            for p in doc["transcript"]:
                n_para += 1
                max_dur = max(max_dur, int(p["end_sec"]) - int(p["start_sec"]))
                tail = p["text"].rstrip("\"'”’) ")
                if not tail or tail[-1] not in ".!?,;:":
                    bad_end += 1
        elif txt_path.exists():
            txt_path.unlink()

    for w in warnings:
        print(f"WARNING {w}")
    mode = "offline" if offline else "network"
    print(f"Feed media ({mode}): {hits} cache hits, {downloads} downloads")
    print(
        f"Transcript paragraphs: {n_para} across {n_with} episodes, "
        f"longest {max_dur}s, {bad_end} not ending on a sentence"
    )
    return ordered
