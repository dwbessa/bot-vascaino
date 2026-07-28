"""Guardrails pós-LLM — plan.md §6.5, tasks.md T-021.

Três rejeições, todas → `pending_review`:
1. Overlap literal ≥ 10 palavras consecutivas com o corpo-fonte (RNF-07).
2. Nome próprio no bullet que não aparece em nenhum artigo do cluster.
3. Estouro de limite de caracteres da headline ou dos bullets.

Nenhum guardrail publica ou silencia — só devolve `GuardrailResult`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from vascobot.llm.schemas import ResumoCategoria
from vascobot.pipeline.dedupe import Cluster

MIN_LITERAL_WORDS = 10
HEADLINE_MAX = 80
BULLET_MAX = 140

_STOPWORDS_CAP: set[str] = {
    "vasco",
    "cruzmaltino",
    "cruz-maltino",
    "gigante",
    "colina",
    "sao",
    "januario",
    "brasileirao",
    "carioca",
    "copa",
    "sul",
    "americana",
    "libertadores",
    "brasil",
    "bahia",  # nomes de times comuns entram no corpus por padrão do domínio
    "flamengo",
    "botafogo",
    "fluminense",
}


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize(text))


def literal_overlap_ok(bullet: str, source_bodies: list[str]) -> bool:
    """Retorna False se houver ≥ MIN_LITERAL_WORDS consecutivas iguais a alguma fonte."""
    bullet_words = _words(bullet)
    if len(bullet_words) < MIN_LITERAL_WORDS:
        return True
    windows = {
        " ".join(bullet_words[i : i + MIN_LITERAL_WORDS])
        for i in range(len(bullet_words) - MIN_LITERAL_WORDS + 1)
    }
    for body in source_bodies:
        body_norm = " ".join(_words(body))
        for window in windows:
            if window in body_norm:
                return False
    return True


def _proper_nouns_in(text: str) -> set[str]:
    return {
        _normalize(w)
        for w in re.findall(r"\b[A-ZÁÂÃÉÊÍÓÔÕÚÇ][A-Za-zÁ-Úá-ú-]{2,}\b", text)
        if _normalize(w) not in _STOPWORDS_CAP
    }


def proper_nouns_grounded(bullet: str, clusters: list[Cluster]) -> bool:
    """Todo nome próprio do bullet deve aparecer em algum campo dos artigos do cluster."""
    names = _proper_nouns_in(bullet)
    if not names:
        return True
    corpus_parts: list[str] = []
    for c in clusters:
        for item in c.items:
            corpus_parts.append(item.article.title)
            corpus_parts.append(item.article.summary or "")
            corpus_parts.append(item.article.body or "")
    corpus = _normalize(" ".join(corpus_parts))
    return all(name in corpus for name in names)


@dataclass(frozen=True)
class GuardrailResult:
    passed: bool
    reason: str


def check_summary(
    summary: ResumoCategoria,
    *,
    source_bodies: list[str],
    clusters: list[Cluster],
) -> GuardrailResult:
    if len(summary.headline) > HEADLINE_MAX:
        return GuardrailResult(False, f"headline acima do limite ({len(summary.headline)})")
    for i, bullet in enumerate(summary.bullets):
        if len(bullet) > BULLET_MAX:
            return GuardrailResult(False, f"bullet #{i} acima do limite ({len(bullet)})")
        if not literal_overlap_ok(bullet, source_bodies):
            return GuardrailResult(
                False, f"bullet #{i} copia trecho literal ≥ {MIN_LITERAL_WORDS} palavras"
            )
        if not proper_nouns_grounded(bullet, clusters):
            missing = _proper_nouns_in(bullet) - _proper_nouns_in(
                " ".join(
                    (item.article.title + " " + (item.article.body or ""))
                    for c in clusters
                    for item in c.items
                ),
            )
            return GuardrailResult(
                False, f"bullet #{i} cita nome fora do cluster: {sorted(missing)}"
            )
    return GuardrailResult(True, "")


__all__ = ["GuardrailResult", "check_summary", "literal_overlap_ok", "proper_nouns_grounded"]
