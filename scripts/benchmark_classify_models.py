#!/usr/bin/env python3
"""T-016b — mede acurácia de classificação por modelo contra o CSV rotulado.

Uso: `set -a; source .env; set +a; uv run python scripts/benchmark_classify_models.py`

Chama LLM real. Cada modelo consome cota. Rodar só quando quiser atualizar
a tabela do research.md §4.4.
"""

from __future__ import annotations

import asyncio
import csv
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from vascobot.config import Settings
from vascobot.llm.ollama_cloud import OllamaCloudProvider
from vascobot.llm.schemas import Categoria, ClassificacaoBatch
from vascobot.models import Article, ArticleStatus
from vascobot.pipeline.classify import build_batch_prompt

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "tests" / "fixtures" / "labeled_headlines.csv"

CANDIDATES: tuple[str, ...] = ("gpt-oss:20b", "qwen3.5:397b", "deepseek-v4-flash")

BATCH_SIZE = 20


def _load_gold() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _as_article(row: dict[str, str], idx: int) -> Article:
    now = datetime.now(tz=ZoneInfo("America/Sao_Paulo"))
    return Article(
        id=f"bench-{idx}",
        source_id="bench",
        external_id=str(idx),
        url=row.get("url") or f"https://bench.invalid/{idx}",
        title=row["title"],
        summary=None,
        body=None,
        published_at=now,
        fetched_at=now,
        content_hash="h",
        status=ArticleStatus.OK.value,
        run_id="bench",
    )


async def _run_model(model: str, articles: list[Article]) -> tuple[list[Categoria], list[float]]:
    settings = Settings()
    provider = OllamaCloudProvider.from_settings(settings)
    latencies: list[float] = []
    predictions: list[Categoria] = []
    for start in range(0, len(articles), BATCH_SIZE):
        chunk = articles[start : start + BATCH_SIZE]
        prompt = build_batch_prompt(chunk, include_institutional=True)
        t0 = time.perf_counter()
        batch: ClassificacaoBatch = await provider.structured(
            prompt=prompt,
            schema=ClassificacaoBatch,
            model=model,
        )
        latencies.append((time.perf_counter() - t0) * 1000)
        if len(batch.itens) != len(chunk):
            raise RuntimeError(
                f"{model}: pedi {len(chunk)}, veio {len(batch.itens)}",
            )
        predictions.extend(item.categoria for item in batch.itens)
    return predictions, latencies


def _accuracy(gold: list[str], pred: list[str]) -> float:
    hits = sum(1 for g, p in zip(gold, pred, strict=True) if g == p)
    return hits / len(gold)


def _precision(gold: list[str], pred: list[str], label: str) -> float:
    predicted = [i for i, p in enumerate(pred) if p == label]
    if not predicted:
        return 0.0
    hits = sum(1 for i in predicted if gold[i] == label)
    return hits / len(predicted)


def _confusion(gold: list[str], pred: list[str]) -> str:
    labels = sorted({*gold, *pred})
    rows = []
    for g in labels:
        row = [g]
        for p in labels:
            n = sum(1 for i, gg in enumerate(gold) if gg == g and pred[i] == p)
            row.append(str(n))
        rows.append(row)
    header = "actual\\pred | " + " | ".join(labels)
    body = "\n".join(" | ".join(r) for r in rows)
    return f"{header}\n{body}"


async def main() -> int:
    if not os.getenv("OLLAMA_API_KEY"):
        print("OLLAMA_API_KEY ausente. `set -a; source .env; set +a` antes.", file=sys.stderr)
        return 1

    gold_rows = _load_gold()
    articles = [_as_article(row, i) for i, row in enumerate(gold_rows)]
    gold_labels = [row["category"] for row in gold_rows]
    print(f"benchmark contra {len(articles)} manchetes rotuladas", file=sys.stderr)

    print("\n| Modelo | Acurácia geral | Precisão em `descartado` | Latência p50 (ms) |")
    print("|---|---|---|---|")
    for model in CANDIDATES:
        print(f"→ rodando {model}...", file=sys.stderr)
        try:
            preds, latencies = await _run_model(model, articles)
        except Exception as exc:
            print(f"| `{model}` | ERRO: {type(exc).__name__} | — | — |")
            print(f"  falha: {exc}", file=sys.stderr)
            continue
        pred_labels = [p.value for p in preds]
        acc = _accuracy(gold_labels, pred_labels)
        prec = _precision(gold_labels, pred_labels, "descartado")
        p50 = statistics.median(latencies)
        print(f"| `{model}` | {acc:.1%} | {prec:.1%} | {p50:.0f} |")
        # Matriz de confusão pro log
        print(_confusion(gold_labels, pred_labels), file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
