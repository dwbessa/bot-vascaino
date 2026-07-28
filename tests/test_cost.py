"""Custo do X — T-024, 100% cov."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vascobot.models import Platform, PostDraft, PostStatus, PublishedPost
from vascobot.publishers.cost import (
    COST_POST_WITH_LINK_USD,
    COST_POST_WITHOUT_LINK_USD,
    CostSummary,
    cost_of_post,
    cost_of_published,
    cost_of_thread,
    project_month,
)

BRT = ZoneInfo("America/Sao_Paulo")


def _draft(platform: Platform, has_link: bool, idx: int = 0) -> PostDraft:
    return PostDraft(
        digest_id="d",
        platform=platform,
        thread_index=idx,
        text="t",
        has_link=has_link,
        idempotency_key=f"k-{platform.value}-{idx}",
    )


def test_post_without_link_cheap() -> None:
    assert cost_of_post(has_link=False) == COST_POST_WITHOUT_LINK_USD


def test_post_with_link_expensive() -> None:
    assert cost_of_post(has_link=True) == COST_POST_WITH_LINK_USD


def test_link_is_much_more_expensive() -> None:
    """Aviso do research.md §3: post com link custa ~13x mais."""
    assert COST_POST_WITH_LINK_USD > 10 * COST_POST_WITHOUT_LINK_USD


def test_thread_all_no_link() -> None:
    drafts = [_draft(Platform.X, has_link=False, idx=i) for i in range(4)]
    assert cost_of_thread(drafts) == round(4 * COST_POST_WITHOUT_LINK_USD, 4)


def test_thread_all_link() -> None:
    drafts = [_draft(Platform.X, has_link=True, idx=i) for i in range(4)]
    assert cost_of_thread(drafts) == round(4 * COST_POST_WITH_LINK_USD, 4)


def test_thread_last_post_link_policy() -> None:
    """X_LINK_POLICY=last_post: só o último tem link."""
    drafts = [_draft(Platform.X, has_link=(i == 3), idx=i) for i in range(4)]
    expected = round(3 * COST_POST_WITHOUT_LINK_USD + COST_POST_WITH_LINK_USD, 4)
    assert cost_of_thread(drafts) == expected


def test_bluesky_drafts_dont_cost() -> None:
    drafts = [_draft(Platform.BLUESKY, has_link=True, idx=i) for i in range(4)]
    assert cost_of_thread(drafts) == 0.0


def test_mixed_platforms_only_x_charged() -> None:
    drafts = [
        _draft(Platform.BLUESKY, has_link=True, idx=0),
        _draft(Platform.X, has_link=True, idx=1),
    ]
    assert cost_of_thread(drafts) == COST_POST_WITH_LINK_USD


def test_cost_of_published_sums_stored_cost() -> None:
    posts = [
        PublishedPost(
            id=f"p{i}",
            digest_id="d",
            platform=Platform.X,
            thread_index=i,
            text="t",
            has_link=False,
            status=PostStatus.PUBLISHED,
            cost_usd=0.01,
            published_at=datetime(2026, 7, 27, 12, tzinfo=BRT),
            idempotency_key=f"k-{i}",
        )
        for i in range(3)
    ]
    assert cost_of_published(posts) == 0.03


def test_cost_summary_accumulates() -> None:
    s = CostSummary()
    s.add(platform="x", has_link=False)
    s.add(platform="x", has_link=True)
    s.add(platform="bluesky", has_link=True)
    assert s.posts_without_link == 1
    assert s.posts_with_link == 1
    assert s.total_usd == pytest.approx(COST_POST_WITHOUT_LINK_USD + COST_POST_WITH_LINK_USD)
    assert s.per_platform["bluesky"] == 0.0
    assert s.per_platform["x"] > 0


def test_project_month_linear() -> None:
    # gastou 30 nos 10 primeiros dias → 90 no mês
    assert project_month(30.0, day_of_month=10) == 90.0


def test_project_month_edge_day_zero() -> None:
    """Dia 0 (impossível) → devolve o próprio spent sem dividir por 0."""
    assert project_month(30.0, day_of_month=0) == 30.0


def test_project_month_full_month() -> None:
    assert project_month(100.0, day_of_month=30) == 100.0
