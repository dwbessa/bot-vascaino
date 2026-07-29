"""OllamaCloudProvider — cliente para Ollama Cloud (e local).

Detalhes decisivos (research.md §4.2):
- `format=Schema.model_json_schema()` — o servidor valida o schema **durante a
  decodificação**, o que elimina a maior parte do parse defensivo.
- Passar o schema também no prompt, além do campo `format`.
- `temperature=0` para reprodutibilidade.
- Retry com backoff em erros transientes; fim das tentativas → `LLMUnavailableError`,
  que dispara a degradação do RF-11 (CA-10).

O construtor aceita `client: AsyncClient | None`. Se None, cria com base em
`Settings.ollama_host` e `ollama_api_key`. Assim testes passam um fake sem rede.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

import httpx
from ollama import AsyncClient
from pydantic import BaseModel, ValidationError

from vascobot.llm.base import LLMError, LLMProvider, LLMUnavailableError

if TYPE_CHECKING:
    from vascobot.config import Settings

T = TypeVar("T", bound=BaseModel)

# Timeout por chamada ao Ollama Cloud. Modelo grande + cold start pode levar
# ~1 min; damos folga, mas nunca "infinito".
REQUEST_TIMEOUT_S = 120.0


class _ChatClient(Protocol):
    async def chat(self, **kwargs: Any) -> Any: ...


class OllamaCloudProvider(LLMProvider):
    def __init__(
        self,
        client: _ChatClient | None = None,
        *,
        retries: int = 3,
        backoff: float = 0.5,
    ) -> None:
        self._client = client
        self._retries = retries
        self._backoff = backoff

    @classmethod
    def from_settings(cls, settings: Settings) -> OllamaCloudProvider:
        raw_client = AsyncClient(
            host=settings.ollama_host,
            headers={"Authorization": f"Bearer {settings.ollama_api_key.get_secret_value()}"},
            # Timeout obrigatório: sem ele, uma conexão pendurada do Ollama Cloud
            # trava a run inteira pra sempre (e num cron, empilha execuções).
            # Estoura → retry com backoff → LLMUnavailableError → degrada.
            timeout=REQUEST_TIMEOUT_S,
        )
        # `AsyncClient.chat` tem overloads que não batem com o Protocol simples;
        # o cast é seguro — só chamamos a assinatura kwargs-only.
        return cls(client=raw_client)  # type: ignore[arg-type]

    async def structured(
        self,
        prompt: str,
        schema: type[T],
        model: str,
        temperature: float = 0.0,
    ) -> T:
        if self._client is None:
            raise LLMError("OllamaCloudProvider criado sem client — use from_settings()")

        schema_json = schema.model_json_schema()
        messages = [
            {
                "role": "system",
                "content": (
                    "Você devolve APENAS JSON válido, aderente ao schema abaixo. "
                    "Nada de texto fora do JSON.\n\n"
                    f"schema: {json.dumps(schema_json, ensure_ascii=False)}"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        options = {"temperature": temperature}

        last_transport_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.chat(
                    model=model,
                    messages=messages,
                    format=schema_json,
                    options=options,
                )
            except (TimeoutError, httpx.TransportError, httpx.HTTPError) as exc:
                last_transport_error = exc
                if attempt == self._retries:
                    break
                await asyncio.sleep(self._backoff * (2**attempt))
                continue

            return _decode(response, schema)

        assert last_transport_error is not None
        raise LLMUnavailableError(
            f"ollama unavailable: {last_transport_error}",
        ) from last_transport_error


def _decode[U: BaseModel](response: Any, schema: type[U]) -> U:
    """Extrai conteúdo (dict-like ou objeto) e valida contra o schema."""
    message = response["message"] if isinstance(response, dict) else response.message
    content = message["content"] if isinstance(message, dict) else message.content

    if isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"resposta não é JSON válido: {exc}") from exc
    else:
        payload = content

    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise LLMError(f"resposta não bate com o schema {schema.__name__}: {exc}") from exc


__all__ = ["OllamaCloudProvider"]
