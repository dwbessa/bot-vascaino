"""Persistência SQLite — WAL, FK ON, migrations em SQL puro."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


class Database:
    """Wrapper mínimo. Zero ORM — abre conexão, aplica PRAGMAs, executa migrations."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, isolation_level=None)  # autocommit
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
        finally:
            conn.close()

    def migrate(self, migrations_dir: Path | None = None) -> list[str]:
        """Aplica todas as migrations em ordem. Idempotente."""
        source = migrations_dir or MIGRATIONS_DIR
        applied: list[str] = []
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))",
            )
            done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
            for path in sorted(source.glob("*.sql")):
                if path.name in done:
                    continue
                sql = path.read_text(encoding="utf-8")
                conn.executescript(sql)
                conn.execute("INSERT INTO schema_migrations(name) VALUES (?)", (path.name,))
                applied.append(path.name)
        return applied
