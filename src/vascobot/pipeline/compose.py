"""Composição de thread por plataforma — plan.md §6.6, T-023.

- Bluesky: 300 graphemes/post (`regex` `\\X`), links viram *facets* na hora de
  publicar (aqui só marcamos `has_link`).
- X: weighted count com URL fixo em 23 chars, ou 25.000 se Premium.
- `X_LINK_POLICY`: none / last_post / all_posts.
- `idempotency_key = f"{run_id}:{categoria}:{plataforma}:{index}"` (RF-08).
"""

from __future__ import annotations

import re
from collections.abc import Callable

import regex as regex_pkg

from vascobot.config import XLinkPolicy
from vascobot.models import Category, Digest, Platform, PostDraft

BLUESKY_LIMIT = 300
X_LIMIT_FREE = 280
X_LIMIT_PREMIUM = 25_000
X_URL_WEIGHT = 23

_URL_RE = re.compile(r"https?://\S+")
_GRAPHEMES_RE = regex_pkg.compile(r"\X")


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


_BLOCK_SEP = "\n\n"
# Poucas fontes por thread — só as de maior prioridade. Muitas URLs incham a
# thread (e no X, cada URL pesa 23 chars) sem ganho de atribuição.
MAX_SOURCE_URLS = 3


def compose_thread(
    digest: Digest,
    *,
    platform: Platform,
    run_id: str,
    x_is_premium: bool = True,
    x_link_policy: XLinkPolicy = XLinkPolicy.LAST_POST,
    max_posts: int = 4,
) -> list[PostDraft]:
    """Monta a thread empacotando o máximo de conteúdo por post (menos posts = menos custo no X).

    Blocos (raiz, bullets, fontes) são concatenados gulosamente enquanto couberem
    no limite da plataforma. Só quando o próximo bloco estouraria é que abre um
    novo post. Truncar > estourar.
    """
    limit_fits = _fits_fn(platform, x_is_premium=x_is_premium)

    blocks: list[tuple[str, bool]] = [(_render_root(digest), False)]
    blocks.extend((bullet, False) for bullet in digest.bullets)
    sources_block = _render_sources(digest.source_urls, platform, x_link_policy)
    if sources_block is not None:
        blocks.append(sources_block)

    packed = _pack(blocks, limit_fits)
    packed = packed[:max_posts]

    drafts: list[PostDraft] = []
    for idx, (raw_text, has_link) in enumerate(packed):
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


def _fits_fn(platform: Platform, *, x_is_premium: bool) -> Callable[[str], bool]:
    if platform is Platform.BLUESKY:
        return fits_bluesky
    return lambda text: fits_x(text, is_premium=x_is_premium)


def _pack(
    blocks: list[tuple[str, bool]],
    fits: Callable[[str], bool],
) -> list[tuple[str, bool]]:
    """Empacotamento guloso: junta blocos com `\\n\\n` enquanto couberem."""
    posts: list[tuple[str, bool]] = []
    cur_text: str | None = None
    cur_link = False
    for text, has_link in blocks:
        if not text:
            continue
        if cur_text is None:
            cur_text, cur_link = text, has_link
            continue
        candidate = f"{cur_text}{_BLOCK_SEP}{text}"
        if fits(candidate):
            cur_text, cur_link = candidate, cur_link or has_link
        else:
            posts.append((cur_text, cur_link))
            cur_text, cur_link = text, has_link
    if cur_text is not None:
        posts.append((cur_text, cur_link))
    return posts


def _render_root(digest: Digest) -> str:
    return f"🔵⚫ {digest.category.value.upper()}\n{digest.headline}"


def _render_sources(
    urls: list[str],
    platform: Platform,
    policy: XLinkPolicy,
) -> tuple[str, bool] | None:
    """Bloco de fontes. `None` quando não há bloco a incluir."""
    top = urls[:MAX_SOURCE_URLS]
    if not top:
        return None
    if platform is Platform.X and policy is XLinkPolicy.NONE:
        # sem URL no X — atribuição segue no Bluesky (grátis)
        return ("fontes: ver Bluesky", False)
    joined = " · ".join(top)
    return (f"fontes: {joined}", True)


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
