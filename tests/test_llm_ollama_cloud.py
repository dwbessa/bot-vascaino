"""OllamaCloudProvider — T-014.

Unit tests com fake client (zero rede). Testes de integração real (marca
`integration`) só rodam via `make integration`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from vascobot.llm.base import LLMError, LLMUnavailableError
from vascobot.llm.ollama_cloud import OllamaCloudProvider
from vascobot.llm.schemas import Categoria, Classificacao


class _FakeAsyncClient:
    """Substituto do `ollama.AsyncClient` para testes."""

    def __init__(
        self,
        response_content: str | None = None,
        raise_exc: Exception | None = None,
        raise_after: int | None = None,
    ) -> None:
        self._content = response_content
        self._raise = raise_exc
        self._raise_after = raise_after
        self.calls: list[dict[str, Any]] = []

    async def chat(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self._raise is not None:
            n_calls = len(self.calls)
            should_raise = self._raise_after is None or n_calls <= self._raise_after
            if should_raise:
                raise self._raise
        return {"message": {"content": self._content}}


def test_returns_validated_pydantic_model() -> None:
    fake = _FakeAsyncClient(
        response_content=json.dumps(
            {"categoria": "profissional", "confianca": 0.92, "motivo": "resultado do jogo"},
        ),
    )
    provider = OllamaCloudProvider(client=fake, retries=0)  # type: ignore[arg-type]

    out = asyncio.run(
        provider.structured(
            prompt="Classifique: Vasco vence Bahia",
            schema=Classificacao,
            model="gpt-oss:20b-cloud",
        ),
    )
    assert isinstance(out, Classificacao)
    assert out.categoria is Categoria.PROFISSIONAL
    assert out.confianca == 0.92


def test_passes_schema_and_temperature_to_client() -> None:
    fake = _FakeAsyncClient(
        response_content=json.dumps(
            {"categoria": "descartado", "confianca": 1.0, "motivo": "futsal"},
        ),
    )
    provider = OllamaCloudProvider(client=fake, retries=0)  # type: ignore[arg-type]
    asyncio.run(
        provider.structured(prompt="p", schema=Classificacao, model="qwen3.5", temperature=0.0),
    )

    call = fake.calls[0]
    assert call["model"] == "qwen3.5"
    assert call["options"]["temperature"] == 0.0
    assert call["format"] == Classificacao.model_json_schema()
    # schema também no prompt — research.md §4.2 diz que aumenta aderência
    joined = "\n".join(m["content"] for m in call["messages"])
    assert "categoria" in joined and "confianca" in joined


def test_retries_on_transient_and_succeeds() -> None:
    """Duas falhas transientes seguidas de sucesso — deve entregar."""
    fake = _FakeAsyncClient(
        response_content=json.dumps(
            {"categoria": "profissional", "confianca": 0.8, "motivo": "ok"},
        ),
        raise_exc=httpx.ConnectError("boom"),
        raise_after=2,
    )
    provider = OllamaCloudProvider(client=fake, retries=3, backoff=0.0)  # type: ignore[arg-type]
    out = asyncio.run(
        provider.structured(prompt="p", schema=Classificacao, model="m"),
    )
    assert out.categoria is Categoria.PROFISSIONAL
    assert len(fake.calls) == 3


def test_network_error_becomes_llm_unavailable_after_all_retries() -> None:
    fake = _FakeAsyncClient(raise_exc=httpx.ConnectError("no route"))
    provider = OllamaCloudProvider(client=fake, retries=2, backoff=0.0)  # type: ignore[arg-type]
    with pytest.raises(LLMUnavailableError):
        asyncio.run(provider.structured(prompt="p", schema=Classificacao, model="m"))
    assert len(fake.calls) == 3  # 1 tentativa + 2 retries


def test_invalid_json_raises_llm_error() -> None:
    fake = _FakeAsyncClient(response_content="{ not json")
    provider = OllamaCloudProvider(client=fake, retries=0)  # type: ignore[arg-type]
    with pytest.raises(LLMError):
        asyncio.run(provider.structured(prompt="p", schema=Classificacao, model="m"))


def test_json_that_violates_schema_raises_llm_error() -> None:
    """Confiança > 1 viola o schema — Pydantic reprova."""
    fake = _FakeAsyncClient(
        response_content=json.dumps(
            {"categoria": "profissional", "confianca": 1.5, "motivo": "x"},
        ),
    )
    provider = OllamaCloudProvider(client=fake, retries=0)  # type: ignore[arg-type]
    with pytest.raises(LLMError):
        asyncio.run(provider.structured(prompt="p", schema=Classificacao, model="m"))
