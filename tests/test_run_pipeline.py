"""Pipeline fim-a-fim — T-029 (CA-01, RNF-01, janela CA-07)."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.config import XLinkPolicy
from vascobot.db import Database
from vascobot.llm.fake import FakeLLMProvider
from vascobot.llm.schemas import Categoria, Classificacao, ClassificacaoBatch, ResumoCategoria
from vascobot.models import RawArticle, RunStatus, Watermark
from vascobot.pipeline.run import compute_window, run_pipeline
from vascobot.publishers.base import Publisher
from vascobot.publishers.registry import PublisherRegistry
from vascobot.sources.base import SourceAdapter
from vascobot.sources.registry import SourceRegistry

BRT = ZoneInfo("America/Sao_Paulo")


class _Source(SourceAdapter):
    source_id = "fakesrc"
    base_url = "https://fake.invalid"

    def __init__(self, articles: list[RawArticle]) -> None:
        self._articles = articles

    async def discover(self, since: Watermark) -> list[RawArticle]:
        _ = since
        return self._articles


class _CapturingPublisher(Publisher):
    platform = "bluesky"

    def __init__(self) -> None:
        self.enabled = True
        self.threads: list[list] = []

    async def publish_thread(self, drafts: list) -> list:  # type: ignore[type-arg]
        self.threads.append(drafts)
        return []


def _raw(ext_id: str, title: str, *, minutes_ago: int, now: datetime) -> RawArticle:
    published = now - timedelta(minutes=minutes_ago)
    return RawArticle(
        source_id="fakesrc",
        external_id=ext_id,
        url=f"https://fake.invalid/n/{ext_id}/x",
        title=title,
        summary="lide",
        body="corpo do artigo com detalhes suficientes",
        published_at=published,
        fetched_at=now,
    )


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "run.db")
    d.migrate()
    return d


def test_compute_window_overnight_covers_0200() -> None:
    """CA-07 (lógica): run das 06:00 com lookback 8h cobre 02:00 (e 22:00 do dia anterior)."""
    now = datetime(2026, 7, 27, 6, 0, tzinfo=BRT)
    start, end = compute_window(now, lookback_hours=8)
    assert end == now
    assert start == datetime(2026, 7, 26, 22, 0, tzinfo=BRT)
    news_0200 = datetime(2026, 7, 27, 2, 0, tzinfo=BRT)
    assert start <= news_0200 <= end


def test_ca01_collects_all_articles(db: Database) -> None:
    now = datetime(2026, 7, 27, 6, 0, tzinfo=BRT)
    articles = [
        _raw("1", "Vasco vence o Bahia por 2 a 1", minutes_ago=60, now=now),
        _raw("2", "Vasco anuncia novo patrocinador", minutes_ago=120, now=now),
        _raw("3", "Feminino: Vasco goleia rival", minutes_ago=30, now=now),
    ]
    src_reg = SourceRegistry()
    src_reg.register(_Source(articles))

    pub_reg = PublisherRegistry()
    pub = _CapturingPublisher()
    pub_reg.register(pub)

    stats = asyncio.run(
        run_pipeline(
            db=db,
            settings=_FakeSettings(),
            source_registry=src_reg,
            publisher_registry=pub_reg,
            llm_provider=_SmartFake(),
            now=now,
            dry_run=True,
        ),
    )
    # CA-01 — coletou os 3 (≥ 90%)
    assert stats.counts["collected"] == 3
    assert stats.status in (RunStatus.OK, RunStatus.PARTIAL)


def test_dry_run_does_not_publish(db: Database) -> None:
    now = datetime(2026, 7, 27, 6, 0, tzinfo=BRT)
    articles = [_raw("1", "Feminino: Vasco goleia", minutes_ago=30, now=now)]
    src_reg = SourceRegistry()
    src_reg.register(_Source(articles))
    pub_reg = PublisherRegistry()
    pub = _CapturingPublisher()
    pub_reg.register(pub)

    asyncio.run(
        run_pipeline(
            db=db,
            settings=_FakeSettings(),
            source_registry=src_reg,
            publisher_registry=pub_reg,
            llm_provider=_SmartFake(),
            now=now,
            dry_run=True,
        ),
    )
    assert pub.threads == []


def test_run_persists_stats_json(db: Database) -> None:
    now = datetime(2026, 7, 27, 6, 0, tzinfo=BRT)
    articles = [_raw("1", "Feminino: Vasco goleia", minutes_ago=30, now=now)]
    src_reg = SourceRegistry()
    src_reg.register(_Source(articles))
    pub_reg = PublisherRegistry()
    pub_reg.register(_CapturingPublisher())

    stats = asyncio.run(
        run_pipeline(
            db=db,
            settings=_FakeSettings(),
            source_registry=src_reg,
            publisher_registry=pub_reg,
            llm_provider=_SmartFake(),
            now=now,
            dry_run=True,
        ),
    )
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status, stats_json FROM runs WHERE id=?",
            (stats.run_id,),
        ).fetchone()
    assert row is not None
    assert row[0] in ("ok", "partial")
    parsed = json.loads(row[1])
    assert "collected" in parsed["counts"]


def test_llm_outage_makes_run_partial(db: Database) -> None:
    now = datetime(2026, 7, 27, 6, 0, tzinfo=BRT)
    articles = [_raw("1", "Vasco vence o Bahia", minutes_ago=30, now=now)]
    src_reg = SourceRegistry()
    src_reg.register(_Source(articles))
    pub_reg = PublisherRegistry()
    pub = _CapturingPublisher()
    pub_reg.register(pub)

    outage = FakeLLMProvider(outage=True)
    stats = asyncio.run(
        run_pipeline(
            db=db,
            settings=_FakeSettings(),
            source_registry=src_reg,
            publisher_registry=pub_reg,
            llm_provider=outage,
            now=now,
            dry_run=True,
        ),
    )
    assert stats.status is RunStatus.PARTIAL
    assert pub.threads == []


# --------------------------------------------------------------------- helpers
class _FakeSettings:
    """Config mínima que o run_pipeline consome (evita montar Settings real)."""

    sources_enabled = ("fakesrc",)
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
    """Fake que responde a qualquer prompt: classificação → profissional, resumo → 1 bullet."""

    async def structured(self, prompt: str, schema, model: str, temperature: float = 0.0):  # type: ignore[override,no-untyped-def]
        if schema is ClassificacaoBatch:
            n = len(re.findall(r'"title"', prompt))
            return ClassificacaoBatch(
                itens=[
                    Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.9, motivo="x")
                    for _ in range(n)
                ],
            )
        if schema is ResumoCategoria:
            return ResumoCategoria(headline="Resumo do dia", bullets=["um destaque"])
        raise AssertionError(f"schema inesperado: {schema}")
