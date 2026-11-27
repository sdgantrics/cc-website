# Construction Conversations Website

Static replacement for the Lovable site at constructionconversations.com.
No framework, no build service, no monthly fee — just HTML/CSS/JS generated
from the Podbean RSS feed.

## How it works

- `templates/` — the two page templates (edit design/copy here)
- `site/` — the deployable output (this folder is what gets hosted)
- `build.py` — fetches the Podbean feed and regenerates `site/index.html`
  and `site/episodes.html` (episode cards, counts, cover art)
- `transcripts.py` — during that same build, downloads each episode's
  chapters and transcript (see Transcripts and chapters)
- Episode slugs: `ep-054` when the title starts with a number. Unnumbered
  specials (Reviewed as Noted) use `ran-YYYY-MM-DD` from the publish date,
  not feed position, so a new special does not renumber older ones. Two
  specials on the same date get a `-2`, `-3` suffix from a guid sort.
  Legacy `episodes/special-N.html` URLs redirect via `data/special_redirects.json`.

## What's on the site (audience-first, Aug 2026)

| Page | Source of truth | Edit how |
|---|---|---|
| Start Here paths (`start.html`, `start/*`) | `paths.json` | edit JSON, rebuild |
| Episode chapters, quotes, guest line, mentions | `data/chapters/<slug>.json` for quotes, mentions, the guest line, and any chapter list you write. Feed chapters and the full transcript fill in at build time. | edit the JSON to override chapters or add quotes; see Transcripts and chapters |
| Articles (`articles.html`, `articles/*`) | `articles/<slug>.md` (front matter + HTML body) | add a file per Recap / Insider Take / Debrief |
| Tools database (`tools.html`, `assets/tools.csv`) | `data/tools.json` | regenerate from the Notion Episode Insights DB (Tools Mentioned + Mention Source); only Practitioner mentions are published |
| The 50 lessons (`lessons.html`, `assets/cc-50-expensive-lessons.pdf`) | `data/lessons.json` | edit JSON, rebuild, re-print the PDF (headless Chrome on lessons.html) |
| Reviews (`reviews.html`) | Apple RSS at build time, cached in `data/reviews.json` | add non-Apple reviews by hand to the cache with `"source": "LinkedIn"` |
| Join In (`join.html`) | `data/upcoming.json` + form links in `templates/join.html` | paste Tally form URLs over the mailto placeholders |
| From the Field (`stories.html`) | `stories/<slug>.md` | one file per approved listener story |

Nav and footer are single-sourced in `extras.py` (`NAV_ITEMS`, `FOOT_ITEMS`). The newsletter block on every page is `extras.newsletter_block()`.

## Transcripts and chapters

Every episode page gets a clickable chapter list and a collapsed full transcript from the feed, on every build. A new Podbean episode picks both up with no hand step.

`build.py` reads two Podcasting 2.0 tags on each item:

- `<podcast:chapters>` is a JSON list of `{startTime, title}`
- `<podcast:transcript>` is `text/vtt` on most episodes and `application/srt` on episodes 1 through 6. Neither file has speaker labels.

`transcripts.py` parses the cues and merges them into paragraphs of about 20 to 45 seconds. A paragraph ends at a sentence, and it also breaks when a chapter starts, so a heading never cuts a sentence in half. A caption stretch with no period, which some auto-transcripts run for a minute, breaks at a comma or before "and", "but", or "so" so the paragraph stays in that range. If the caption has no clause break, the sentence stays whole. The normalized record is `data/episodes/<slug>.json`:

- `slug`, `number` (null for an unnumbered show), `type` (`episode` for a numbered show, `roundtable` for Reviewed as Noted)
- `title`, `date`, `duration_sec`
- `audio_url`, the enclosure URL with the `cohst.app` prefix left exactly as the feed publishes it
- `podbean_url`
- `chapters[]` of `{start_sec, title}` from the feed
- `transcript[]` of `{start_sec, end_sec, text}`

Those JSON files are build output and are not committed. The feed is the source of truth, and both CI and the daily Pages workflow run `python3 build.py`, so committing them would only copy the feed and go stale. Raw chapter and caption downloads live in `cache/media/` (also not committed). A later local build reuses a file when its feed URL has not changed, instead of downloading it again. If one episode fails to download, the build logs a warning and still writes that page, just without the missing section.

