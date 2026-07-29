"""LLMProvider iface + fake provider — T-013."""

from __future__ import annotations

import asyncio

import pytest

from vascobot.llm.base import LLMProvider, LLMUnavailableError
from vascobot.llm.fake import FakeLLMProvider
from vascobot.llm.schemas import Categoria, Classificacao, ResumoCategoria
from vascobot.models import Category


def test_categoria_enum_matches_domain() -> None:
    """Enum de saída do LLM tem que bater com Category do domínio."""
    assert {c.value for c in Categoria} == {c.value for c in Category}


def test_classificacao_schema_shape() -> None:
    c = Classificacao(categoria=Categoria.PROFISSIONAL, confianca=0.9, motivo="tem 'Vasco vence'")
    assert c.categoria is Categoria.PROFISSIONAL
    assert 0.0 <= c.confianca <= 1.0


def test_classificacao_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError, match="confianca"):
        Classificacao(categoria=Categoria.PROFISSIONAL, confianca=1.5, motivo="x")


def test_resumo_categoria_shape() -> None:
    r = ResumoCategoria(headline="Vasco vence Bahia", bullets=["b1", "b2"])
    assert len(r.bullets) <= 2
    assert len(r.headline) <= 80


def test_resumo_categoria_rejects_too_many_bullets() -> None:
    with pytest.raises(ValueError):
        ResumoCategoria(headline="h", bullets=["a", "b", "c"])


def test_resumo_categoria_allows_long_headline() -> None:
    """Sem limite de tamanho no schema — o compose trunca por plataforma.

    Output de LLM poucos chars acima não pode estourar a validação e derrubar
    a categoria.
    """
    r = ResumoCategoria(headline="x" * 120, bullets=[])
    assert len(r.headline) == 120


def test_fake_provider_returns_pre_seeded_response() -> None:
    fake = FakeLLMProvider(
        responses={
            "class": Classificacao(
                categoria=Categoria.PROFISSIONAL,
                confianca=0.95,
                motivo="teste",
            ),
        },
    )
    out = asyncio.run(fake.structured(prompt="class", schema=Classificacao, model="fake"))
    assert isinstance(out, Classificacao)
    assert out.categoria is Categoria.PROFISSIONAL


def test_fake_provider_raises_when_no_response_registered() -> None:
    fake = FakeLLMProvider(responses={})
    with pytest.raises(KeyError):
        asyncio.run(fake.structured(prompt="whatever", schema=Classificacao, model="fake"))


def test_fake_provider_simulates_outage() -> None:
    fake = FakeLLMProvider(responses={}, outage=True)
    with pytest.raises(LLMUnavailableError):
        asyncio.run(fake.structured(prompt="x", schema=Classificacao, model="fake"))


def test_fake_provider_is_llmprovider_subclass() -> None:
    assert issubclass(FakeLLMProvider, LLMProvider)


def test_fake_provider_records_calls() -> None:
    fake = FakeLLMProvider(
        responses={
            "p1": Classificacao(categoria=Categoria.FEMININO, confianca=0.8, motivo="x"),
        },
    )
    asyncio.run(fake.structured(prompt="p1", schema=Classificacao, model="fake"))
    assert len(fake.calls) == 1
    assert fake.calls[0].prompt == "p1"
    assert fake.calls[0].model == "fake"
