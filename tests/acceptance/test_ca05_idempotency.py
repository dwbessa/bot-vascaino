"""CA-05 — reexecutar a mesma janela não publica nada novo."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from vascobot.db import Database
from vascobot.models import Platform, PostDraft
from vascobot.pipeline.idempotency import already_committed, filter_new


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "ca05.db")
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


def _draft(key: str, idx: int = 0) -> PostDraft:
    return PostDraft(
        digest_id="d1",
        platform=Platform.BLUESKY,
        thread_index=idx,
        text="t",
        has_link=False,
        idempotency_key=key,
    )


@pytest.mark.acceptance
def test_ca05_idempotent_rerun(db: Database) -> None:
    """1ª run persiste; 2ª tentativa com a mesma chave é filtrada antes."""
    key = "r1:profissional:bluesky:0"
    draft = _draft(key)

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO posts(id, digest_id, platform, thread_index, text, has_link,"
            " status, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("p1", "d1", "bluesky", 0, "t", 0, "published", key),
        )

    # Reexecutar deve devolver zero novos
    assert filter_new(db, [draft]) == []


@pytest.mark.acceptance
def test_ca05_new_drafts_pass_through(db: Database) -> None:
    """Drafts novos (chaves nunca vistas) sobrevivem ao filtro."""
    fresh = [_draft(f"r1:profissional:bluesky:{i}", i) for i in range(3)]
    assert filter_new(db, fresh) == fresh


@pytest.mark.acceptance
def test_ca05_partial_overlap(db: Database) -> None:
    """Mistura: 2 já persistidos + 1 novo → devolve só o novo."""
    keys = [f"r1:profissional:bluesky:{i}" for i in range(3)]
    with db.connect() as conn:
        for i, key in enumerate(keys[:2]):
            conn.execute(
                "INSERT INTO posts(id, digest_id, platform, thread_index, text, has_link,"
                " status, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"pf-{i}", "d1", "bluesky", i, "t", 0, "published", key),
            )
    drafts = [_draft(k, i) for i, k in enumerate(keys)]
    remaining = filter_new(db, drafts)
    assert [d.idempotency_key for d in remaining] == [keys[2]]


def test_committed_empty_input(db: Database) -> None:
    assert already_committed(db, []) == set()
    assert filter_new(db, []) == []


def test_db_unique_constraint_still_enforced(db: Database) -> None:
    """Sanity: mesmo sem checagem no código, o UNIQUE do schema barra."""
    key = "r1:profissional:bluesky:0"
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO posts(id, digest_id, platform, thread_index, text, has_link,"
            " status, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("p1", "d1", "bluesky", 0, "t", 0, "published", key),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO posts(id, digest_id, platform, thread_index, text, has_link,"
                " status, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("p2", "d1", "bluesky", 0, "t", 0, "published", key),
            )
