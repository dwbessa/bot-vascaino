#!/usr/bin/env python3
"""Baixa fixtures reais de NetVasco e SuperVasco para tests/fixtures/.

Uso: `uv run python scripts/fetch_fixtures.py`.
Repetível — sobrescreve. Fixtures são commitadas para dar reprodutibilidade
(CLAUDE.md §4). Nunca chame este script no CI.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
NETVASCO_DIR = FIXTURES / "netvasco"
SUPERVASCO_DIR = FIXTURES / "supervasco"

UA = "VascoDigestBot/1.0 (+contato@exemplo.com) fixture-fetch"
NETVASCO_RSS = "https://www.netvasco.com.br/news/rss.xml"
SUPERVASCO_LIST = "https://www.supervasco.com/ultimas-noticias-vasco/"
TIMEOUT = 30.0


def fetch(client: httpx.Client, url: str) -> httpx.Response:
    print(f"→ GET {url}", file=sys.stderr)
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    return resp


def netvasco_article_urls(rss_xml: str, limit: int = 3) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"<link>(https?://[^<]+/n/\d+/[^<]+)</link>", rss_xml):
        urls.append(match.group(1))
        if len(urls) >= limit:
            break
    return urls


def supervasco_article_urls(html: str, limit: int = 3) -> list[str]:
    tree = HTMLParser(html)
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in tree.css("a"):
        href = anchor.attributes.get("href") or ""
        if not re.search(r"/noticias/.+-\d+\.html$", href):
            continue
        if href.startswith("/"):
            href = f"https://www.supervasco.com{href}"
        if "supervasco.com" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        urls.append(href)
        if len(urls) >= limit:
            break
    return urls


def slug_of(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    if tail.endswith(".html"):
        tail = tail[:-5]
    return re.sub(r"[^a-z0-9_.-]", "-", tail.lower())[:80]


def main() -> int:
    NETVASCO_DIR.mkdir(parents=True, exist_ok=True)
    SUPERVASCO_DIR.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers={"User-Agent": UA}, timeout=TIMEOUT) as client:
        rss = fetch(client, NETVASCO_RSS)
        (NETVASCO_DIR / "rss.xml").write_bytes(rss.content)

        for url in netvasco_article_urls(rss.text):
            resp = fetch(client, url)
            (NETVASCO_DIR / f"{slug_of(url)}.html").write_bytes(resp.content)
            time.sleep(1.0)

        listing = fetch(client, SUPERVASCO_LIST)
        (SUPERVASCO_DIR / "listing.html").write_bytes(listing.content)

        for url in supervasco_article_urls(listing.text):
            resp = fetch(client, url)
            (SUPERVASCO_DIR / f"{slug_of(url)}.html").write_bytes(resp.content)
            time.sleep(1.0)

    print("✅ fixtures atualizadas em tests/fixtures/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
