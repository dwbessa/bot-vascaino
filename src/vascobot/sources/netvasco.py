"""Adapter NetVasco — RSS `/news/rss.xml`."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from vascobot.models import RawArticle, Watermark
from vascobot.sources.base import RateLimiter, SourceAdapter, request_with_limits

RSS_URL = "https://www.netvasco.com.br/news/rss.xml"
_ID_IN_URL = re.compile(r"/n/(\d+)/")


class NetVascoAdapter(SourceAdapter):
    source_id = "netvasco"
    base_url = "https://www.netvasco.com.br"
    rate_limit_rps = 0.5

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self._client = client
        self._limiter = limiter or RateLimiter(rps=self.rate_limit_rps)

    async def discover(self, since: Watermark) -> list[RawArticle]:
        if self._client is None:
            raise RuntimeError("NetVascoAdapter needs an httpx.AsyncClient for live discovery")
        resp = await request_with_limits(self._client, RSS_URL, self._limiter)
        articles = await self.parse_rss(resp.content)
        return self.filter_since(articles, since)

    async def parse_rss(self, body: bytes) -> list[RawArticle]:
        parsed = feedparser.parse(body)
        now = datetime.now().astimezone()
        out: list[RawArticle] = []
        for entry in parsed.entries:
            url = entry.get("link", "").strip()
            match = _ID_IN_URL.search(url)
            if not match:
                continue
            pub_raw = entry.get("published") or entry.get("pubDate")
            try:
                published = parsedate_to_datetime(pub_raw) if pub_raw else None
            except (TypeError, ValueError):
                published = None
            if published is None or published.tzinfo is None:
                continue
            out.append(
                RawArticle(
                    source_id=self.source_id,
                    external_id=match.group(1),
                    url=url,
                    title=(entry.get("title") or "").strip(),
                    summary=(entry.get("summary") or None),
                    body=None,
                    published_at=published,
                    fetched_at=now,
                    author=(entry.get("author") or None),
                ),
            )
        return out

    @staticmethod
    def filter_since(articles: Iterable[RawArticle], since: Watermark) -> list[RawArticle]:
        """Watermark duplo — id sequencial primário, timestamp secundário."""
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
