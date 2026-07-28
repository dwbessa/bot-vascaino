"""RF-11 / CA-10 — degradação segura quando o LLM está fora do ar.

Regra: nenhum artigo classificado só por regra pode ser afetado. Todo artigo
que dependia do LLM entra em `pending_review` com `needs_reprocess=True`, o
watermark **não** avança para eles, e o status da run vira `partial`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vascobot.llm.base import LLMProvider, LLMUnavailableError
from vascobot.models import Article, ArticleStatus, Category, ClassifyMethod, RunStatus
from vascobot.pipeline.classify_pipeline import ClassifiedArticle, classify_articles
from vascobot.pipeline.rules import classify_by_rules


@dataclass(frozen=True)
class ClassifiedArticleWithReprocess:
    article: Article
    category: Category
    confidence: float
    method: ClassifyMethod | None
    llm_model: str | None
    status: str
    motivo: str
    needs_reprocess: bool = False


@dataclass
class ClassifyOutcome:
    status: RunStatus
    classified: list[ClassifiedArticleWithReprocess] = field(default_factory=list)
    error: str | None = None


async def classify_with_degradation(
    articles: list[Article],
    *,
    llm_provider: LLMProvider,
    llm_model: str,
    include_institutional: bool,
    batch_size: int = 20,
    confidence_threshold: float = 0.7,
) -> ClassifyOutcome:
    """Roda o pipeline normal; se o LLM cair, degrada em vez de estourar."""
    try:
        classified: list[ClassifiedArticle] = await classify_articles(
            articles,
            llm_provider=llm_provider,
            llm_model=llm_model,
            include_institutional=include_institutional,
            batch_size=batch_size,
            confidence_threshold=confidence_threshold,
        )
    except LLMUnavailableError as exc:
        return _degrade(articles, error=str(exc))

    return ClassifyOutcome(
        status=RunStatus.OK,
        classified=[
            ClassifiedArticleWithReprocess(
                article=c.article,
                category=c.category,
                confidence=c.confidence,
                method=c.method,
                llm_model=c.llm_model,
                status=c.status,
                motivo=c.motivo,
                needs_reprocess=False,
            )
            for c in classified
        ],
    )


def _degrade(articles: list[Article], *, error: str) -> ClassifyOutcome:
    """LLM caiu: quem tinha regra segue, quem não tinha vira pending_review."""
    out: list[ClassifiedArticleWithReprocess] = []
    for art in articles:
        rule = classify_by_rules(art.title)
        if rule.category is not None:
            out.append(
                ClassifiedArticleWithReprocess(
                    article=art,
                    category=rule.category,
                    confidence=rule.confidence,
                    method=rule.method,
                    llm_model=None,
                    status=ArticleStatus.OK.value,
                    motivo=rule.matched or "",
                    needs_reprocess=False,
                ),
            )
        else:
            out.append(
                ClassifiedArticleWithReprocess(
                    article=art,
                    category=Category.DESCARTADO,  # placeholder — nunca publica
                    confidence=0.0,
                    method=None,
                    llm_model=None,
                    status=ArticleStatus.PENDING_REVIEW.value,
                    motivo="LLM indisponível — reprocessar",
                    needs_reprocess=True,
                ),
            )
    return ClassifyOutcome(status=RunStatus.PARTIAL, classified=out, error=error)


__all__ = [
    "ClassifiedArticleWithReprocess",
    "ClassifyOutcome",
    "classify_with_degradation",
]
