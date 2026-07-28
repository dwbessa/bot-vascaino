"""Schemas de saída do LLM — Pydantic v2, validados pelo Ollama no decoding."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Categoria(StrEnum):
    """Cópia da Category do domínio — o LLM devolve o enum como string."""

    PROFISSIONAL = "profissional"
    FEMININO = "feminino"
    BASE_SUB20 = "base_sub20"
    BASE_SUB17 = "base_sub17"
    BASE_SUB15 = "base_sub15"
    DESCARTADO = "descartado"


class Classificacao(BaseModel):
    categoria: Categoria
    confianca: float = Field(ge=0.0, le=1.0)
    motivo: str = Field(max_length=200)


class ClassificacaoBatch(BaseModel):
    """Batch de saída — 1 item por manchete de entrada, mesma ordem."""

    itens: list[Classificacao]


class ResumoCategoria(BaseModel):
    headline: str = Field(max_length=80)
    bullets: list[str] = Field(default_factory=list, max_length=2)