A hand-written `data/chapters/<slug>.json` that includes `chapters` keeps that list on the page, and the transcript is grouped under those headings. Quotes, mentions, and the guest line still come only from that file. Feed chapters are used when the hand-written file has no chapter list. Paragraph breaks follow both the feed chapters and those hand-written times, so the headings line up with the text.

The same build writes `site/episodes/<slug>.txt`, a plain-text transcript with `[mm:ss]` stamps. It is published with the site and is not stored in git.

### Run the build locally

```bash
python3 build.py                 # fetch the feed; reuse cache/media when the URL is unchanged
python3 build.py --offline       # feed.xml and cache/media only; nothing is downloaded
python3 -m http.server 8741 --directory site
```

The first build needs network access to Podbean. `--offline` still renders an episode that is missing from `cache/media/`; that page just has no chapters or transcript from the feed.

## Search

Search covers episode pages, `lessons.html`, `tools.html`, and article pages. Nav, footers, the newsletter, sponsor blocks, and audio players are left out of the index with `data-pagefind-body` and `data-pagefind-ignore`. Filters (type, role, path, guest, year) and the title, guest, and date are `data-pagefind-filter` / `data-pagefind-meta`. Lesson cards and chapter titles use `data-pagefind-weight` so they rank above a passing line in a transcript.

Pagefind runs after `build.py`. It writes a fragmented index under `site/pagefind/` (gitignored). The browser does not load that index until someone uses a search box, and a query fetches only the fragments for its words, not one JSON file of the whole archive.

Each caption cue is its own result, anchored as `c-SECONDS` and rewritten to `episodes/<slug>.html#t=SECONDS`. The episode page already seeks and opens the transcript on that hash, so playback starts at the caption that matched rather than at the start of the merged paragraph. "Play from here" opens that URL. The cues are in the HTML for Pagefind and are not shown; the page still reads as paragraphs.

Pagefind 1.6 has no synonym dictionary, so construction shorthand is expanded in `site/assets/js/search.js` before the query is sent. That is more reliable than stuffing alias words into the HTML: extra tokens in the index would dilute `data-pagefind-weight`, and an unquoted short query is a prefix match (`co` would hit "construction"). Abbreviations such as CO, RFI, GC, and super are rewritten to the full phrase (`change order`, `request for information`, `general contractor`, `superintendent`) and the short form is added as an exact-token search. BIM, VDC, T&M, and pay app are searched as both the short form and the full phrase.

### Run search locally

```bash
python3 build.py                 # or: python3 build.py --offline
npx -y pagefind@1.6.0 --site site --force-language en
python3 -m http.server 8741 --directory site
```

Open `http://127.0.0.1:8741/search.html`. `?q=` prefills the box on that page and on `episodes.html`. The same Pagefind step is in `.github/workflows/ci.yml` and `deploy.yml`, pinned to `pagefind@1.6.0`.

## Refresh episodes

```bash
python3 build.py
```

Run after each new episode publishes (or ask Claude to "rebuild the CC
website"). `--offline` rebuilds from the cached `feed.xml` without fetching.

## Preview locally

```bash
python3 -m http.server 8741 --directory site
```

## Deploying

Any static host serves the `site/` folder as-is. Free options that support
the custom domain constructionconversations.com: GitHub Pages, Cloudflare
Pages, Netlify. A GitHub Action can run `build.py` on a daily schedule so
new episodes appear without manual rebuilds.

## Brand

Built on the **Site Gothic** design system (Brand System V1, Aug 2026 —
claude.ai/code/artifact/8c9e82a2-3bd3-436c-99c6-223c47ea2df1):

- Colors: Pitch #0B0F12 (ground), Crane #F68B4F (the one orange moment),
  Chalk #FCFCFC (type), Steel #3A444C (borders), greys #B7BBC0/#9AA1AA
- Type: Anton (display, all caps, lh .88–.94), Archivo (text),
  DM Mono (stamps/metadata, uppercase, tracked)
- Grit kit: hazard stripe (45°, 13px bars), stamp tags (mono on Crane),
  stud lines (22px rhythm at ~5% white), duotone photos (Pitch + Crane)
- Square corners everywhere; no gradients, glows, or shadows;
  never Construction Briefs orange #E85D2C

Known gap: no real headshot of Stephen exists in the asset library — the
brand kit's "Stephen Poppe - Headshot 2084px.jpg" and the logo package's
"profile photo-01.jpg" both contain the badge, not a photo. His host card
uses the badge avatar until a real photo is dropped into
site/assets/img/stephen.jpg.
