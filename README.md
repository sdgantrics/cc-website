# Construction Conversations Website

Static replacement for the Lovable site at constructionconversations.com.
No framework, no build service, no monthly fee — just HTML/CSS/JS generated
from the Podbean RSS feed.

## How it works

- `templates/` — the two page templates (edit design/copy here)
- `site/` — the deployable output (this folder is what gets hosted)
- `build.py` — fetches the Podbean feed and regenerates `site/index.html`
  and `site/episodes.html` (episode cards, counts, cover art)

## What's on the site (audience-first, Aug 2026)

| Page | Source of truth | Edit how |
|---|---|---|
| Start Here paths (`start.html`, `start/*`) | `paths.json` | edit JSON, rebuild |
| Episode chapters, quotes, guest line, mentions | `data/chapters/<slug>.json` | one JSON per episode (23 so far); add more from transcripts |
| Articles (`articles.html`, `articles/*`) | `articles/<slug>.md` (front matter + HTML body) | add a file per Recap / Insider Take / Debrief |
| Tools database (`tools.html`, `assets/tools.csv`) | `data/tools.json` | regenerate from the Notion Episode Insights DB (Tools Mentioned + Mention Source); only Practitioner mentions are published |
| The 50 lessons (`lessons.html`, `assets/cc-50-expensive-lessons.pdf`) | `data/lessons.json` | edit JSON, rebuild, re-print the PDF (headless Chrome on lessons.html) |
| Reviews (`reviews.html`) | Apple RSS at build time, cached in `data/reviews.json` | add non-Apple reviews by hand to the cache with `"source": "LinkedIn"` |
| Join In (`join.html`) | `data/upcoming.json` + form links in `templates/join.html` | paste Tally form URLs over the mailto placeholders |
| From the Field (`stories.html`) | `stories/<slug>.md` | one file per approved listener story |

Nav and footer are single-sourced in `extras.py` (`NAV_ITEMS`, `FOOT_ITEMS`). The newsletter block on every page is `extras.newsletter_block()`.

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
