"""Pipeline de classificação camadas 0 → 1 → 2 (unit, sem rede)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from vascobot.llm.fake import FakeLLMProvider
from vascobot.llm.schemas import Categoria, Classificacao, ClassificacaoBatch
from vascobot.models import Article, ArticleStatus, Category, ClassifyMethod
from vascobot.pipeline.classify import build_batch_prompt
from vascobot.pipeline.classify_pipeline import ClassifiedArticle, classify_articles

BRT = ZoneInfo("America/Sao_Paulo")


def _article(title: str, ext_id: str) -> Article:
    now = datetime(2026, 7, 27, 12, tzinfo=BRT)
    return Article(
        id=f"h-{ext_id}",
        source_id="netvasco",
        external_id=ext_id,
        url=f"https://x/y/{ext_id}",
        title=title,
        summary=None,
        body=None,
        published_at=now,
        fetched_at=now,
        content_hash="h",
        status=ArticleStatus.OK.value,
        run_id="r",
    )


def test_rules_kill_before_llm() -> None:
    """Artigo pego pelas regras nunca vai pro LLM."""
    arts = [
        _article("Futsal Feminino Base: Sub-15", "1"),  # camada 0
        _article("Feminino: Vasco vence Fla", "2"),  # camada 1
    ]
    fake = FakeLLMProvider()
    out = asyncio.run(
        classify_articles(
            arts,
            llm_provider=fake,
            llm_model="fake",
            include_institutional=True,
        ),
    )
    assert out[0].category is Category.DESCARTADO
    assert out[0].method is ClassifyMethod.RULE_EXCLUSION
    assert out[1].category is Category.FEMININO
    assert out[1].method is ClassifyMethod.RULE_POSITIVE
    assert fake.calls == []  # LLM não foi chamado


def test_llm_called_only_for_no_prefix() -> None:
    arts = [
        _article("Sub-20: Vasco vence Cruzeiro", "1"),  # regra
        _article("Vasco vence o Bahia por 2 a 1", "2"),  # LLM
    ]
    fake = FakeLLMProvider()
    prompt = build_batch_prompt([arts[1]], include_institutional=True)
    fake.register(
        prompt,
        ClassificacaoBatch(
            itens=[Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.9, motivo="jogo")],
        ),
    )
    out = asyncio.run(
        classify_articles(
            arts,
            llm_provider=fake,
            llm_model="fake",
            include_institutional=True,
        ),
    )
    assert out[0].method is ClassifyMethod.RULE_POSITIVE
    assert out[1].method is ClassifyMethod.LLM
    assert out[1].category is Category.PROFISSIONAL
    assert len(fake.calls) == 1


def test_low_confidence_llm_marks_pending_review() -> None:
    arts = [_article("Vasco confirma reforço misterioso", "1")]
    fake = FakeLLMProvider()
    prompt = build_batch_prompt(arts, include_institutional=True)
    fake.register(
        prompt,
        ClassificacaoBatch(
            itens=[
                Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.5, motivo="incerto"),
            ],
        ),
    )
    out = asyncio.run(
        classify_articles(
            arts,
            llm_provider=fake,
            llm_model="fake",
            include_institutional=True,
            confidence_threshold=0.7,
        ),
    )
    assert out[0].status == ArticleStatus.PENDING_REVIEW.value


def test_preserves_input_order() -> None:
    arts = [
        _article("Vasco vence Bahia", "a"),  # LLM
        _article("Sub-15: Vasco vence Cruzeiro", "b"),  # regra
        _article("Vasco anuncia patrocinador", "c"),  # LLM
    ]
    fake = FakeLLMProvider()
    llm_chunk = [arts[0], arts[2]]
    prompt = build_batch_prompt(llm_chunk, include_institutional=True)
    fake.register(
        prompt,
        ClassificacaoBatch(
            itens=[
                Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.9, motivo="a"),
                Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.85, motivo="c"),
            ],
        ),
    )
    out = asyncio.run(
        classify_articles(
            arts,
            llm_provider=fake,
            llm_model="fake",
            include_institutional=True,
        ),
    )
    assert [c.article.external_id for c in out] == ["a", "b", "c"]


def test_returns_typed_dataclass() -> None:
    arts = [_article("Basquete: Vasco vence", "1")]
    fake = FakeLLMProvider()
    out = asyncio.run(
        classify_articles(arts, llm_provider=fake, llm_model="fake", include_institutional=True),
    )
    assert isinstance(out[0], ClassifiedArticle)
