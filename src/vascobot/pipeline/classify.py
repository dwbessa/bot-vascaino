"""Classificador via LLM — camada 2 da RF-03.

Regras (plan.md §6.2, tasks.md T-016):
- Recebe apenas artigos que camada 0 e camada 1 não resolveram.
- Batch de até `batch_size` (default 20) manchetes por chamada.
- Prompt lê `prompts/classify.md` — não é template hardcoded.
- Passa D11 (`INCLUDE_INSTITUTIONAL`) via variável de prompt.
- Confiança < `confidence_threshold` → `pending_review`, não publica.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from vascobot.llm.base import LLMProvider
from vascobot.llm.schemas import Categoria, ClassificacaoBatch
from vascobot.models import Article, ArticleStatus, Category, ClassifyMethod

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "classify.md"

_INSTITUTIONAL_HINT_TRUE = (
    ", **e** pauta institucional (SAF, CEO, investidor, eleição, patrocínio, "
    "estádio, sócio-torcedor)"
)
_INSTITUTIONAL_HINT_FALSE = ""


@dataclass(frozen=True)
class ClassifyResult:
    """Saída por artigo — o que o pipeline vai persistir."""

    category: Category
    confidence: float
    method: ClassifyMethod
    llm_model: str
    motivo: str
    status: str  # ArticleStatus.value


def _load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_batch_prompt(articles: list[Article], *, include_institutional: bool) -> str:
    """Monta o prompt: instruções (arquivo) + lista JSON de manchetes."""
    template = _load_prompt_template()
    hint = _INSTITUTIONAL_HINT_TRUE if include_institutional else _INSTITUTIONAL_HINT_FALSE
    rendered = template.replace("{institutional_hint}", hint)

    items = [
        {
            "title": a.title,
            "summary": a.summary or "",
            "editoria": "",
            "url": a.url,
        }
        for a in articles
    ]
    return f"{rendered}\n\nEntrada:\n{json.dumps(items, ensure_ascii=False, indent=2)}"


class LLMClassifier:
    def __init__(
        self,
        provider: LLMProvider,
        model: str,
        *,
        batch_size: int = 20,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._provider = provider
        self._model = model
        self._batch_size = batch_size
        self._threshold = confidence_threshold

    async def classify(
        self,
        articles: list[Article],
        *,
        include_institutional: bool,
    ) -> dict[str, ClassifyResult]:
        out: dict[str, ClassifyResult] = {}
        for start in range(0, len(articles), self._batch_size):
            chunk = articles[start : start + self._batch_size]
            prompt = build_batch_prompt(chunk, include_institutional=include_institutional)
            batch = await self._provider.structured(
                prompt=prompt,
                schema=ClassificacaoBatch,
                model=self._model,
            )
            if len(batch.itens) != len(chunk):
                raise ValueError(
                    f"batch tem tamanho errado: pedi {len(chunk)}, veio {len(batch.itens)}",
                )
            for article, item in zip(chunk, batch.itens, strict=True):
                out[article.id] = ClassifyResult(
                    category=_categoria_to_category(item.categoria),
                    confidence=item.confianca,
                    method=ClassifyMethod.LLM,
                    llm_model=self._model,
                    motivo=item.motivo,
                    status=(
                        ArticleStatus.OK.value
                        if item.confianca >= self._threshold
                        else ArticleStatus.PENDING_REVIEW.value
                    ),
                )
        return out


def _categoria_to_category(c: Categoria) -> Category:
    return Category(c.value)


__all__ = ["ClassifyResult", "LLMClassifier", "build_batch_prompt"]
