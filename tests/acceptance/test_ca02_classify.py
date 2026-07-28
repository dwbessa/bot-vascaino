"""CA-02 — pipeline de classificação: ≥ 90% acurácia geral, ≥ 95% precisão em `descartado`.

Este teste TEM DUAS FORMAS:
- **Unit** (default no CI): usa `FakeLLMProvider` alimentado por respostas gravadas
  no `tests/fixtures/classify_llm_snapshot.json`. Zero rede.
- **Integração** (`make integration`): usa `OllamaCloudProvider` real, com
  `CLASSIFY_MODEL` da config. Consome cota.

O snapshot é gerado por `scripts/refresh_classify_snapshot.py` — rode quando
mexer no prompt ou no CSV, com a chave real.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.config import Settings
from vascobot.llm.base import LLMProvider
from vascobot.llm.fake import FakeLLMProvider
from vascobot.llm.ollama_cloud import OllamaCloudProvider
from vascobot.llm.schemas import Categoria, Classificacao, ClassificacaoBatch
from vascobot.models import Article, ArticleStatus, Category
from vascobot.pipeline.classify import build_batch_prompt
from vascobot.pipeline.classify_pipeline import classify_articles
from vascobot.pipeline.rules import classify_by_rules

BRT = ZoneInfo("America/Sao_Paulo")
CSV_PATH = Path(__file__).parent.parent / "fixtures" / "labeled_headlines.csv"
SNAPSHOT_PATH = Path(__file__).parent.parent / "fixtures" / "classify_llm_snapshot.json"

TARGET_ACCURACY = 0.90
TARGET_DESCARTADO_PRECISION = 0.95
BATCH_SIZE = 20


def _load_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_article(row: dict[str, str], idx: int) -> Article:
    now = datetime(2026, 7, 27, 12, tzinfo=BRT)
    return Article(
        id=f"gold-{idx}",
        source_id="gold",
        external_id=str(idx),
        url=row.get("url") or f"https://bench.invalid/{idx}",
        title=row["title"],
        summary=None,
        body=None,
        published_at=now,
        fetched_at=now,
        content_hash="h",
        status=ArticleStatus.OK.value,
        run_id="gold",
    )


def _build_fake_from_snapshot() -> tuple[FakeLLMProvider, list[Article], list[str]]:
    """Alimenta o FakeLLMProvider replicando as chamadas em batch do pipeline."""
    rows = _load_rows()
    articles = [_to_article(row, i) for i, row in enumerate(rows)]
    gold = [row["category"] for row in rows]

    # Filtra só o que iria pro LLM (mesmo critério do pipeline real)
    to_llm: list[Article] = [a for a in articles if classify_by_rules(a.title).category is None]

    with SNAPSHOT_PATH.open(encoding="utf-8") as f:
        snapshot = json.load(f)

    fake = FakeLLMProvider()
    for start in range(0, len(to_llm), BATCH_SIZE):
        chunk = to_llm[start : start + BATCH_SIZE]
        prompt = build_batch_prompt(chunk, include_institutional=True)
        items = [
            Classificacao(
                categoria=Categoria(snap["categoria"]),
                confianca=snap["confianca"],
                motivo=snap["motivo"],
            )
            for snap in snapshot[start : start + BATCH_SIZE]
        ]
        fake.register(prompt, ClassificacaoBatch(itens=items))
    return fake, articles, gold


def _accuracy(gold: list[str], pred: list[str]) -> float:
    hits = sum(1 for g, p in zip(gold, pred, strict=True) if g == p)
    return hits / len(gold)


def _precision(gold: list[str], pred: list[str], label: str) -> float:
    predicted = [i for i, p in enumerate(pred) if p == label]
    if not predicted:
        return 0.0
    hits = sum(1 for i in predicted if gold[i] == label)
    return hits / len(predicted)


def _run_gate(provider: LLMProvider, model: str, articles: list[Article], gold: list[str]) -> None:
    classified = asyncio.run(
        classify_articles(
            articles,
            llm_provider=provider,
            llm_model=model,
            include_institutional=True,
            batch_size=BATCH_SIZE,
        ),
    )
    pred = [c.category.value for c in classified]
    acc = _accuracy(gold, pred)
    prec = _precision(gold, pred, "descartado")

    mistakes = [
        (articles[i].title, gold[i], pred[i]) for i in range(len(gold)) if gold[i] != pred[i]
    ][:10]
    detail = "\n".join(f"  {t!r} → esperava {g}, veio {p}" for t, g, p in mistakes)

    assert acc >= TARGET_ACCURACY, f"acurácia {acc:.1%} < {TARGET_ACCURACY:.0%}\n{detail}"
    assert prec >= TARGET_DESCARTADO_PRECISION, (
        f"precisão em descartado {prec:.1%} < {TARGET_DESCARTADO_PRECISION:.0%}\n{detail}"
    )

    # Sanidade — cobertura das categorias
    label_counts = Counter(gold)
    assert set(label_counts) == {c.value for c in Category}, (
        "CSV precisa cobrir todas as categorias"
    )


@pytest.mark.acceptance
def test_ca02_classification_accuracy_from_snapshot() -> None:
    """Roda o gate contra o snapshot gravado — determinístico, sem rede."""
    if not SNAPSHOT_PATH.exists():
        pytest.skip("snapshot ausente; rode scripts/refresh_classify_snapshot.py")
    fake, articles, gold = _build_fake_from_snapshot()
    _run_gate(fake, model="fake", articles=articles, gold=gold)


@pytest.mark.acceptance
@pytest.mark.integration
def test_ca02_classification_accuracy_live() -> None:
    """Prova que o gate ainda passa contra o modelo real, na config atual."""
    if not os.getenv("OLLAMA_API_KEY"):
        pytest.skip("OLLAMA_API_KEY ausente")
    settings = Settings()
    provider = OllamaCloudProvider.from_settings(settings)
    rows = _load_rows()
    articles = [_to_article(row, i) for i, row in enumerate(rows)]
    gold = [row["category"] for row in rows]
    _run_gate(provider, model=settings.classify_model, articles=articles, gold=gold)
