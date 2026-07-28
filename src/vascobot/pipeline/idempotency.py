"""Idempotência de posts (RF-08 / CA-05).

`idempotency_key` já é UNIQUE no schema (migrations/0001). Aqui é a lógica que
o pipeline usa: dado um lote de drafts, quais já foram publicados/skipped nessa
mesma chave. Reexecutar a mesma janela não deve criar post novo.
"""

from __future__ import annotations

from vascobot.db import Database
from vascobot.models import PostDraft


def already_committed(db: Database, drafts: list[PostDraft]) -> set[str]:
    """Retorna o conjunto de `idempotency_key`s que já estão em `posts`."""
    if not drafts:
        return set()
    keys = [d.idempotency_key for d in drafts]
    placeholders = ",".join("?" * len(keys))
    with db.connect() as conn:
        rows = conn.execute(
            f"SELECT idempotency_key FROM posts WHERE idempotency_key IN ({placeholders})",  # noqa: S608
            keys,
        ).fetchall()
    return {row[0] for row in rows}


def filter_new(db: Database, drafts: list[PostDraft]) -> list[PostDraft]:
    """Descarta drafts cuja chave já foi persistida."""
    committed = already_committed(db, drafts)
    return [d for d in drafts if d.idempotency_key not in committed]


__all__ = ["already_committed", "filter_new"]
