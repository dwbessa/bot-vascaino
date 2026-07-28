"""CLI approve/reject — T-028."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vascobot.cli import app
from vascobot.db import Database
from vascobot.models import Platform, PostDraft, PostStatus
from vascobot.repo import PostRepo

runner = CliRunner()


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "vascobot.db"
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-fake")
    monkeypatch.setenv("BLUESKY_HANDLE", "bot.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "aaaa-bbbb-cccc-dddd")
    monkeypatch.setenv("X_ENABLED", "false")
    monkeypatch.setenv("DB_PATH", str(db_path))
    return db_path


def _seed(db_path: Path) -> PostRepo:
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
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
    repo = PostRepo(db)
    repo.save_drafts(
        [
            PostDraft(
                digest_id="d1",
                platform=Platform.BLUESKY,
                thread_index=0,
                text="post de teste",
                has_link=False,
                idempotency_key="r1:profissional:bluesky:0",
            ),
        ],
        require_approval=True,
    )
    return repo


def test_approve_command_lists_and_releases(_env: Path) -> None:
    repo = _seed(_env)
    result = runner.invoke(app, ["approve", "--run-id", "r1"])
    assert result.exit_code == 0, result.stdout
    assert "post de teste" in result.stdout
    assert "aprovados: 1" in result.stdout
    assert repo.list_pending() == []
    assert len(repo.list_by_status(PostStatus.APPROVED)) == 1


def test_approve_nothing_pending(_env: Path) -> None:
    db = Database(_env)
    db.migrate()
    result = runner.invoke(app, ["approve", "--run-id", "r1"])
    assert result.exit_code == 0
    assert "nenhum post pending" in result.stdout


def test_reject_command(_env: Path) -> None:
    repo = _seed(_env)
    result = runner.invoke(app, ["reject", "--run-id", "r1"])
    assert result.exit_code == 0, result.stdout
    assert "rejeitados: 1" in result.stdout
    assert repo.list_pending() == []
    assert len(repo.list_by_status(PostStatus.SKIPPED)) == 1


def test_pending_command_lists_without_mutating(_env: Path) -> None:
    """`pending` é read-only — mostra os drafts mas não aprova nada."""
    repo = _seed(_env)
    result = runner.invoke(app, ["pending"])
    assert result.exit_code == 0, result.stdout
    assert "post de teste" in result.stdout
    assert "profissional" in result.stdout
    assert "r1" in result.stdout
    # não mutou: continua pending
    assert len(repo.list_pending()) == 1
    assert repo.list_by_status(PostStatus.APPROVED) == []


def test_pending_command_empty(_env: Path) -> None:
    db = Database(_env)
    db.migrate()
    result = runner.invoke(app, ["pending"])
    assert result.exit_code == 0
    assert "nenhum post pending" in result.stdout.lower()
