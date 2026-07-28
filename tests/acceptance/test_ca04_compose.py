"""CA-04 — nenhum post excede o limite. Property-ish com emoji e acento."""

from __future__ import annotations

import random
import string

import pytest

from vascobot.config import XLinkPolicy
from vascobot.models import Category, Digest, Platform
from vascobot.pipeline.compose import (
    BLUESKY_LIMIT,
    X_LIMIT_FREE,
    X_LIMIT_PREMIUM,
    compose_thread,
    fits_bluesky,
    fits_x,
    grapheme_count,
    x_weighted_count,
)

EMOJIS = "🔵⚫🇧🇷🏆⚽💪🐊🚨💥⚔️🏟️"


def _digest(headline: str = "H", bullets: list[str] | None = None) -> Digest:
    return Digest(
        id="d1",
        run_id="r1",
        category=Category.PROFISSIONAL,
        headline=headline,
        bullets=bullets or ["b1", "b2"],
        source_urls=["https://x/y/1", "https://x/y/2"],
        llm_model="fake",
    )


# ------------------------------------------------------------- grapheme count
def test_grapheme_count_emoji_is_one() -> None:
    assert grapheme_count("🔵⚫") == 2


def test_grapheme_count_accented_chars() -> None:
    assert grapheme_count("São Januário") == len("São Januário")


def test_len_lies_about_emoji_but_grapheme_does_not() -> None:
    """len('👨‍👩‍👧') > grapheme_count — CA-04 depende disso."""
    text = "👨‍👩‍👧"
    assert grapheme_count(text) == 1
    assert len(text) > 1


# ------------------------------------------------------------- weighted X
def test_x_url_counts_23() -> None:
    assert x_weighted_count("https://verylong-url.example.com/foo/bar/baz") == 23


def test_x_mixed_text_and_url() -> None:
    text = "veja fontes: https://verylong-url.example.com/foo"
    assert x_weighted_count(text) == len("veja fontes: ") + 23


# ------------------------------------------------------------- CA-04 property
@pytest.mark.acceptance
def test_ca04_bluesky_post_length_never_exceeds_limit() -> None:
    """Property: qualquer digest possível → todo draft ≤ BLUESKY_LIMIT graphemes."""
    rng = random.Random(42)
    for trial in range(200):
        headline_len = rng.randint(0, 80)
        headline = "".join(
            rng.choice(string.ascii_letters + " " + EMOJIS) for _ in range(headline_len)
        )
        n_bullets = rng.randint(0, 2)
        bullets = [
            "".join(
                rng.choice(string.ascii_letters + " " + EMOJIS + "ãâáéíçú")
                for _ in range(rng.randint(0, 140))
            )
            for _ in range(n_bullets)
        ]
        digest = _digest(headline=headline or "h", bullets=bullets)
        drafts = compose_thread(
            digest,
            platform=Platform.BLUESKY,
            run_id="r1",
            x_link_policy=XLinkPolicy.LAST_POST,
        )
        for d in drafts:
            assert fits_bluesky(d.text), (
                f"trial {trial}: len={grapheme_count(d.text)} text={d.text!r}"
            )


@pytest.mark.acceptance
def test_ca04_x_free_post_length_never_exceeds_limit() -> None:
    rng = random.Random(7)
    for _ in range(100):
        headline = "".join(
            rng.choice(string.ascii_letters + " ") for _ in range(rng.randint(0, 80))
        )
        bullets = [
            "".join(rng.choice(string.ascii_letters + " ") for _ in range(rng.randint(0, 140)))
            for _ in range(rng.randint(0, 2))
        ]
        d = _digest(headline=headline or "h", bullets=bullets)
        drafts = compose_thread(
            d,
            platform=Platform.X,
            run_id="r1",
            x_is_premium=False,
            x_link_policy=XLinkPolicy.LAST_POST,
        )
        for draft in drafts:
            assert fits_x(draft.text, is_premium=False), draft.text


# ------------------------------------------------------------- políticas X
@pytest.mark.acceptance
def test_ca04_x_link_policy_none_never_has_link() -> None:
    d = _digest()
    drafts = compose_thread(d, platform=Platform.X, run_id="r", x_link_policy=XLinkPolicy.NONE)
    assert not any(dd.has_link for dd in drafts)
    assert all("http" not in dd.text for dd in drafts)


@pytest.mark.acceptance
def test_ca04_x_link_policy_last_post_only_last_has_link() -> None:
    d = _digest()
    drafts = compose_thread(d, platform=Platform.X, run_id="r", x_link_policy=XLinkPolicy.LAST_POST)
    has_link_indices = [i for i, dd in enumerate(drafts) if dd.has_link]
    assert has_link_indices == [len(drafts) - 1]


