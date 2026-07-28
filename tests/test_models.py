"""Modelos de domínio — round-trip e datetime naive rejeitado (DTZ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from vascobot.models import (
    Article,
    Category,
    Cluster,
    Digest,
    Platform,
    PostDraft,
    PostStatus,
    PublishedPost,
    RawArticle,
    RunStats,
    RunStatus,
    Watermark,
)

BRT = ZoneInfo("America/Sao_Paulo")


def _now_brt() -> datetime:
    return datetime(2026, 7, 27, 12, 34, 56, tzinfo=BRT)


def test_raw_article_round_trip() -> None:
    raw = RawArticle(
        source_id="netvasco",
        external_id="386872",
        url="https://www.netvasco.com.br/n/386872/vasco-vence",
        title="Vasco vence o Bahia",
        summary="Lide curto.",
        published_at=_now_brt(),
        fetched_at=_now_brt(),
    )
    assert RawArticle.model_validate(raw.model_dump()) == raw


def test_raw_article_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError) as exc:
        RawArticle(
            source_id="netvasco",
            external_id="1",
            url="https://x/y",
            title="t",
            published_at=datetime(2026, 7, 27, 12, 0),  # noqa: DTZ001
            fetched_at=_now_brt(),
        )
    assert "aware" in str(exc.value).lower() or "timezone" in str(exc.value).lower()


def test_article_round_trip() -> None:
    a = Article(
        id="abc123",
        source_id="netvasco",
        external_id="1",
        url="https://x/y",
        title="Vasco",
        body="corpo",
        published_at=_now_brt(),
        fetched_at=_now_brt(),
        content_hash="deadbeef",
        category=Category.PROFISSIONAL,
        confidence=0.9,
        classify_method="rule_positive",
        status="ok",
        run_id="r1",
    )
    assert Article.model_validate(a.model_dump()) == a


def test_cluster_and_digest() -> None:
    c = Cluster(
        id="c1",
        canonical_article_id="a1",
        category=Category.FEMININO,
        size=3,
        run_id="r1",
    )
    d = Digest(
        id="d1",
        run_id="r1",
        category=Category.FEMININO,
        headline="Feminino vence o Fla",
        bullets=["b1", "b2"],
        source_urls=["https://x/1"],
        llm_model="qwen3.5:397b",
    )
    assert Cluster.model_validate(c.model_dump()) == c
    assert Digest.model_validate(d.model_dump()) == d


def test_post_draft_and_published() -> None:
    draft = PostDraft(
        digest_id="d1",
        platform=Platform.BLUESKY,
        thread_index=0,
        text="🔵⚫ FEMININO — 12:00\nHeadline",
        has_link=False,
        idempotency_key="r1:feminino:bluesky:0",
    )
    pub = PublishedPost(
        id="p1",
        digest_id="d1",
        platform=Platform.BLUESKY,
        thread_index=0,
        text=draft.text,
        has_link=False,
        status=PostStatus.PUBLISHED,
        external_id="at://did/app.bsky.feed.post/xyz",
        cost_usd=0.0,
        published_at=_now_brt(),
        idempotency_key=draft.idempotency_key,
    )
    assert PostDraft.model_validate(draft.model_dump()) == draft
    assert PublishedPost.model_validate(pub.model_dump()) == pub


def test_watermark_aware_ts() -> None:
    wm = Watermark(source_id="netvasco", ts=_now_brt(), external_id="386872")
    assert Watermark.model_validate(wm.model_dump()) == wm
    with pytest.raises(ValidationError):
        Watermark(source_id="x", ts=datetime(2026, 7, 27, 12, 0), external_id="1")  # noqa: DTZ001


def test_watermark_none_ts_allowed() -> None:
    Watermark(source_id="netvasco", ts=None, external_id=None)


def test_run_stats_round_trip() -> None:
    rs = RunStats(
        run_id="r1",
        started_at=_now_brt(),
        finished_at=_now_brt(),
        window_start=_now_brt(),
        window_end=_now_brt(),
        status=RunStatus.OK,
        counts={"collected": 10, "descartado": 3},
    )
    assert RunStats.model_validate(rs.model_dump()) == rs


def test_utc_datetime_also_ok() -> None:
    """Aware é aware — tanto BRT quanto UTC quanto offset fixo passam."""
    Watermark(source_id="x", ts=datetime.now(UTC), external_id=None)
    Watermark(
        source_id="x",
        ts=datetime.now(timezone(timedelta(hours=-3))),
        external_id=None,
    )
