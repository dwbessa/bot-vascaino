"""Pipeline fim-a-fim — T-029.

Encadeia as 7 etapas (plan.md §3), grava `runs.stats_json`, resolve o status
final (ok | partial | failed). A janela é calculada por watermark + lookback,
o que garante a cobertura overnight da CA-07.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import structlog

from vascobot.config import XLinkPolicy
from vascobot.db import Database
from vascobot.llm.base import LLMError, LLMProvider, LLMUnavailableError
from vascobot.models import (
    Article,
    Category,
    Digest,
    Platform,
    PostDraft,
    RunStats,
    RunStatus,
)
from vascobot.pipeline.classify_pipeline import ClassifiedArticle
from vascobot.pipeline.collect import collect
from vascobot.pipeline.compose import compose_thread
from vascobot.pipeline.dedupe import Cluster, cluster
from vascobot.pipeline.degrade import classify_with_degradation
from vascobot.pipeline.guardrails import check_summary
from vascobot.pipeline.normalize import normalize
from vascobot.pipeline.priority import rank_clusters
from vascobot.pipeline.summarize import Summarizer
from vascobot.publishers.registry import PublisherRegistry
from vascobot.repo import PostRepo
from vascobot.sources.registry import SourceRegistry

_log = structlog.get_logger(__name__)

# Quantos clusters (já priorizados) alimentam o resumo de cada categoria.
# Poucos → bullets e fontes ficam sobre o mesmo assunto e a thread não incha.
_SUMMARIZE_TOP_N = 5


class _SettingsLike(Protocol):
    sources_enabled: tuple[str, ...]
    max_lookback_hours: int
    classify_model: str
    summarize_model: str
    classify_batch_size: int
    classify_confidence_threshold: float
    include_institutional: bool
    require_approval: bool
    max_posts_per_thread: int
    x_is_premium: bool
    x_link_policy: XLinkPolicy


@dataclass
class _StageTimer:
    per_stage_ms: dict[str, int]

    def measure(self, name: str, started: float) -> None:
        self.per_stage_ms[name] = int((time.perf_counter() - started) * 1000)


def compute_window(now: datetime, *, lookback_hours: int) -> tuple[datetime, datetime]:
    """Janela [now - lookback, now]. Lookback de 8h fecha o vão overnight (CA-07)."""
    return now - timedelta(hours=lookback_hours), now


def _publishable(article_status: str) -> bool:
    return article_status == "ok"


async def run_pipeline(
    *,
    db: Database,
    settings: _SettingsLike,
    source_registry: SourceRegistry,
    publisher_registry: PublisherRegistry,
    llm_provider: LLMProvider,
    now: datetime,
    dry_run: bool = False,
) -> RunStats:
    run_id = uuid.uuid4().hex
    window_start, window_end = compute_window(now, lookback_hours=settings.max_lookback_hours)
    counts: dict[str, int] = {}
    costs: dict[str, float] = {}
    per_stage: dict[str, int] = {}
    timer = _StageTimer(per_stage)

    _open_run(db, run_id, now, window_start, window_end)

    # 1. COLLECT ------------------------------------------------------------
    t = time.perf_counter()
    collect_result = await collect(source_registry, db, source_ids=settings.sources_enabled)
    raw = collect_result.articles
    counts["collected"] = len(raw)
    counts["sources_failed"] = len(collect_result.failed)
    timer.measure("collect", t)

    # 2. NORMALIZE ----------------------------------------------------------
    t = time.perf_counter()
    articles: list[Article] = [normalize(r, run_id=run_id) for r in raw]
    timer.measure("normalize", t)

    # 3. CLASSIFY (0 → 1 → 2, com degradação) -------------------------------
    t = time.perf_counter()
    outcome = await classify_with_degradation(
        articles,
        llm_provider=llm_provider,
        llm_model=settings.classify_model,
        include_institutional=settings.include_institutional,
        batch_size=settings.classify_batch_size,
        confidence_threshold=settings.classify_confidence_threshold,
    )
    timer.measure("classify", t)

    run_status = RunStatus.OK if outcome.status is RunStatus.OK else RunStatus.PARTIAL
    counts["pending_review"] = sum(1 for c in outcome.classified if c.needs_reprocess)

    # Só o que é publicável (status ok, categoria != descartado) segue.
    keepers: list[ClassifiedArticle] = [
        ClassifiedArticle(
            article=c.article,
            category=c.category,
            confidence=c.confidence,
            method=c.method,  # type: ignore[arg-type]
            llm_model=c.llm_model,
            status=c.status,
            motivo=c.motivo,
        )
        for c in outcome.classified
        if _publishable(c.status) and c.category is not Category.DESCARTADO
    ]
    counts["descartado"] = sum(1 for c in outcome.classified if c.category is Category.DESCARTADO)
    counts["kept"] = len(keepers)

    # 4. DEDUPE -------------------------------------------------------------
    t = time.perf_counter()
    clusters = cluster(keepers)
    counts["clusters"] = len(clusters)
    timer.measure("dedupe", t)

    # 5+6. SUMMARIZE + guardrails por categoria -----------------------------
    t = time.perf_counter()
    digests = await _summarize_categories(
        clusters,
        summarizer=Summarizer(provider=llm_provider, model=settings.summarize_model),
        run_id=run_id,
        llm_model=settings.summarize_model,
    )
    counts["digests"] = len(digests)
    timer.measure("summarize", t)
    _persist_digests(db, digests)

    # 7. COMPOSE + persist drafts (+ publish se liberado) -------------------
    t = time.perf_counter()
    posts_by_platform = await _compose_and_route(
        db=db,
        settings=settings,
        publisher_registry=publisher_registry,
        digests=digests,
        run_id=run_id,
        dry_run=dry_run,
        run_status=run_status,
    )
    for platform, n in posts_by_platform.items():
        counts[f"posts_{platform}"] = n
    timer.measure("compose_publish", t)

    stats = RunStats(
        run_id=run_id,
        started_at=now,
        finished_at=datetime.now(tz=now.tzinfo),
        window_start=window_start,
        window_end=window_end,
        status=run_status,
        counts=counts,
        costs_usd=costs,
        per_stage_ms=per_stage,
    )
    _close_run(db, stats)
    _log.info("run.done", run_id=run_id, status=run_status.value, **counts)
    return stats


async def _summarize_categories(
    clusters: list[Cluster],
    *,
    summarizer: Summarizer,
    run_id: str,
    llm_model: str,
) -> list[Digest]:
    by_cat: dict[Category, list[Cluster]] = {}
    for c in clusters:
        by_cat.setdefault(c.canonical.category, []).append(c)

    digests: list[Digest] = []
    for category, cat_clusters in by_cat.items():
        ranked = rank_clusters(cat_clusters)
        # O sumarizador vê só os clusters de maior prioridade (RF-13). Isso mantém
        # os bullets e as `source_urls` falando do mesmo material — sem isso, o
        # LLM resume um assunto e as fontes exibidas eram de outro (jogo vs mercado).
        material = ranked[:_SUMMARIZE_TOP_N]
        try:
            resumo = await summarizer.summarize(category, material)
        except (LLMUnavailableError, LLMError) as exc:
            # Falha de LLM numa categoria não pode derrubar a run inteira nem
            # travá-la (o timeout do provider garante que "trava" vira erro).
            # Pula a categoria; as outras seguem.
            _log.warning("run.summarize_failed", category=category.value, error=str(exc))
            continue
        if resumo is None:
            continue
        source_bodies = [c.canonical.article.body or "" for c in material]
        guard = check_summary(resumo, source_bodies=source_bodies, clusters=material)
        if not guard.passed:
            _log.warning("run.guardrail_rejected", category=category.value, reason=guard.reason)
            continue
        digests.append(
            Digest(
                id=f"{run_id}-{category.value}",
                run_id=run_id,
                category=category,
                headline=resumo.headline,
                bullets=resumo.bullets,
                source_urls=[c.canonical.article.url for c in material],
                llm_model=llm_model,
            ),
        )
    return digests


async def _compose_and_route(
    *,
    db: Database,
    settings: _SettingsLike,
    publisher_registry: PublisherRegistry,
    digests: list[Digest],
    run_id: str,
    dry_run: bool,
    run_status: RunStatus,
) -> dict[str, int]:
    repo = PostRepo(db)
    counts: dict[str, int] = {}
    publish_now = not dry_run and not settings.require_approval and run_status is RunStatus.OK
    for publisher in publisher_registry.enabled():
        platform = Platform(publisher.platform)
        total = 0
        # Uma thread POR digest (categoria). Nunca juntar categorias na mesma
        # thread — cada uma é um post-raiz independente (D4).
        for digest in digests:
            drafts: list[PostDraft] = compose_thread(
                digest,
                platform=platform,
                run_id=run_id,
                x_is_premium=settings.x_is_premium,
                x_link_policy=settings.x_link_policy,
                max_posts=settings.max_posts_per_thread,
            )
            if not drafts:
                continue
            repo.save_drafts(drafts, require_approval=settings.require_approval)
            total += len(drafts)
            if publish_now:
                await publisher.publish_thread(drafts)
        counts[publisher.platform] = total
    return counts


def _open_run(
    db: Database,
    run_id: str,
    now: datetime,
    window_start: datetime,
    window_end: datetime,
) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO runs(id, started_at, window_start, window_end, status)"
            " VALUES (?, ?, ?, ?, ?)",
            (run_id, now.isoformat(), window_start.isoformat(), window_end.isoformat(), "running"),
        )


def _close_run(db: Database, stats: RunStats) -> None:
    payload = {
        "counts": stats.counts,
        "costs_usd": stats.costs_usd,
        "per_stage_ms": stats.per_stage_ms,
    }
    with db.connect() as conn:
        conn.execute(
            "UPDATE runs SET finished_at=?, status=?, stats_json=? WHERE id=?",
            (
                stats.finished_at.isoformat() if stats.finished_at else None,
                stats.status.value,
                json.dumps(payload, ensure_ascii=False),
                stats.run_id,
            ),
        )


def _persist_digests(db: Database, digests: list[Digest]) -> None:
    with db.connect() as conn:
        for d in digests:
            conn.execute(
                "INSERT INTO digests(id, run_id, category, headline, bullets_json,"
                " source_urls_json, llm_model) VALUES (?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(run_id, category) DO NOTHING",
                (
                    d.id,
                    d.run_id,
                    d.category.value,
                    d.headline,
                    json.dumps(d.bullets, ensure_ascii=False),
                    json.dumps(d.source_urls, ensure_ascii=False),
                    d.llm_model,
                ),
            )


__all__ = ["compute_window", "run_pipeline"]
