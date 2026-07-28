"""Etapa 1 do pipeline — coleta com watermark duplo e isolamento de falhas.

Regras (RF-02 / RF-06 / CA-06):
- Cada fonte tem watermark próprio, lido de `source_state`.
- Adapters rodam concorrentes via `asyncio.gather(return_exceptions=True)`.
- Uma exceção em uma fonte não derruba as outras.
- Watermark **só** avança em sucesso.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime

import structlog

from vascobot.db import Database
from vascobot.models import RawArticle, Watermark
from vascobot.sources.base import SourceAdapter
from vascobot.sources.registry import SourceRegistry

_log = structlog.get_logger(__name__)


@dataclass
class SourceOutcome:
    source_id: str
    articles: list[RawArticle] = field(default_factory=list)
    error: BaseException | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class CollectResult:
    articles: list[RawArticle]
    successful: list[SourceOutcome]
    failed: list[SourceOutcome]


def _load_watermark(db: Database, source_id: str) -> Watermark:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT watermark_ts, watermark_extid FROM source_state WHERE source_id=?",
            (source_id,),
        ).fetchone()
    if row is None:
        return Watermark(source_id=source_id)
    ts_raw, ext = row
    ts_parsed = datetime.fromisoformat(ts_raw) if ts_raw else None
    return Watermark(source_id=source_id, ts=ts_parsed, external_id=ext)


def _advance_watermark(db: Database, source_id: str, articles: list[RawArticle]) -> None:
    """Watermark = maior id sequencial + timestamp mais novo."""
    if not articles:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO source_state(source_id, last_ok_at, last_error)"
                " VALUES (?, datetime('now'), NULL)"
                " ON CONFLICT(source_id) DO UPDATE SET"
                " last_ok_at=excluded.last_ok_at, last_error=NULL",
                (source_id,),
            )
        return

    max_id = None
    for a in articles:
        if a.external_id and a.external_id.isdigit():
            n = int(a.external_id)
            if max_id is None or n > max_id:
                max_id = n
    max_ts = max(a.published_at for a in articles).isoformat()

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO source_state(source_id, watermark_ts, watermark_extid,"
            " last_ok_at, last_error) VALUES (?, ?, ?, datetime('now'), NULL)"
            " ON CONFLICT(source_id) DO UPDATE SET"
            " watermark_ts=excluded.watermark_ts,"
            " watermark_extid=excluded.watermark_extid,"
            " last_ok_at=excluded.last_ok_at, last_error=NULL",
            (source_id, max_ts, str(max_id) if max_id is not None else None),
        )


def _record_failure(db: Database, source_id: str, exc: BaseException) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO source_state(source_id, last_error) VALUES (?, ?)"
            " ON CONFLICT(source_id) DO UPDATE SET last_error=excluded.last_error",
            (source_id, f"{type(exc).__name__}: {exc}"),
        )


async def _run_one(adapter: SourceAdapter, since: Watermark) -> SourceOutcome:
    try:
        articles = await adapter.discover(since)
    except (Exception, asyncio.CancelledError) as exc:
        return SourceOutcome(source_id=adapter.source_id, error=exc)
    return SourceOutcome(source_id=adapter.source_id, articles=articles)


async def collect(
    registry: SourceRegistry,
    db: Database,
    *,
    source_ids: tuple[str, ...],
) -> CollectResult:
    adapters = registry.enabled(source_ids)
    watermarks = {a.source_id: _load_watermark(db, a.source_id) for a in adapters}

    outcomes = await asyncio.gather(
        *(_run_one(a, watermarks[a.source_id]) for a in adapters),
    )

    all_articles: list[RawArticle] = []
    successful: list[SourceOutcome] = []
    failed: list[SourceOutcome] = []
    for outcome in outcomes:
        if outcome.ok:
            _advance_watermark(db, outcome.source_id, outcome.articles)
            all_articles.extend(outcome.articles)
            successful.append(outcome)
            _log.info(
                "collect.source.ok",
                source_id=outcome.source_id,
                collected=len(outcome.articles),
            )
        else:
            assert outcome.error is not None
            _record_failure(db, outcome.source_id, outcome.error)
            failed.append(outcome)
            _log.warning(
                "collect.source.failed",
                source_id=outcome.source_id,
                error=str(outcome.error),
            )

    return CollectResult(articles=all_articles, successful=successful, failed=failed)
