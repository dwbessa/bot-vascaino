"""Adapter SuperVasco — scraping da listagem `/ultimas-noticias-vasco/`.

Cuidado principal: o `<time>` de cada item traz só `HHhMM`, sem data.
A data vem do último header de dia no formato `<span>Domingo, 26/07/2026</span>`.
Antes do primeiro header, os itens são de "hoje" (a partir de `reference_now`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta

import httpx
from selectolax.parser import HTMLParser, Node

from vascobot.models import RawArticle, Watermark
from vascobot.sources.base import RateLimiter, SourceAdapter, request_with_limits

BASE = "https://www.supervasco.com"
LISTING = f"{BASE}/ultimas-noticias-vasco/"

_ARTICLE_HREF = re.compile(r"^/noticias/.+-(\d+)\.html$")
_DAY_HEADER = re.compile(r"^[A-Za-zÁ-Úá-úçÇ-]+,\s*(\d{2})/(\d{2})/(\d{4})$")
_TIME_TAG = re.compile(r"(\d{1,2})h(\d{2})")
_TIME_TAG_FULL = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*[•·-]\s*(\d{1,2}):(\d{2})")


class SuperVascoAdapter(SourceAdapter):
    source_id = "supervasco"
    base_url = BASE
    rate_limit_rps = 0.5

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        limiter: RateLimiter | None = None,
        pages: int = 1,
    ) -> None:
        self._client = client
        self._limiter = limiter or RateLimiter(rps=self.rate_limit_rps)
        self._pages = pages

    async def discover(self, since: Watermark) -> list[RawArticle]:
        if self._client is None:
            raise RuntimeError("SuperVascoAdapter needs an httpx.AsyncClient for live discovery")
        collected: list[RawArticle] = []
        now = datetime.now().astimezone()
        for page in range(1, self._pages + 1):
            url = LISTING if page == 1 else f"{LISTING}?page={page}"
            resp = await request_with_limits(self._client, url, self._limiter)
            page_articles = self.parse_listing(resp.content, reference_now=now)
            filtered = self.filter_since(page_articles, since)
            if not filtered:
                break
            collected.extend(filtered)
        return collected

    def parse_listing(self, body: bytes | str, *, reference_now: datetime) -> list[RawArticle]:
        html = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
        tree = HTMLParser(html)
        current_day: date = reference_now.date()
        tz = reference_now.tzinfo
        out: list[RawArticle] = []
        seen_ids: set[str] = set()

        for li in tree.css("li"):
            span = li.css_first("span")
            if span is not None:
                header_text = " ".join(span.text(strip=True).split())
                match = _DAY_HEADER.match(header_text)
                if match:
                    d, m, y = match.group(1), match.group(2), match.group(3)
                    current_day = date(int(y), int(m), int(d))
                    continue

            article = self._parse_article_li(li, current_day, tz)
            if article and article.external_id not in seen_ids:
                seen_ids.add(article.external_id or "")
                out.append(article.model_copy(update={"fetched_at": reference_now}))

        return out

    @staticmethod
    def _parse_article_li(li: Node, current_day: date, tz: object) -> RawArticle | None:
        anchor = _first_article_anchor(li)
        if anchor is None:
            return None
        href = anchor.attributes.get("href") or ""
        match = _ARTICLE_HREF.match(href)
        if not match:
            return None

        time_tag = li.css_first("time")
        if time_tag is None:
            return None
        published = _parse_time_tag(time_tag.text(strip=True), current_day, tz)
        if published is None:
            return None

        title = " ".join(anchor.text(strip=True).split())
        if not title:
            return None

        return RawArticle(
            source_id="supervasco",
            external_id=match.group(1),
            url=f"{BASE}{href}",
            title=title,
            summary=None,
            body=None,
            published_at=published,
            fetched_at=published,
        )

    @staticmethod
    def filter_since(articles: Iterable[RawArticle], since: Watermark) -> list[RawArticle]:
        """Mesmo watermark duplo do NetVasco: id sequencial primário, ts secundário."""
        cutoff_id = int(since.external_id) if since.external_id else None
        cutoff_ts = since.ts
        keep: list[RawArticle] = []
        for art in articles:
            if cutoff_id is not None and art.external_id and int(art.external_id) <= cutoff_id:
                continue
            if cutoff_ts is not None and art.published_at <= cutoff_ts:
                continue
            keep.append(art)
        return keep


def _first_article_anchor(li: Node) -> Node | None:
    h2 = li.css_first("h2")
    if h2 is None:
        return None
    return h2.css_first("a")


def _parse_time_tag(raw_time: str, current_day: date, tz: object) -> datetime | None:
    full = _TIME_TAG_FULL.search(raw_time)
    if full:
        d, m, y, hh, mm = (int(full.group(i)) for i in range(1, 6))
        return datetime(y, m, d, hh, mm, tzinfo=tz)  # type: ignore[arg-type]
    short = _TIME_TAG.search(raw_time)
    if short:
        return datetime(
            current_day.year,
            current_day.month,
            current_day.day,
            int(short.group(1)),
            int(short.group(2)),
            tzinfo=tz,  # type: ignore[arg-type]
        )
    return None


__all__ = ["SuperVascoAdapter"]


_ = timedelta  # reservado para futura lógica de virada de dia
