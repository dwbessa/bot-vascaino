#!/usr/bin/env python3
"""Grava snapshot das respostas do LLM para as manchetes do CSV.

Reproduz exatamente os batches que o pipeline monta (só o que camada 0/1 não
resolveu) e persiste a lista de `Classificacao` em ordem. O teste
`test_ca02_classification_accuracy_from_snapshot` usa esse snapshot para rodar
o gate CA-02 sem rede.

Uso: `set -a; source .env; set +a; uv run python scripts/refresh_classify_snapshot.py`
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from vascobot.config import Settings
from vascobot.llm.ollama_cloud import OllamaCloudProvider
from vascobot.llm.schemas import ClassificacaoBatch
from vascobot.models import Article, ArticleStatus
from vascobot.pipeline.classify import build_batch_prompt
from vascobot.pipeline.rules import classify_by_rules

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "tests" / "fixtures" / "labeled_headlines.csv"
SNAPSHOT_PATH = ROOT / "tests" / "fixtures" / "classify_llm_snapshot.json"
BATCH_SIZE = 20


def _load_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_article(row: dict[str, str], idx: int) -> Article:
    now = datetime.now(tz=ZoneInfo("America/Sao_Paulo"))
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


async def _capture(
    articles: list[Article], provider: OllamaCloudProvider, model: str
) -> list[dict[str, object]]:
    """Roda batches e devolve a sequência achatada de Classificacao (mesma ordem)."""
    snapshot: list[dict[str, object]] = []
    for start in range(0, len(articles), BATCH_SIZE):
        chunk = articles[start : start + BATCH_SIZE]
        prompt = build_batch_prompt(chunk, include_institutional=True)
        print(f"  batch {start // BATCH_SIZE + 1} ({len(chunk)} manchetes)", file=sys.stderr)
        batch: ClassificacaoBatch = await provider.structured(
            prompt=prompt,
            schema=ClassificacaoBatch,
            model=model,
        )
        if len(batch.itens) != len(chunk):
            raise RuntimeError(f"batch retornou {len(batch.itens)}, pedi {len(chunk)}")
        snapshot.extend(
            {"categoria": it.categoria.value, "confianca": it.confianca, "motivo": it.motivo}
            for it in batch.itens
        )
    return snapshot


async def main() -> int:
    if not os.getenv("OLLAMA_API_KEY"):
        print("OLLAMA_API_KEY ausente. Faça `set -a; source .env; set +a`.", file=sys.stderr)
        return 1

    settings = Settings()
    provider = OllamaCloudProvider.from_settings(settings)

    rows = _load_rows()
    articles = [_to_article(row, i) for i, row in enumerate(rows)]
    to_llm = [a for a in articles if classify_by_rules(a.title).category is None]
    print(f"CSV total: {len(articles)} — vai pro LLM: {len(to_llm)}", file=sys.stderr)

    snapshot = await _capture(to_llm, provider, settings.classify_model)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ snapshot gravado em {SNAPSHOT_PATH.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
