"""Publicação dos posts aprovados — fecha o fluxo de aprovação (T-028/T-025)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.db import Database
from vascobot.models import Platform, PostDraft, PostStatus, PublishedPost
from vascobot.pipeline.publish import publish_approved
from vascobot.publishers.base import Publisher
from vascobot.publishers.registry import PublisherRegistry
from vascobot.repo import PostRepo

BRT = ZoneInfo("America/Sao_Paulo")


class _FakeBluesky(Publisher):
    platform = "bluesky"

    def __init__(self) -> None:
        self.enabled = True
        self.threads: list[list[PostDraft]] = []

    async def publish_thread(self, drafts: list[PostDraft]) -> list[PublishedPost]:
        self.threads.append(drafts)
        return [
            PublishedPost(
                id=f"pub-{d.thread_index}",
                digest_id=d.digest_id,
                platform=d.platform,
                thread_index=d.thread_index,
                text=d.text,
                has_link=d.has_link,
                status=PostStatus.PUBLISHED,
                external_id=f"at://did/{d.thread_index}",
                cost_usd=0.0,
                published_at=datetime(2026, 7, 27, 12, tzinfo=BRT),
                idempotency_key=d.idempotency_key,
            )
            for d in drafts
        ]


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "pub.db")
    d.migrate()
    with d.connect() as conn:
        conn.execute(
            "INSERT INTO runs(id, started_at, window_start, window_end, status)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                "r1",
                "2026-07-27T06:00:00-03:00",
                "2026-07-27T00:00:00-03:00",
                "2026-07-27T06:00:00-03:00",
                "ok",
            ),
        )
        conn.execute(
            "INSERT INTO digests(id, run_id, category, headline, bullets_json, source_urls_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("d1", "r1", "profissional", "h", "[]", "[]"),
        )
    return d


def _approve_three(db: Database) -> PostRepo:
    repo = PostRepo(db)
    drafts = [
        PostDraft(
            digest_id="d1",
            platform=Platform.BLUESKY,
            thread_index=i,
            text=f"post {i}",
            has_link=(i == 2),
            idempotency_key=f"r1:profissional:bluesky:{i}",
        )
        for i in range(3)
    ]
    repo.save_drafts(drafts, require_approval=True)
    repo.approve(run_id="r1")
    return repo


def test_publish_sends_approved_thread_in_order(db: Database) -> None:
    _approve_three(db)
    reg = PublisherRegistry()
    pub = _FakeBluesky()
    reg.register(pub)

    counts = asyncio.run(publish_approved(db, reg))

    assert counts["bluesky"] == 3
    assert len(pub.threads) == 1
    sent = pub.threads[0]
    assert [d.thread_index for d in sent] == [0, 1, 2]


def test_publish_marks_posts_published(db: Database) -> None:
    repo = _approve_three(db)
    reg = PublisherRegistry()
    reg.register(_FakeBluesky())

    asyncio.run(publish_approved(db, reg))

    assert repo.list_by_status(PostStatus.APPROVED) == []
    published = repo.list_by_status(PostStatus.PUBLISHED)
    assert len(published) == 3
    assert all(p.external_id and p.external_id.startswith("at://") for p in published)


def test_publish_noop_when_nothing_approved(db: Database) -> None:
    reg = PublisherRegistry()
    pub = _FakeBluesky()
    reg.register(pub)
    counts = asyncio.run(publish_approved(db, reg))
    assert counts == {}
    assert pub.threads == []


def test_publish_skips_disabled_platform(db: Database) -> None:
    _approve_three(db)
    reg = PublisherRegistry()
    pub = _FakeBluesky()
    pub.enabled = False
    reg.register(pub)
    counts = asyncio.run(publish_approved(db, reg))
    assert counts.get("bluesky", 0) == 0
    assert pub.threads == []


def test_publish_is_idempotent_second_run_noop(db: Database) -> None:
    """Depois de publicado, os posts saem de approved — 2ª chamada não repete."""
    _approve_three(db)
    reg = PublisherRegistry()
    pub = _FakeBluesky()
    reg.register(pub)

    asyncio.run(publish_approved(db, reg))
    asyncio.run(publish_approved(db, reg))
    assert len(pub.threads) == 1  # só a primeira publicou


def test_publish_records_failure(db: Database) -> None:
    _approve_three(db)

    class _Broken(Publisher):
        platform = "bluesky"
        enabled = True

        async def publish_thread(self, drafts: list[PostDraft]) -> list[PublishedPost]:
            return [
                PublishedPost(
                    id=f"f-{drafts[0].thread_index}",
                    digest_id=drafts[0].digest_id,
                    platform=drafts[0].platform,
                    thread_index=drafts[0].thread_index,
                    text=drafts[0].text,
                    has_link=drafts[0].has_link,
                    status=PostStatus.FAILED,
                    error="boom",
                    published_at=datetime(2026, 7, 27, 12, tzinfo=BRT),
                    idempotency_key=drafts[0].idempotency_key,
                ),
            ]

    reg = PublisherRegistry()
    reg.register(_Broken())
    repo = PostRepo(db)
    asyncio.run(publish_approved(db, reg))
    failed = repo.list_by_status(PostStatus.FAILED)
    assert len(failed) == 1
    assert failed[0].error == "boom"
