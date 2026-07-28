"""Composição de thread por plataforma — plan.md §6.6, T-023.

- Bluesky: 300 graphemes/post (`regex` `\\X`), links viram *facets* na hora de
  publicar (aqui só marcamos `has_link`).
- X: weighted count com URL fixo em 23 chars, ou 25.000 se Premium.
- `X_LINK_POLICY`: none / last_post / all_posts.
- `idempotency_key = f"{run_id}:{categoria}:{plataforma}:{index}"` (RF-08).
"""

from __future__ import annotations

import re
from enum import StrEnum

import regex as regex_pkg

from vascobot.config import XLinkPolicy
from vascobot.models import Category, Digest, Platform, PostDraft

BLUESKY_LIMIT = 300
X_LIMIT_FREE = 280
X_LIMIT_PREMIUM = 25_000
X_URL_WEIGHT = 23

_URL_RE = re.compile(r"https?://\S+")
_GRAPHEMES_RE = regex_pkg.compile(r"\X")


class _Layout(StrEnum):
    ROOT = "root"
    BULLET = "bullet"
    SOURCES = "sources"


def grapheme_count(text: str) -> int:
    """Conta graphemes (`\\X`) — nunca `len()`. Emoji e acento não podem trapacear (CA-04)."""
    return len(_GRAPHEMES_RE.findall(text))


def x_weighted_count(text: str) -> int:
    """URL pesa X_URL_WEIGHT, resto é 1 char cada."""
    urls = _URL_RE.findall(text)
    stripped = _URL_RE.sub("", text)
    return len(stripped) + len(urls) * X_URL_WEIGHT


def fits_bluesky(text: str) -> bool:
    return grapheme_count(text) <= BLUESKY_LIMIT


def fits_x(text: str, *, is_premium: bool) -> bool:
    limit = X_LIMIT_PREMIUM if is_premium else X_LIMIT_FREE
    return x_weighted_count(text) <= limit


def _idempotency_key(run_id: str, category: Category, platform: Platform, idx: int) -> str:
    return f"{run_id}:{category.value}:{platform.value}:{idx}"


def _truncate_bluesky(text: str) -> str:
    if fits_bluesky(text):
        return text
    graphemes = _GRAPHEMES_RE.findall(text)
    return "".join(graphemes[: BLUESKY_LIMIT - 1]) + "…"


def _truncate_x(text: str, *, is_premium: bool) -> str:
    limit = X_LIMIT_PREMIUM if is_premium else X_LIMIT_FREE
    if x_weighted_count(text) <= limit:
        return text
    # trunca aos poucos até caber; URL peso 23 significa que a última porção
    # pode ter que ser cortada. Simples: corta 1 grapheme por vez do fim.
    graphemes = _GRAPHEMES_RE.findall(text)
    while graphemes and x_weighted_count("".join(graphemes)) > limit - 1:
        graphemes.pop()
    return "".join(graphemes) + "…"


def compose_thread(
    digest: Digest,
    *,
    platform: Platform,
    run_id: str,
    x_is_premium: bool = True,
    x_link_policy: XLinkPolicy = XLinkPolicy.LAST_POST,
    max_posts: int = 4,
) -> list[PostDraft]:
    """Monta a thread de uma categoria numa plataforma. Truncar > estourar."""
    posts: list[tuple[str, bool]] = []
    posts.append((_render_root(digest), False))
    for bullet in digest.bullets:
        posts.append((bullet, False))
    sources_text, sources_has_link = _render_sources(digest.source_urls, platform, x_link_policy)
    posts.append((sources_text, sources_has_link))
    posts = posts[:max_posts]

    if platform is Platform.X:
        posts = _apply_x_link_policy(posts, digest.source_urls, x_link_policy)

    drafts: list[PostDraft] = []
    for idx, (raw_text, has_link) in enumerate(posts):
        text = (
            _truncate_bluesky(raw_text)
            if platform is Platform.BLUESKY
            else _truncate_x(raw_text, is_premium=x_is_premium)
        )
        drafts.append(
            PostDraft(
                digest_id=digest.id,
                platform=platform,
                thread_index=idx,
                text=text,
                has_link=has_link,
                idempotency_key=_idempotency_key(run_id, digest.category, platform, idx),
            ),
        )
    return drafts


def _render_root(digest: Digest) -> str:
    return f"🔵⚫ {digest.category.value.upper()}\n{digest.headline}"


def _render_sources(
    urls: list[str],
    platform: Platform,
    policy: XLinkPolicy,
) -> tuple[str, bool]:
    if not urls:
        return ("fontes: —", False)
    if platform is Platform.BLUESKY:
        # Bluesky é grátis — sempre põe todas
        joined = " · ".join(urls)
        return (f"fontes: {joined}", True)
    if policy is XLinkPolicy.NONE:
        return ("fontes: (ver Bluesky)", False)
    joined = " · ".join(urls)
    return (f"fontes: {joined}", True)


def _apply_x_link_policy(
    posts: list[tuple[str, bool]],
    urls: list[str],
    policy: XLinkPolicy,
) -> list[tuple[str, bool]]:
    """Aplica X_LINK_POLICY sobre a thread (sem contar o post-raiz nem o de fontes)."""
    if policy is XLinkPolicy.NONE:
        return [(_URL_RE.sub("", text).strip(), False) for text, _ in posts]
    if policy is XLinkPolicy.LAST_POST:
        # só o último post carrega URLs; os intermediários limpos
        cleaned = [(_URL_RE.sub("", text).strip(), False) for text, _ in posts[:-1]]
        if urls:
            cleaned.append((f"fontes: {' · '.join(urls)}", True))
        else:
            cleaned.append(posts[-1])
        return cleaned
    # ALL_POSTS — todos os posts podem ter link; o de fontes já tem — nada a mudar
    return posts


__all__ = [
    "BLUESKY_LIMIT",
    "X_LIMIT_FREE",
    "X_LIMIT_PREMIUM",
    "X_URL_WEIGHT",
    "compose_thread",
    "fits_bluesky",
    "fits_x",
    "grapheme_count",
    "x_weighted_count",
]
