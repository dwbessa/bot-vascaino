"""FakeLLMProvider — testes de LLM sem rede (CLAUDE.md §0.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from vascobot.llm.base import LLMProvider, LLMUnavailableError

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class RecordedCall:
    prompt: str
    schema: str
    model: str
    temperature: float


class FakeLLMProvider(LLMProvider):
    """Respostas pré-registradas por prompt. Opcionalmente simula outage."""

    def __init__(
        self,
        responses: dict[str, BaseModel] | None = None,
        *,
        outage: bool = False,
    ) -> None:
        self._responses: dict[str, BaseModel] = dict(responses or {})
        self._outage = outage
        self.calls: list[RecordedCall] = []

    def register(self, prompt: str, response: BaseModel) -> None:
        self._responses[prompt] = response

    def set_outage(self, *, outage: bool) -> None:
        self._outage = outage

    async def structured(
        self,
        prompt: str,
        schema: type[T],
        model: str,
        temperature: float = 0.0,
    ) -> T:
        self.calls.append(
            RecordedCall(
                prompt=prompt,
                schema=schema.__name__,
                model=model,
                temperature=temperature,
            ),
        )
        if self._outage:
            raise LLMUnavailableError("fake outage")
        try:
            response = self._responses[prompt]
        except KeyError as exc:
            msg = f"FakeLLMProvider: sem resposta registrada para prompt {prompt!r}"
            raise KeyError(msg) from exc
        if not isinstance(response, schema):
            msg = f"resposta registrada é {type(response).__name__}, prompt pediu {schema.__name__}"
            raise TypeError(msg)
        return response


__all__ = ["FakeLLMProvider", "RecordedCall"]
