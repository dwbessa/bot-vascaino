"""Sumarizador por categoria — plan.md §6.5.

Uma chamada de LLM por categoria (não por cluster). Entrada = clusters já
priorizados (T-019b), canônico de cada. Corpo truncado em ~800 chars por artigo
p/ não estourar contexto barato.
"""

from __future__ import annotations

import json
from pathlib import Path

from vascobot.llm.base import LLMProvider
from vascobot.llm.schemas import ResumoCategoria
from vascobot.models import Category
from vascobot.pipeline.dedupe import Cluster

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "summarize.md"
_BODY_TRUNCATE = 800


def _load_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_summarize_prompt(category: Category, clusters: list[Cluster]) -> str:
    template = _load_template().replace("{categoria}", category.value)
    items = [
        {
            "title": c.canonical.article.title,
            "summary": (c.canonical.article.summary or "").strip(),
            "excerpt": (c.canonical.article.body or "")[:_BODY_TRUNCATE],
            "url": c.canonical.article.url,
        }
        for c in clusters
    ]
    return f"{template}\n\nArtigos:\n{json.dumps(items, ensure_ascii=False, indent=2)}"


class Summarizer:
    def __init__(self, provider: LLMProvider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def summarize(
        self,
        category: Category,
        clusters: list[Cluster],
    ) -> ResumoCategoria | None:
        if not clusters:
            return None
        prompt = build_summarize_prompt(category, clusters)
        return await self._provider.structured(
            prompt=prompt,
            schema=ResumoCategoria,
            model=self._model,
        )


__all__ = ["Summarizer", "build_summarize_prompt"]
