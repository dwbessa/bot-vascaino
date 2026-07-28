"""CA-10 — LLM indisponível → run partial, nada publicado, watermark preservado."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vascobot.llm.base import LLMUnavailableError
from vascobot.llm.fake import FakeLLMProvider
from vascobot.llm.schemas import Categoria, Classificacao, ClassificacaoBatch
from vascobot.models import Article, ArticleStatus, Category, RunStatus
from vascobot.pipeline.classify import build_batch_prompt
from vascobot.pipeline.classify_pipeline import classify_articles
from vascobot.pipeline.degrade import ClassifyOutcome, classify_with_degradation

BRT = ZoneInfo("America/Sao_Paulo")


def _article(title: str, ext_id: str) -> Article:
    now = datetime(2026, 7, 27, 12, tzinfo=BRT)
    return Article(
        id=f"h-{ext_id}",
        source_id="netvasco",
        external_id=ext_id,
        url=f"https://x/{ext_id}",
        title=title,
        summary=None,
        body=None,
        published_at=now,
        fetched_at=now,
        content_hash="h",
        status=ArticleStatus.OK.value,
        run_id="r",
    )


@pytest.mark.acceptance
def test_ca10_llm_outage_degrades_safely() -> None:
    """LLM off → status partial, artigos sem prefixo em pending_review, watermark não avança."""
    arts = [
        _article("Sub-20: Vasco vence Cruzeiro", "1"),  # regra
        _article("Vasco vence o Bahia por 2 a 1", "2"),  # LLM (vai falhar)
        _article("SAF aprova balanço", "3"),  # LLM (vai falhar)
    ]

    fake = FakeLLMProvider(outage=True)
    outcome: ClassifyOutcome = asyncio.run(
        classify_with_degradation(
            arts,
            llm_provider=fake,
            llm_model="fake",
            include_institutional=True,
        ),
    )

    assert outcome.status is RunStatus.PARTIAL
    by_id = {c.article.external_id: c for c in outcome.classified}

    # regra resolveu o Sub-20 — segue normal
    assert by_id["1"].category is Category.BASE_SUB20
    assert by_id["1"].status == ArticleStatus.OK.value

    # Sem-prefixo viraram pending_review (não publicam nesta run)
    assert by_id["2"].status == ArticleStatus.PENDING_REVIEW.value
    assert by_id["3"].status == ArticleStatus.PENDING_REVIEW.value

    # E o watermark NÃO deve avançar para o que ficou pending
    stalled_ids = {c.article.external_id for c in outcome.classified if c.needs_reprocess}
    assert stalled_ids == {"2", "3"}


def test_reprocess_after_outage_reclassifies_pending() -> None:
    """Próxima execução com LLM voltando reclassifica os pending."""
    arts = [_article("Vasco vence o Bahia", "1")]

    fake_broken = FakeLLMProvider(outage=True)
    outcome1 = asyncio.run(
        classify_with_degradation(
            arts,
            llm_provider=fake_broken,
            llm_model="fake",
            include_institutional=True,
        ),
    )
    assert outcome1.status is RunStatus.PARTIAL

    # LLM voltou — reprocessa pendentes
    fake_ok = FakeLLMProvider()
    stalled = [c.article for c in outcome1.classified if c.needs_reprocess]
    reclassified = asyncio.run(
        _classify_now_ok(stalled, fake_ok, include_institutional=True),
    )
    assert reclassified[0].category is Category.PROFISSIONAL


async def _classify_now_ok(
    articles: list[Article],
    fake: FakeLLMProvider,
    *,
    include_institutional: bool,
) -> list[object]:
    """Helper — registra resposta ok e roda o pipeline direto (sem degradação)."""
    prompt = build_batch_prompt(articles, include_institutional=include_institutional)
    fake.register(
        prompt,
        ClassificacaoBatch(
            itens=[
                Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.9, motivo="ok")
                for _ in articles
            ],
        ),
    )
    return await classify_articles(
        articles,
        llm_provider=fake,
        llm_model="fake",
        include_institutional=include_institutional,
    )


def test_llm_ok_returns_status_ok() -> None:
    arts = [_article("Feminino: goleada", "1")]  # só regra, nem chama LLM
    fake = FakeLLMProvider()
    outcome = asyncio.run(
        classify_with_degradation(
            arts,
            llm_provider=fake,
            llm_model="fake",
            include_institutional=True,
        ),
    )
    assert outcome.status is RunStatus.OK
    assert not any(c.needs_reprocess for c in outcome.classified)


def test_llm_error_class_is_llm_unavailable() -> None:
    """Só p/ documentar o contrato — CA-10 depende dessa exceção."""
    assert issubclass(LLMUnavailableError, Exception)
