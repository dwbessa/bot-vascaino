"""Camadas 0 e 1 da classificação — determinísticas, plan.md §6.2.

Ordem obrigatória:
1. Camada 0 (exclusão) sempre roda antes. `Futsal Feminino Base` precisa
   morrer aqui, senão a camada 1 vai classificar como `feminino`.
2. Camada 1 (positiva) só roda se a camada 0 não bateu.
3. Se nenhuma bater → devolve `RuleOutcome(category=None)` — o LLM decide.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from vascobot.models import Category, ClassifyMethod

# ---------------------------------------------------------------- confidences
_CONF_EXCLUSION = 1.0
_CONF_POSITIVE = 0.95

# ---------------------------------------------------------------- CAMADA 0
# Padrões que **excluem** — modalidades fora de escopo e Sub-14/menores.
# Toda a comparação é feita sobre o título normalizado (lower + sem acento).
_EXCLUSION_PREFIXES = (
    r"^futsal(?:\s+feminino)?(?:\s+base)?\b",
    r"^futsal\s+base\b",
    r"^basquete\b",
    r"^basquete\s+feminino\b",
    r"^volei\b",
    r"^futevolei\b",
    r"^polo\s+aquatico\b",
    r"^natacao(?:\s+paralimpica)?\b",
    r"^remo\b",
    r"^atletismo\b",
    r"^judo\b",
    r"^e-?sports\b",
    r"^esports\b",
    r"^futmesa\b",
    r"^esporte\s+amador\b",
    r"^wallpaper\b",
    r"^blog\s+do\b",
    r"^efemeride\b",
    r"^ha\s+\d+\s+anos\b",  # notícia histórica
    r"^torcida\s+organizada\b",
    r"^sub-0[0-9]:",  # sub-00 ao sub-09
    r"^sub-1[0-4]:",  # sub-10 ao sub-14
)

# ---------------------------------------------------------------- CAMADA 1
_POSITIVE_PATTERNS: tuple[tuple[str, Category], ...] = (
    (r"^feminino:", Category.FEMININO),
    (r"^sub-20:", Category.BASE_SUB20),
    (r"^sub-1[67]:", Category.BASE_SUB17),
    (r"^sub-15:", Category.BASE_SUB15),
)

_EXCLUSION_RE = tuple(re.compile(pat) for pat in _EXCLUSION_PREFIXES)
_POSITIVE_RE: tuple[tuple[re.Pattern[str], Category], ...] = tuple(
    (re.compile(pat), cat) for pat, cat in _POSITIVE_PATTERNS
)


@dataclass(frozen=True)
class RuleOutcome:
    """Resultado da classificação por regra. `category=None` → passa pro LLM."""

    category: Category | None
    confidence: float
    method: ClassifyMethod | None
    matched: str | None = None


def _normalize(text: str) -> str:
    """Lower + remove acentos. Não altera espaçamento."""
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def classify_by_rules(title: str) -> RuleOutcome:
    """Retorna Category se alguma camada bater, senão None. Zero rede, síncrona."""
    text = _normalize(title.strip())

    for pattern in _EXCLUSION_RE:
        match = pattern.search(text)
        if match:
            return RuleOutcome(
                category=Category.DESCARTADO,
                confidence=_CONF_EXCLUSION,
                method=ClassifyMethod.RULE_EXCLUSION,
                matched=pattern.pattern,
            )

    for pattern, category in _POSITIVE_RE:
        match = pattern.search(text)
        if match:
            return RuleOutcome(
                category=category,
                confidence=_CONF_POSITIVE,
                method=ClassifyMethod.RULE_POSITIVE,
                matched=pattern.pattern,
            )

    return RuleOutcome(category=None, confidence=0.0, method=None)


__all__ = ["RuleOutcome", "classify_by_rules"]
