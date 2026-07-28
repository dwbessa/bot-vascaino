"""Guarda o CSV rotulado — T-005. Se a distribuição decair, o gate CA-02 sofre."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

CSV_PATH = Path(__file__).parent / "fixtures" / "labeled_headlines.csv"

VALID_CATEGORIES = {
    "profissional",
    "feminino",
    "base_sub20",
    "base_sub17",
    "base_sub15",
    "descartado",
}

REQUIRED_HEADLINES = [
    "Futsal Feminino Base:",
    "Sub-16:",
    "Sub-12:",
    "Basquete:",
    "Futmesa:",
    "Natação Paralímpica:",
]


def _rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_csv_min_size() -> None:
    rows = _rows()
    assert len(rows) >= 100, f"CSV precisa de ≥ 100 linhas, tem {len(rows)}"


def test_csv_no_empty_category() -> None:
    rows = _rows()
    empty = [r for r in rows if not r.get("category", "").strip()]
    assert not empty, f"{len(empty)} linhas sem categoria"


def test_csv_only_valid_categories() -> None:
    rows = _rows()
    bad = [r for r in rows if r["category"] not in VALID_CATEGORIES]
    assert not bad, f"categorias inválidas: {bad}"


def test_csv_all_categories_present() -> None:
    counts = Counter(r["category"] for r in _rows())
    for cat in VALID_CATEGORIES:
        assert counts.get(cat, 0) > 0, f"categoria {cat} zerada"


def test_csv_required_traps_present() -> None:
    """Manchetes-armadilha obrigatórias do tasks.md T-005."""
    titles = [r["title"] for r in _rows()]
    for needed in REQUIRED_HEADLINES:
        assert any(t.startswith(needed) for t in titles), f"falta '{needed}'"


def test_csv_min_no_prefix_headlines() -> None:
    """≥ 40 manchetes sem prefixo, para medir o LLM no bolo sem sinal."""
    rows = _rows()
    no_prefix = [r for r in rows if ":" not in r["title"].split()[0]]
    assert len(no_prefix) >= 40, f"só {len(no_prefix)} manchetes sem prefixo"
