#!/usr/bin/env python3
"""Print the Expensive Lessons Field Deck PDFs from the built lessons page.

Run AFTER build.py, with the local server up (or it starts one itself):
    python3 make_deck.py

Writes site/assets/cc-expensive-lessons-deck.pdf plus -super / -pm / -exec
editions (one lesson per page via the print stylesheet). Requires Google
Chrome. PDFs are committed to the repo; CI does not regenerate them.
"""

import subprocess
import sys
import time
from pathlib import Path

import extras
from extras import apply_chrome, lessons_sections, load_lessons, newsletter_block, set_episode_index

ROOT = Path(__file__).parent
SITE = ROOT / "site"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 8749

EDITIONS = {
    "deck": ("", "The Expensive Lessons Field Deck"),
    "super": ("Super", "The Superintendent Edition"),
    "pm": ("PM", "The PM Edition"),
    "exec": ("Exec", "The Exec and Owner Edition"),
}


def main():
    import build
    episodes, _ = build.parse_episodes((ROOT / "feed.xml").read_text())
    set_episode_index(episodes)
    data = load_lessons()
    tpl = (ROOT / "templates" / "lessons.html").read_text()

    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--directory", str(SITE)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        for key, (role, subtitle) in EDITIONS.items():
            page = tpl.replace("{{LESSONS}}", lessons_sections(data, role=role))
            page = page.replace("{{LESSON_COUNT}}", str(len({l["episode"] for l in data["lessons"]})))
            page = page.replace("{{NEWSLETTER}}", newsletter_block("", compact=True))
            page = page.replace("The 50 most expensive lessons", subtitle)
            (SITE / f"_print_{key}.html").write_text(apply_chrome(page, ""))
            out = SITE / "assets" / f"cc-expensive-lessons-{key}.pdf"
            subprocess.run([
                CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={out}", f"http://localhost:{PORT}/_print_{key}.html",
            ], check=True, capture_output=True)
            (SITE / f"_print_{key}.html").unlink()
            print(f"{out.name}: {out.stat().st_size // 1024} KB")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
