"""Persistência SQLite — migração idempotente + CRUD por tabela."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.db import MIGRATIONS_DIR, Database

BRT = ZoneInfo("America/Sao_Paulo")


def _iso(y: int = 2026, mo: int = 7, d: int = 27, h: int = 12) -> str:
    return datetime(y, mo, d, h, tzinfo=BRT).isoformat()


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "test.db")
    d.migrate()
    return d


def test_migrations_dir_has_files() -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert files, "sem migrations em /migrations"


def test_migrate_idempotent(tmp_path: Path) -> None:
    d = Database(tmp_path / "x.db")
    d.migrate()
    d.migrate()  # segunda vez não pode explodir
    with d.connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for expected in ("runs", "source_state", "articles", "clusters", "digests", "posts"):
        assert expected in names


def test_wal_and_foreign_keys(db: Database) -> None:
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_runs_crud(db: Database) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO runs(id, started_at, window_start, window_end, status, stats_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("r1", _iso(), _iso(h=6), _iso(h=9), "ok", json.dumps({"collected": 4})),
        )
        row = conn.execute("SELECT id, status, stats_json FROM runs WHERE id=?", ("r1",)).fetchone()
    assert row is not None
    assert row[0] == "r1"
    assert row[1] == "ok"
    assert json.loads(row[2])["collected"] == 4


def test_source_state_crud(db: Database) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO source_state(source_id, watermark_ts, watermark_extid, last_ok_at)"
            " VALUES (?, ?, ?, ?)",
            ("netvasco", _iso(), "386872", _iso()),
        )
        row = conn.execute(
            "SELECT watermark_extid FROM source_state WHERE source_id=?",
            ("netvasco",),
        ).fetchone()
    assert row[0] == "386872"


def test_articles_url_unique(db: Database) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO runs(id, started_at, window_start, window_end, status)"
            " VALUES (?, ?, ?, ?, ?)",
            ("r1", _iso(), _iso(h=6), _iso(h=9), "ok"),
        )
        conn.execute(
            "INSERT INTO articles(id, source_id, url, title, published_at, fetched_at,"
            " content_hash, status, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("a1", "netvasco", "https://x/y", "t", _iso(), _iso(), "h1", "ok", "r1"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO articles(id, source_id, url, title, published_at, fetched_at,"
                " content_hash, status, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("a2", "netvasco", "https://x/y", "t2", _iso(), _iso(), "h2", "ok", "r1"),
            )


def test_digest_unique_run_category(db: Database) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO runs(id, started_at, window_start, window_end, status)"
            " VALUES (?, ?, ?, ?, ?)",
            ("r1", _iso(), _iso(h=6), _iso(h=9), "ok"),
        )
        conn.execute(
            "INSERT INTO digests(id, run_id, category, headline, bullets_json,"
            " source_urls_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("d1", "r1", "feminino", "h", "[]", "[]"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO digests(id, run_id, category, headline, bullets_json,"
                " source_urls_json) VALUES (?, ?, ?, ?, ?, ?)",
                ("d2", "r1", "feminino", "h", "[]", "[]"),
            )


def test_posts_idempotency_key_unique(db: Database) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO runs(id, started_at, window_start, window_end, status)"
            " VALUES (?, ?, ?, ?, ?)",
            ("r1", _iso(), _iso(h=6), _iso(h=9), "ok"),
        )
        conn.execute(
            "INSERT INTO digests(id, run_id, category, headline, bullets_json,"
            " source_urls_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("d1", "r1", "feminino", "h", "[]", "[]"),
        )
        conn.execute(
            "INSERT INTO posts(id, digest_id, platform, thread_index, text, has_link,"
            " status, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("p1", "d1", "bluesky", 0, "hi", 0, "published", "r1:feminino:bluesky:0"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO posts(id, digest_id, platform, thread_index, text, has_link,"
                " status, idempotency_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("p2", "d1", "bluesky", 0, "hi2", 0, "published", "r1:feminino:bluesky:0"),
            )


def test_fk_enforcement(db: Database) -> None:
    with db.connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO articles(id, source_id, url, title, published_at, fetched_at,"
            " content_hash, status, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("a1", "netvasco", "https://x/y", "t", _iso(), _iso(), "h1", "ok", "ghost"),
        )
