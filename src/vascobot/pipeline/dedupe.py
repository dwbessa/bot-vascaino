"""Deduplicação — plan.md §6.4.

Dentro de cada categoria:
  1. Exato: mesma URL canônica OU mesmo content_hash.
  2. Near-dup: `token_set_ratio >= 85` (título normalizado).
  3. Ancoragem por entidade: ≥ 1 token capitalizado em comum.

O canônico do cluster = o mais antigo. Clustering guloso (n < 100 → O(n²) é
irrelevante).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from vascobot.pipeline.classify_pipeline import ClassifiedArticle

FUZZY_THRESHOLD = 85

# Stopwords pt-BR curtas — suficiente pra normalização barata (unidecode + este set)
_STOPWORDS = {
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "a",
    "o",
    "as",
    "os",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "por",
    "para",
    "com",
    "sem",
    "sobre",
    "vs",
    "x",
    "contra",
    "pelo",
    "pela",
    "pelos",
    "pelas",
    "que",
    "um",
    "uma",
    "uns",
    "umas",
}

# Prefixos que são etiqueta de categoria, não conteúdo do fato
_TAG_PREFIXES = re.compile(
    r"^(feminino|sub-\d+|futsal(?:\s+feminino)?(?:\s+base)?|"
    r"basquete|volei|natacao|remo|atletismo|judo|e-?sports|"
    r"futmesa|futevolei|polo\s+aquatico):\s*",
    re.IGNORECASE,
)


@dataclass
class Cluster:
    canonical: ClassifiedArticle
    items: list[ClassifiedArticle] = field(default_factory=list)


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _tokens(title: str) -> tuple[list[str], set[str]]:
    """Devolve (tokens_normalizados, entidades_capitalizadas_originais)."""
    entities = {
        _strip_accents(w).lower()
        for w in re.findall(r"\b[A-ZÁÂÃÉÊÍÓÔÕÚÇ][A-Za-zÁ-Úá-ú-]{2,}\b", title)
        if _strip_accents(w).lower() not in _STOPWORDS
    }
    stripped = _TAG_PREFIXES.sub("", title)
    plain = _strip_accents(stripped).lower()
    raw = re.findall(r"[a-z0-9]+", plain)
    keep = [t for t in raw if t not in _STOPWORDS and len(t) > 1]
    return sorted(keep), entities


def _similar(a: ClassifiedArticle, b: ClassifiedArticle) -> bool:
    """Testa se dois artigos são o mesmo fato."""
    if a.article.url == b.article.url:
        return True
    if a.article.content_hash == b.article.content_hash:
        return True

    tok_a, ent_a = _tokens(a.article.title)
    tok_b, ent_b = _tokens(b.article.title)
    if not tok_a or not tok_b:
        return False

    ratio = fuzz.token_set_ratio(" ".join(tok_a), " ".join(tok_b))
    if ratio < FUZZY_THRESHOLD:
        return False

    # ancoragem por entidade — pelo menos 1 nome próprio em comum
    return bool(ent_a & ent_b)


def cluster(items: list[ClassifiedArticle]) -> list[Cluster]:
    """Agrupa por categoria + similaridade. Canônico = mais antigo do cluster."""
    by_category: dict[str, list[ClassifiedArticle]] = {}
    for item in items:
        by_category.setdefault(item.category.value, []).append(item)

    clusters: list[Cluster] = []
    for group in by_category.values():
        # ordenar por published_at asc — o primeiro a "abrir cluster" é o mais antigo
        group_sorted = sorted(group, key=lambda x: x.article.published_at)
        assigned: list[bool] = [False] * len(group_sorted)
        for i, seed in enumerate(group_sorted):
            if assigned[i]:
                continue
            bucket = [seed]
            assigned[i] = True
            for j in range(i + 1, len(group_sorted)):
                if assigned[j]:
                    continue
                if _similar(seed, group_sorted[j]):
                    bucket.append(group_sorted[j])
                    assigned[j] = True
            clusters.append(Cluster(canonical=seed, items=bucket))
    return clusters


__all__ = ["Cluster", "cluster"]
