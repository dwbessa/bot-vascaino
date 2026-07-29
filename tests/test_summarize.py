"""Sumarizador — T-020."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vascobot.llm.fake import FakeLLMProvider
from vascobot.llm.schemas import ResumoCategoria
from vascobot.models import Article, ArticleStatus, Category
from vascobot.pipeline.classify_pipeline import ClassifiedArticle
from vascobot.pipeline.dedupe import Cluster
from vascobot.pipeline.summarize import Summarizer, build_summarize_prompt

BRT = ZoneInfo("America/Sao_Paulo")


def _cluster(headline: str, body: str = "corpo padrão") -> Cluster:
    now = datetime(2026, 7, 27, 12, tzinfo=BRT)
    art = Article(
        id=f"h-{headline[:10]}",
        source_id="netvasco",
        external_id="1",
        url="https://x/y/1",
        title=headline,
        summary=None,
        body=body,
        published_at=now,
        fetched_at=now,
        content_hash="h",
        status=ArticleStatus.OK.value,
        run_id="r",
    )
    ca = ClassifiedArticle(
        article=art,
        category=Category.PROFISSIONAL,
        confidence=0.9,
        method=None,  # type: ignore[arg-type]
        llm_model=None,
        status=ArticleStatus.OK.value,
        motivo="",
    )
    return Cluster(canonical=ca, items=[ca])


def test_prompt_names_category_and_titles() -> None:
    prompt = build_summarize_prompt(
        Category.PROFISSIONAL,
        [_cluster("Vasco vence Bahia")],
    )
    assert "profissional" in prompt.lower()
    assert "Vasco vence Bahia" in prompt


def test_prompt_truncates_long_body() -> None:
    prompt = build_summarize_prompt(
        Category.PROFISSIONAL,
        [_cluster("t", body="x" * 5000)],
    )
    assert len(prompt) < 5000


def test_summarizer_returns_digest_per_category() -> None:
    clusters = [_cluster("Vasco vence Bahia")]
    fake = FakeLLMProvider()
    prompt = build_summarize_prompt(Category.PROFISSIONAL, clusters)
    fake.register(
        prompt,
        ResumoCategoria(
            headline="Vasco vence o Bahia por 2 a 1",
            bullets=["Payet marcou dois", "Vasco sobe na tabela"],
        ),
    )
    s = Summarizer(provider=fake, model="fake")
    digest = asyncio.run(s.summarize(Category.PROFISSIONAL, clusters))
    assert digest is not None
    assert digest.headline.startswith("Vasco vence")
    assert len(digest.bullets) == 2


def test_summarizer_returns_none_when_no_clusters() -> None:
    fake = FakeLLMProvider()
    s = Summarizer(provider=fake, model="fake")
    digest = asyncio.run(s.summarize(Category.FEMININO, []))
    assert digest is None
    assert fake.calls == []


def test_summarizer_ok_with_empty_bullets() -> None:
    """Material insuficiente → prompt manda devolver bullets: []."""
    clusters = [_cluster("t", body="")]
    fake = FakeLLMProvider()
    prompt = build_summarize_prompt(Category.PROFISSIONAL, clusters)
    fake.register(prompt, ResumoCategoria(headline="Sem novidades", bullets=[]))
    s = Summarizer(provider=fake, model="fake")
    digest = asyncio.run(s.summarize(Category.PROFISSIONAL, clusters))
    assert digest is not None
    assert digest.bullets == []


def test_one_call_per_category() -> None:
    clusters = [_cluster("a"), _cluster("b"), _cluster("c")]
    fake = FakeLLMProvider()
    prompt = build_summarize_prompt(Category.PROFISSIONAL, clusters)
    fake.register(prompt, ResumoCategoria(headline="h", bullets=[]))
    s = Summarizer(provider=fake, model="fake")
    asyncio.run(s.summarize(Category.PROFISSIONAL, clusters))
    assert len(fake.calls) == 1


def test_digest_bullets_max_2_enforced() -> None:
    with pytest.raises(ValueError):
        ResumoCategoria(headline="ok", bullets=["a", "b", "c"])
