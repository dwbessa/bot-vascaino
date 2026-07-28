"""Repositórios tipados — SQL cru, parametrizado (CLAUDE.md §7).

Só o que a Fase 4 precisa: persistir posts, listar por status, aprovar/rejeitar.
Runs/digests/articles são gravados pelo pipeline (run.py) com SQL direto.
"""

from __future__ import annotations

from dataclasses import dataclass

from vascobot.db import Database
from vascobot.models import PostDraft, PostStatus, PublishedPost


@dataclass(frozen=True)
class StoredPost:
    id: str
    digest_id: str
    platform: str
    thread_index: int
    text: str
    has_link: bool
    status: PostStatus
    idempotency_key: str
    error: str | None = None
    external_id: str | None = None
    cost_usd: float = 0.0


def _post_id(draft: PostDraft) -> str:
    return f"post-{draft.idempotency_key}"


class PostRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    def save_drafts(self, drafts: list[PostDraft], *, require_approval: bool) -> None:
        """Grava drafts. Status inicial = pending se require_approval, senão approved.

        Idempotente: chave já existente é ignorada (ON CONFLICT DO NOTHING).
        """
        status = PostStatus.PENDING if require_approval else PostStatus.APPROVED
        with self._db.connect() as conn:
            for d in drafts:
                conn.execute(
                    "INSERT INTO posts(id, digest_id, platform, thread_index, text,"
                    " has_link, status, cost_usd, idempotency_key)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(idempotency_key) DO NOTHING",
                    (
                        _post_id(d),
                        d.digest_id,
                        d.platform.value,
                        d.thread_index,
                        d.text,
                        int(d.has_link),
                        status.value,
                        0.0,
                        d.idempotency_key,
                    ),
                )

    def list_by_status(self, status: PostStatus) -> list[StoredPost]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT id, digest_id, platform, thread_index, text, has_link, status,"
                " idempotency_key, error, external_id, cost_usd"
                " FROM posts WHERE status=?"
                " ORDER BY digest_id, thread_index",
                (status.value,),
            ).fetchall()
        return [_row_to_post(r) for r in rows]

    def list_pending(self) -> list[StoredPost]:
        return self.list_by_status(PostStatus.PENDING)

    def _transition(
        self,
        *,
        from_status: PostStatus,
        to_status: PostStatus,
        run_id: str | None,
        category: str | None,
        error: str | None,
    ) -> int:
        params: list[object] = [to_status.value]
        set_clause = "status=?"
        if error is not None:
            set_clause += ", error=?"
            params.append(error)
        where = (
            "idempotency_key IN ("
            " SELECT p.idempotency_key FROM posts p"
            " JOIN digests d ON d.id = p.digest_id"
            " WHERE p.status=?"
        )
        params.append(from_status.value)
        if run_id is not None:
            where += " AND d.run_id=?"
            params.append(run_id)
        if category is not None:
            where += " AND d.category=?"
            params.append(category)
        where += ")"

        with self._db.connect() as conn:
            cur = conn.execute(f"UPDATE posts SET {set_clause} WHERE {where}", params)  # noqa: S608
            return cur.rowcount

    def approve(self, *, run_id: str | None = None, category: str | None = None) -> int:
        return self._transition(
            from_status=PostStatus.PENDING,
            to_status=PostStatus.APPROVED,
            run_id=run_id,
            category=category,
            error=None,
        )

    def reject(self, *, run_id: str | None = None, category: str | None = None) -> int:
        return self._transition(
            from_status=PostStatus.PENDING,
            to_status=PostStatus.SKIPPED,
            run_id=run_id,
            category=category,
            error="rejeitado na aprovação",
        )

    def record_result(self, post: PublishedPost) -> None:
        """Persiste o resultado de uma publicação, casando por idempotency_key."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE posts SET status=?, external_id=?, cost_usd=?, published_at=?,"
                " error=? WHERE idempotency_key=?",
                (
                    post.status.value,
                    post.external_id,
                    post.cost_usd,
                    post.published_at.isoformat() if post.published_at else None,
                    post.error,
                    post.idempotency_key,
                ),
            )


def _row_to_post(r: tuple[object, ...]) -> StoredPost:
    return StoredPost(
        id=str(r[0]),
        digest_id=str(r[1]),
        platform=str(r[2]),
        thread_index=int(str(r[3])),
        text=str(r[4]),
        has_link=bool(r[5]),
        status=PostStatus(str(r[6])),
        idempotency_key=str(r[7]),
        error=str(r[8]) if r[8] is not None else None,
        external_id=str(r[9]) if r[9] is not None else None,
        cost_usd=float(str(r[10])),
    )


__all__ = ["PostRepo", "StoredPost"]
