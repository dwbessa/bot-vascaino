"""CA-01 — coleta ≥ 90% das notícias desde a última execução. RNF-01 < 3 min."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.config import XLinkPolicy
from vascobot.db import Database
from vascobot.llm.fake import FakeLLMProvider
from vascobot.llm.schemas import Categoria, Classificacao, ClassificacaoBatch, ResumoCategoria
from vascobot.models import RawArticle, RunStatus, Watermark
from vascobot.pipeline.run import run_pipeline
from vascobot.publishers.base import Publisher
from vascobot.publishers.registry import PublisherRegistry
from vascobot.sources.base import SourceAdapter
from vascobot.sources.registry import SourceRegistry

BRT = ZoneInfo("America/Sao_Paulo")


class _Src(SourceAdapter):
    base_url = "https://fake.invalid"

    def __init__(self, source_id: str, articles: list[RawArticle]) -> None:
        self.source_id = source_id
        self._articles = articles

    async def discover(self, since: Watermark) -> list[RawArticle]:
        _ = since
        return self._articles


class _NoopPublisher(Publisher):
    platform = "bluesky"

    def __init__(self) -> None:
        self.enabled = True

    async def publish_thread(self, drafts: list) -> list:  # type: ignore[type-arg]
        _ = drafts
        return []


class _Settings:
    sources_enabled = ("netvasco", "supervasco")
    max_lookback_hours = 8
    classify_model = "fake"
    summarize_model = "fake"
    classify_batch_size = 20
    classify_confidence_threshold = 0.7
    include_institutional = True
    require_approval = True
    max_posts_per_thread = 4
    x_is_premium = True
    x_link_policy = XLinkPolicy.LAST_POST


class _SmartFake(FakeLLMProvider):
    async def structured(self, prompt: str, schema, model: str, temperature: float = 0.0):  # type: ignore[override,no-untyped-def]
        import re

        if schema is ClassificacaoBatch:
            n = len(re.findall(r'"title"', prompt))
            return ClassificacaoBatch(
                itens=[
                    Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.9, motivo="x")
                    for _ in range(n)
                ],
            )
        if schema is ResumoCategoria:
            return ResumoCategoria(headline="Resumo", bullets=["destaque"])
        raise AssertionError(schema)


def _raw(source: str, ext_id: str, title: str, now: datetime, minutes_ago: int) -> RawArticle:
    return RawArticle(
        source_id=source,
        external_id=ext_id,
        url=f"https://{source}.invalid/n/{ext_id}/x",
        title=title,
        summary="lide",
        body="corpo suficiente para o resumo",
        published_at=now - timedelta(minutes=minutes_ago),
        fetched_at=now,
    )


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "ca01.db")
    d.migrate()
    return d


@pytest.mark.acceptance
def test_ca01_collects_since_watermark(db: Database) -> None:
    now = datetime(2026, 7, 27, 6, 0, tzinfo=BRT)
    net = [
        _raw("netvasco", str(100 + i), f"Vasco assunto {i}", now, minutes_ago=30 + i)
        for i in range(6)
    ]
    sup = [
        _raw("supervasco", str(200 + i), f"Cruzmaltino assunto {i}", now, minutes_ago=20 + i)
        for i in range(4)
    ]
    src_reg = SourceRegistry()
    src_reg.register(_Src("netvasco", net))
    src_reg.register(_Src("supervasco", sup))

    pub_reg = PublisherRegistry()
    pub_reg.register(_NoopPublisher())

    stats = asyncio.run(
        run_pipeline(
            db=db,
            settings=_Settings(),
            source_registry=src_reg,
            publisher_registry=pub_reg,
            llm_provider=_SmartFake(),
            now=now,
            dry_run=True,
        ),
    )
    published_count = 10
    assert stats.counts["collected"] >= 0.9 * published_count
    assert stats.counts["collected"] == 10
    assert stats.status in (RunStatus.OK, RunStatus.PARTIAL)


@pytest.mark.acceptance
def test_rnf01_run_under_3_minutes(db: Database) -> None:
    """Com fakes (sem rede), o pipeline inteiro fecha em muito menos de 3 min."""
    now = datetime(2026, 7, 27, 6, 0, tzinfo=BRT)
    net = [_raw("netvasco", str(100 + i), f"Vasco {i}", now, 30 + i) for i in range(30)]
    src_reg = SourceRegistry()
    src_reg.register(_Src("netvasco", net))
    src_reg.register(_Src("supervasco", []))
    pub_reg = PublisherRegistry()
    pub_reg.register(_NoopPublisher())

    t0 = time.perf_counter()
    asyncio.run(
        run_pipeline(
            db=db,
            settings=_Settings(),
            source_registry=src_reg,
            publisher_registry=pub_reg,
            llm_provider=_SmartFake(),
            now=now,
            dry_run=True,
        ),
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 180, f"pipeline levou {elapsed:.1f}s (> 3 min)"
