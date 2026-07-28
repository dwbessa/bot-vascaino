"""Pipeline completo de classificação: camadas 0 → 1 → 2.

- Camada 0 (rules exclusion): sempre primeiro. Nunca vai ao LLM.
- Camada 1 (rules positive): resolve prefixos determinísticos.
- Camada 2 (LLM): resolve o resto (~60% do volume real).
"""

from __future__ import annotations

from dataclasses import dataclass

from vascobot.llm.base import LLMProvider
from vascobot.models import Article, ArticleStatus, Category, ClassifyMethod
from vascobot.pipeline.classify import ClassifyResult, LLMClassifier
from vascobot.pipeline.rules import classify_by_rules


@dataclass(frozen=True)
class ClassifiedArticle:
    """O que o resto do pipeline enxerga: artigo + decisão da classificação."""

    article: Article
    category: Category
    confidence: float
    method: ClassifyMethod
    llm_model: str | None
    status: str  # ArticleStatus.value
    motivo: str


async def classify_articles(
    articles: list[Article],
    *,
    llm_provider: LLMProvider,
    llm_model: str,
    include_institutional: bool,
    batch_size: int = 20,
    confidence_threshold: float = 0.7,
) -> list[ClassifiedArticle]:
    """Encadeia as camadas. Devolve na mesma ordem da entrada."""
    layer2: list[Article] = []
    slots: list[ClassifiedArticle | None] = [None] * len(articles)

    for i, art in enumerate(articles):
        rule = classify_by_rules(art.title)
        if rule.category is not None:
            slots[i] = ClassifiedArticle(
                article=art,
                category=rule.category,
                confidence=rule.confidence,
                method=rule.method,  # type: ignore[arg-type]
                llm_model=None,
                status=ArticleStatus.OK.value,
                motivo=rule.matched or "",
            )
        else:
            layer2.append(art)

    if layer2:
        classifier = LLMClassifier(
            provider=llm_provider,
            model=llm_model,
            batch_size=batch_size,
            confidence_threshold=confidence_threshold,
        )
        results: dict[str, ClassifyResult] = await classifier.classify(
            layer2,
            include_institutional=include_institutional,
        )
        for i, art in enumerate(articles):
            if slots[i] is not None:
                continue
            res = results[art.id]
            slots[i] = ClassifiedArticle(
                article=art,
                category=res.category,
                confidence=res.confidence,
                method=res.method,
                llm_model=res.llm_model,
                status=res.status,
                motivo=res.motivo,
            )

    for i, slot in enumerate(slots):
        if slot is None:
            raise RuntimeError(f"artigo #{i} não classificado — bug de pipeline")

    return [slot for slot in slots if slot is not None]


__all__ = ["ClassifiedArticle", "classify_articles"]
