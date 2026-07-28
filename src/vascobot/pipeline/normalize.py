"""Normalização de URL, content_hash e hidratação do corpo do artigo."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import trafilatura

from vascobot.models import Article, ArticleStatus, RawArticle

_UTM_PREFIX = "utm_"
_DROP_PARAMS = {"q", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "share"}
_WWW = re.compile(r"^www\.", re.IGNORECASE)


def canonical_url(url: str) -> str:
    """URL canônica: sem utm_*, sem fragmento, sem `?q=`, sem `www.`, sem barra final."""
    parsed = urlparse(url.strip())
    host = _WWW.sub("", (parsed.hostname or "").lower())
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{host}{port}"

    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith(_UTM_PREFIX) and k.lower() not in _DROP_PARAMS
    ]
    query = urlencode(sorted(kept))
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), netloc, path, "", query, ""))


def article_id(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()


def content_hash(title: str, body: str | None) -> str:
    text = f"{title}\n{body or ''}"
    collapsed = " ".join(text.split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def normalize(raw: RawArticle, *, run_id: str = "") -> Article:
    """Transforma RawArticle → Article. Sem I/O — hidratação de corpo com trafilatura
    fica opcional em `hydrate_body`, pra não amarrar o teste unitário à rede."""
    body = (raw.body or raw.summary or "").strip() or None
    canonical = canonical_url(raw.url)
    return Article(
        id=article_id(raw.url),
        source_id=raw.source_id,
        external_id=raw.external_id,
        url=canonical,
        title=raw.title,
        summary=raw.summary,
        body=body,
        published_at=raw.published_at,
        fetched_at=raw.fetched_at,
        content_hash=content_hash(raw.title, body),
        status=ArticleStatus.OK.value,
        run_id=run_id,
    )


def hydrate_body(html: str) -> str | None:
    """Extração de corpo via trafilatura."""
    return trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        no_fallback=False,
    )
