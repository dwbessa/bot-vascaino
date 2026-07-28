"""Fila de aprovação — T-028 (RF-10)."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.db import Database
from vascobot.models import Platform, PostDraft, PostStatus
from vascobot.repo import PostRepo

BRT = ZoneInfo("America/Sao_Paulo")


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "approval.db")
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
        for cat in ("profissional", "feminino"):
            conn.execute(
                "INSERT INTO digests(id, run_id, category, headline, bullets_json,"
                " source_urls_json) VALUES (?, ?, ?, ?, ?, ?)",
                (f"d-{cat}", "r1", cat, "h", "[]", "[]"),
            )
    return d


def _draft(digest_id: str, cat: str, idx: int) -> PostDraft:
    return PostDraft(
        digest_id=digest_id,
        platform=Platform.BLUESKY,
        thread_index=idx,
        text=f"post {cat} {idx}",
        has_link=False,
        idempotency_key=f"r1:{cat}:bluesky:{idx}",
    )


def test_save_pending_when_require_approval(db: Database) -> None:
    repo = PostRepo(db)
    drafts = [_draft("d-profissional", "profissional", i) for i in range(2)]
    repo.save_drafts(drafts, require_approval=True)

    pending = repo.list_pending()
    assert len(pending) == 2
    assert all(p.status is PostStatus.PENDING for p in pending)


def test_save_approved_when_no_approval(db: Database) -> None:
    repo = PostRepo(db)
    drafts = [_draft("d-profissional", "profissional", 0)]
    repo.save_drafts(drafts, require_approval=False)
    assert repo.list_pending() == []
    approved = repo.list_by_status(PostStatus.APPROVED)
    assert len(approved) == 1


def test_approve_flips_pending_to_approved(db: Database) -> None:
    repo = PostRepo(db)
    repo.save_drafts([_draft("d-profissional", "profissional", 0)], require_approval=True)
    n = repo.approve(run_id="r1")
    assert n == 1
    assert repo.list_pending() == []
    assert len(repo.list_by_status(PostStatus.APPROVED)) == 1


def test_approve_filtered_by_category(db: Database) -> None:
    repo = PostRepo(db)
    repo.save_drafts([_draft("d-profissional", "profissional", 0)], require_approval=True)
    repo.save_drafts([_draft("d-feminino", "feminino", 0)], require_approval=True)
    n = repo.approve(run_id="r1", category="feminino")
    assert n == 1
    pending = repo.list_pending()
    assert len(pending) == 1
    assert "profissional" in pending[0].idempotency_key


def test_reject_marks_skipped(db: Database) -> None:
    repo = PostRepo(db)
    repo.save_drafts([_draft("d-profissional", "profissional", 0)], require_approval=True)
    n = repo.reject(run_id="r1")
    assert n == 1
    assert repo.list_pending() == []
    skipped = repo.list_by_status(PostStatus.SKIPPED)
    assert len(skipped) == 1
    assert skipped[0].error == "rejeitado na aprovação"


def test_nothing_published_without_approval_when_flag_on(db: Database) -> None:
    """RF-10 — com REQUIRE_APPROVAL, nada sai de pending sem approve explícito."""
    repo = PostRepo(db)
    repo.save_drafts([_draft("d-profissional", "profissional", 0)], require_approval=True)
    assert repo.list_by_status(PostStatus.APPROVED) == []
    assert repo.list_by_status(PostStatus.PUBLISHED) == []


def test_save_is_idempotent_on_key(db: Database) -> None:
    """Salvar o mesmo draft duas vezes nao duplica (idempotency_key UNIQUE)."""
    repo = PostRepo(db)
    d = _draft("d-profissional", "profissional", 0)
    repo.save_drafts([d], require_approval=True)
    repo.save_drafts([d], require_approval=True)
    assert len(repo.list_pending()) == 1


def test_approve_returns_zero_when_nothing_pending(db: Database) -> None:
    repo = PostRepo(db)
    assert repo.approve(run_id="r1") == 0


def test_list_pending_ordered_by_category_then_index(db: Database) -> None:
    repo = PostRepo(db)
    repo.save_drafts(
        [_draft("d-profissional", "profissional", 1), _draft("d-profissional", "profissional", 0)],
        require_approval=True,
    )
    pending = repo.list_pending()
    assert [p.thread_index for p in pending] == [0, 1]
