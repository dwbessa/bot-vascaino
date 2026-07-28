"""Regras de classificação — T-015.

Camada 0 (exclusão) e camada 1 (positiva). Zero rede.
A prioridade absoluta é `Futsal Feminino Base: ...` **não** virar `feminino`.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

from vascobot.models import Category, ClassifyMethod
from vascobot.pipeline.rules import RuleOutcome, classify_by_rules

CSV_PATH = Path(__file__).parent / "fixtures" / "labeled_headlines.csv"


# ------------------------------------------------------------------ armadilhas
def test_futsal_feminino_base_goes_to_descartado() -> None:
    """Armadilha #1 do CLAUDE.md §10 — precisa morrer na camada 0."""
    out = classify_by_rules("Futsal Feminino Base: Vasco vence pelo Estadual sub-15")
    assert out.category is Category.DESCARTADO
    assert out.method is ClassifyMethod.RULE_EXCLUSION


def test_futsal_base_sub12_goes_to_descartado() -> None:
    out = classify_by_rules("Futsal Base: Vasco x Barra Sub-12")
    assert out.category is Category.DESCARTADO
    assert out.method is ClassifyMethod.RULE_EXCLUSION


def test_basquete_goes_to_descartado() -> None:
    assert classify_by_rules("Basquete: Vasco vence o Botafogo").category is Category.DESCARTADO


def test_futmesa_goes_to_descartado() -> None:
    out = classify_by_rules("Futmesa: dupla do Vasco fica com bronze")
    assert out.category is Category.DESCARTADO


def test_natacao_paralimpica_goes_to_descartado() -> None:
    out = classify_by_rules("Natação Paralímpica: atleta bate recorde")
    assert out.category is Category.DESCARTADO


def test_e_sports_goes_to_descartado() -> None:
    out = classify_by_rules("E-Sports: Vasco anuncia equipe de Valorant")
    assert out.category is Category.DESCARTADO


def test_sub_12_goes_to_descartado() -> None:
    """Sub-14 e menores → descartado (D3)."""
    out = classify_by_rules("Sub-12: Vasco vence a Portuguesa")
    assert out.category is Category.DESCARTADO


def test_sub_14_goes_to_descartado() -> None:
    out = classify_by_rules("Sub-14: Vasco vence clássico")
    assert out.category is Category.DESCARTADO


# ------------------------------------------------------------------ camada 1
def test_feminino_prefix_goes_to_feminino() -> None:
    out = classify_by_rules("Feminino: Vasco vence Vila Nova")
    assert out.category is Category.FEMININO
    assert out.method is ClassifyMethod.RULE_POSITIVE


def test_sub20_prefix_goes_to_base_sub20() -> None:
    assert classify_by_rules("Sub-20: Vasco vence Cruzeiro").category is Category.BASE_SUB20


def test_sub17_prefix_goes_to_base_sub17() -> None:
    assert classify_by_rules("Sub-17: Vasco vence Botafogo").category is Category.BASE_SUB17


def test_sub16_prefix_goes_to_base_sub17() -> None:
    """D3 — Sub-16 vai junto com Sub-17."""
    assert classify_by_rules("Sub-16: Vasco goleia adversário").category is Category.BASE_SUB17


def test_sub15_prefix_goes_to_base_sub15() -> None:
    assert classify_by_rules("Sub-15: Vasco vence Cruzeiro").category is Category.BASE_SUB15


# ------------------------------------------------------------------ misses
def test_no_prefix_returns_none() -> None:
    """Sem prefixo, a decisão fica pro LLM (camada 2)."""
    out = classify_by_rules("Vasco vence o Bahia por 2 a 1 em São Januário")
    assert out.category is None
    assert out.method is None


def test_rule_is_accent_and_case_insensitive() -> None:
    a = classify_by_rules("FUTSAL: Vasco enfrenta o Corinthians")
    assert a.category is Category.DESCARTADO
    b = classify_by_rules("natacao paralimpica: atleta recorde")
    assert b.category is Category.DESCARTADO


# ------------------------------------------------------------------ CSV wide
def test_rules_no_false_positive_in_descartado() -> None:
    """DoD do T-015: contra o CSV, **zero** falso-positivo em `descartado`.

    Ou seja: nenhuma linha rotulada como não-descartado pode ser classificada
    pelas regras como `descartado` — e nenhuma linha `descartado` pode virar
    `feminino` por causa de 'Feminino' no meio (armadilha).
    """
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    misclass: list[tuple[str, str, str]] = []
    for row in rows:
        gold = row["category"]
        out = classify_by_rules(row["title"])
        if out.category is None:
            continue  # cai pro LLM
        if out.category.value != gold:
            misclass.append((row["title"], gold, out.category.value))

    # a armadilha do 'Futsal Feminino Base' precisa passar
    trap = [row for row in rows if row["title"].startswith("Futsal Feminino Base:")]
    assert trap, "faltou linha 'Futsal Feminino Base:' no CSV"
    for row in trap:
        assert classify_by_rules(row["title"]).category is Category.DESCARTADO

    assert not misclass, f"regras classificaram errado: {misclass[:5]}"


def test_rules_cover_all_prefixed_headlines() -> None:
    """Uma manchete com prefixo (ex.: `Sub-20:`) precisa ser resolvida pela regra."""
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    resolved = Counter()
    for row in rows:
        out = classify_by_rules(row["title"])
        if out.category is not None:
            resolved[row["category"]] += 1

    # feminino/sub-20/sub-17/sub-15 no CSV vêm todos prefixados
    assert resolved["feminino"] >= 10
    assert resolved["base_sub20"] >= 10
    assert resolved["base_sub17"] >= 8
    assert resolved["base_sub15"] >= 2


def test_rule_outcome_confidence_high() -> None:
    out = classify_by_rules("Futsal: Vasco enfrenta o Corinthians")
    assert isinstance(out, RuleOutcome)
    assert out.confidence >= 0.9


@pytest.mark.parametrize(
    "headline",
    [
        "Vasco confirma reforço",
        "SAF do Vasco aprova balanço",
        "Payet marca dois",
    ],
)
def test_professional_stays_unclassified_by_rules(headline: str) -> None:
    """Sem prefixo → LLM decide. Regra não pode inventar."""
    assert classify_by_rules(headline).category is None