@pytest.mark.acceptance
def test_ca04_x_link_policy_all_posts() -> None:
    d = _digest()
    drafts = compose_thread(d, platform=Platform.X, run_id="r", x_link_policy=XLinkPolicy.ALL_POSTS)
    assert drafts[-1].has_link


# ------------------------------------------------------------- idempotency
def test_idempotency_key_deterministic() -> None:
    d = _digest()
    a = compose_thread(d, platform=Platform.BLUESKY, run_id="r")
    b = compose_thread(d, platform=Platform.BLUESKY, run_id="r")
    assert [x.idempotency_key for x in a] == [x.idempotency_key for x in b]


def test_idempotency_key_differs_by_platform() -> None:
    d = _digest()
    b = compose_thread(d, platform=Platform.BLUESKY, run_id="r")
    x = compose_thread(d, platform=Platform.X, run_id="r")
    assert b[0].idempotency_key != x[0].idempotency_key


def test_max_posts_per_thread_enforced() -> None:
    d = _digest(bullets=["a", "b"])
    drafts = compose_thread(d, platform=Platform.BLUESKY, run_id="r", max_posts=3)
    assert len(drafts) == 3


def test_bluesky_link_always_kept_regardless_of_policy() -> None:
    """Bluesky é grátis — política do X não afeta."""
    d = _digest()
    drafts = compose_thread(
        d, platform=Platform.BLUESKY, run_id="r", x_link_policy=XLinkPolicy.NONE
    )
    assert any(dd.has_link for dd in drafts)


def test_x_premium_much_higher_limit() -> None:
    """Post grande, premium=True → passa. Premium=False → precisa truncar."""
    long_bullet = "palavra " * 200
    d = _digest(headline="ok", bullets=[long_bullet, "b2"])
    drafts_p = compose_thread(d, platform=Platform.X, run_id="r", x_is_premium=True)
    drafts_f = compose_thread(d, platform=Platform.X, run_id="r", x_is_premium=False)
    assert all(fits_x(dd.text, is_premium=True) for dd in drafts_p)
    assert all(fits_x(dd.text, is_premium=False) for dd in drafts_f)


def test_grapheme_count_within_bluesky_limit_boundary() -> None:
    """Boundary: 300 exatos passam, 301 não."""
    assert fits_bluesky("a" * BLUESKY_LIMIT)
    assert not fits_bluesky("a" * (BLUESKY_LIMIT + 1))


def test_x_limits_documented_correctly() -> None:
    assert X_LIMIT_FREE == 280
    assert X_LIMIT_PREMIUM == 25_000


def test_bluesky_truncates_when_over_limit() -> None:
    """Bullet gigante (Pydantic não vê) → truncador do compose corta com '…'."""
    from vascobot.pipeline.compose import _truncate_bluesky

    text = "a" * (BLUESKY_LIMIT + 100)
    truncated = _truncate_bluesky(text)
    assert truncated.endswith("…")
    assert grapheme_count(truncated) <= BLUESKY_LIMIT


def test_digest_without_sources_renders_placeholder() -> None:
    d = Digest(
        id="d1",
        run_id="r1",
        category=Category.PROFISSIONAL,
        headline="h",
        bullets=[],
        source_urls=[],
        llm_model="fake",
    )
    drafts = compose_thread(d, platform=Platform.BLUESKY, run_id="r")
    assert "—" in drafts[-1].text
    assert drafts[-1].has_link is False


def test_x_none_policy_with_no_sources_renders_placeholder() -> None:
    d = Digest(
        id="d1",
        run_id="r1",
        category=Category.PROFISSIONAL,
        headline="h",
        bullets=[],
        source_urls=[],
        llm_model="fake",
    )
    drafts = compose_thread(d, platform=Platform.X, run_id="r", x_link_policy=XLinkPolicy.NONE)
    assert not any(dd.has_link for dd in drafts)


def test_x_last_post_with_no_sources_keeps_original_last_post() -> None:
    d = Digest(
        id="d1",
        run_id="r1",
        category=Category.PROFISSIONAL,
        headline="h",
        bullets=[],
        source_urls=[],  # ← força o fallback
        llm_model="fake",
    )
    drafts = compose_thread(d, platform=Platform.X, run_id="r", x_link_policy=XLinkPolicy.LAST_POST)
    # sem sources, o último post do X vira o placeholder — não deve ter link
    assert not drafts[-1].has_link
