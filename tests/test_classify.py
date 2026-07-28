"""Classificador LLM em batch — T-016."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vascobot.llm.fake import FakeLLMProvider
from vascobot.llm.schemas import Categoria, Classificacao, ClassificacaoBatch
from vascobot.models import Article, ArticleStatus, Category
from vascobot.pipeline.classify import LLMClassifier, build_batch_prompt

BRT = ZoneInfo("America/Sao_Paulo")


def _article(title: str, source: str = "netvasco", ext_id: str = "1") -> Article:
    now = datetime(2026, 7, 27, 12, tzinfo=BRT)
    return Article(
        id=f"hash-{ext_id}",
        source_id=source,
        external_id=ext_id,
        url=f"https://x/y/{ext_id}",
        title=title,
        summary=None,
        body=None,
        published_at=now,
        fetched_at=now,
        content_hash="h",
        status=ArticleStatus.OK.value,
        run_id="run1",
    )


def _batch(items: list[Classificacao]) -> ClassificacaoBatch:
    return ClassificacaoBatch(itens=items)


def test_build_prompt_includes_titles() -> None:
    arts = [_article("Vasco vence", ext_id="1"), _article("SAF aprova", ext_id="2")]
    prompt = build_batch_prompt(arts, include_institutional=True)
    assert "Vasco vence" in prompt
    assert "SAF aprova" in prompt


def test_include_institutional_flag_changes_prompt() -> None:
    a = [_article("saf", ext_id="1")]
    with_inst = build_batch_prompt(a, include_institutional=True)
    without_inst = build_batch_prompt(a, include_institutional=False)
    assert with_inst != without_inst
    assert "institucional" in with_inst.lower() or "saf" in with_inst.lower()


def test_classifier_returns_map_by_article_id() -> None:
    arts = [
        _article("Vasco vence Bahia", ext_id="1"),
        _article("Feminino: goleada", ext_id="2"),
    ]
    resp = _batch(
        [
            Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.9, motivo="jogo"),
            Classificacao(categoria=Categoria.FEMININO, confianca=0.95, motivo="prefixo"),
        ]
    )
    fake = FakeLLMProvider()
    prompt = build_batch_prompt(arts, include_institutional=True)
    fake.register(prompt, resp)

    clf = LLMClassifier(provider=fake, model="fake", batch_size=20)
    out = asyncio.run(clf.classify(arts, include_institutional=True))
    assert out["hash-1"].category is Category.PROFISSIONAL
    assert out["hash-2"].category is Category.FEMININO
    assert out["hash-1"].method.value == "llm"


def test_classifier_splits_into_batches() -> None:
    arts = [_article(f"h{i}", ext_id=str(i)) for i in range(45)]
    fake = FakeLLMProvider()
    # 3 batches: 20+20+5
    for start in (0, 20, 40):
        chunk = arts[start : start + 20]
        prompt = build_batch_prompt(chunk, include_institutional=True)
        fake.register(
            prompt,
            _batch(
                [
                    Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.8, motivo="x")
                    for _ in chunk
                ]
            ),
        )

    clf = LLMClassifier(provider=fake, model="fake", batch_size=20)
    out = asyncio.run(clf.classify(arts, include_institutional=True))
    assert len(out) == 45
    assert len(fake.calls) == 3


def test_classifier_marks_low_confidence_as_pending_review() -> None:
    arts = [_article("ambígua", ext_id="1")]
    resp = _batch(
        [
            Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.5, motivo="incerto"),
        ]
    )
    fake = FakeLLMProvider()
    prompt = build_batch_prompt(arts, include_institutional=True)
    fake.register(prompt, resp)

    clf = LLMClassifier(provider=fake, model="fake", batch_size=20, confidence_threshold=0.7)
    out = asyncio.run(clf.classify(arts, include_institutional=True))
    result = out["hash-1"]
    assert result.status == ArticleStatus.PENDING_REVIEW.value
    assert result.confidence == 0.5


def test_classifier_rejects_wrong_size_batch_response() -> None:
    arts = [_article("a", ext_id="1"), _article("b", ext_id="2")]
    resp = _batch(
        [
            Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.9, motivo="só um"),
        ]
    )
    fake = FakeLLMProvider()
    prompt = build_batch_prompt(arts, include_institutional=True)
    fake.register(prompt, resp)

    clf = LLMClassifier(provider=fake, model="fake", batch_size=20)
    with pytest.raises(ValueError, match="tamanho"):
        asyncio.run(clf.classify(arts, include_institutional=True))


def test_saf_headline_with_institutional_true_maps_to_profissional() -> None:
    """D11 — INCLUDE_INSTITUTIONAL=true → SAF/CEO cai em profissional."""
    arts = [_article("SAF aprova balanço com receita recorde", ext_id="1")]
    resp = _batch(
        [
            Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.85, motivo="SAF"),
        ]
    )
    fake = FakeLLMProvider()
    prompt = build_batch_prompt(arts, include_institutional=True)
    fake.register(prompt, resp)

    clf = LLMClassifier(provider=fake, model="fake", batch_size=20)
    out = asyncio.run(clf.classify(arts, include_institutional=True))
    assert out["hash-1"].category is Category.PROFISSIONAL
