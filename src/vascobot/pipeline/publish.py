"""Publicação dos posts aprovados — fecha o fluxo `run → approve → publish`.

Consome posts com status `approved`, reagrupa em threads por (digest, plataforma),
publica via o Publisher da plataforma (só se ativo) e persiste o resultado.
Idempotente: publicado sai de `approved`, então rodar de novo não repete.
"""

from __future__ import annotations

import structlog

from vascobot.db import Database
from vascobot.models import Platform, PostDraft, PostStatus
from vascobot.publishers.registry import PublisherRegistry
from vascobot.repo import PostRepo, StoredPost

_log = structlog.get_logger(__name__)


def _to_draft(post: StoredPost) -> PostDraft:
    return PostDraft(
        digest_id=post.digest_id,
        platform=Platform(post.platform),
        thread_index=post.thread_index,
        text=post.text,
        has_link=post.has_link,
        idempotency_key=post.idempotency_key,
    )


async def publish_approved(db: Database, registry: PublisherRegistry) -> dict[str, int]:
    """Publica todas as threads aprovadas. Retorna contagem de posts publicados por plataforma."""
    repo = PostRepo(db)
    approved = repo.list_by_status(PostStatus.APPROVED)
    if not approved:
        return {}

    # Agrupa por (digest_id, platform), preservando ordem de thread_index.
    threads: dict[tuple[str, str], list[StoredPost]] = {}
    for post in approved:
        threads.setdefault((post.digest_id, post.platform), []).append(post)

    published_counts: dict[str, int] = {}
    for (digest_id, platform), posts in threads.items():
        publisher = registry.get(platform)
        if publisher is None or not publisher.enabled:
            _log.warning("publish.skip_inactive", platform=platform, digest_id=digest_id)
            continue

        drafts = [_to_draft(p) for p in sorted(posts, key=lambda x: x.thread_index)]
        results = await publisher.publish_thread(drafts)
        for result in results:
            repo.record_result(result)
            if result.status is PostStatus.PUBLISHED:
                published_counts[platform] = published_counts.get(platform, 0) + 1

        _log.info(
            "publish.thread_done",
            platform=platform,
            digest_id=digest_id,
            posts=len(results),
        )

    return published_counts


__all__ = ["publish_approved"]
