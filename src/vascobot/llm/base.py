"""Interface LLMProvider — plan.md §6.3."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMUnavailableError(Exception):
    """Levantada quando o provedor está fora do ar (RF-11 → run partial, CA-10)."""


class LLMError(Exception):
    """Falha genérica do provider — schema inválido, erro persistente etc."""


class LLMProvider(ABC):
    """Contrato mínimo: uma chamada, structured output validado por Pydantic."""

    @abstractmethod
    async def structured(
        self,
        prompt: str,
        schema: type[T],
        model: str,
        temperature: float = 0.0,
    ) -> T:
        """Chama o modelo com `prompt` e devolve instância validada de `schema`."""
