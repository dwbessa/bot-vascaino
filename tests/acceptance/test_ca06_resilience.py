"""CA-06 — falha de fonte isolada. Uma quebra não derruba a outra nem avança watermark."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.db import Database
from vascobot.models import RawArticle, Watermark
from vascobot.pipeline.collect import CollectResult, collect
from vascobot.sources.base import SourceAdapter, SourceError
from vascobot.sources.registry import SourceRegistry

BRT = ZoneInfo("America/Sao_Paulo")


class OkAdapter(SourceAdapter):
    source_id = "ok_source"
    base_url = "https://ok.invalid"

    async def discover(self, since: Watermark) -> list[RawArticle]:
        cutoff = int(since.external_id) if since.external_id else 0
        now = datetime(2026, 7, 27, 12, tzinfo=BRT)
        return [
            RawArticle(
                source_id=self.source_id,
                external_id=str(i),
                url=f"https://ok.invalid/n/{i}/x",
                title=f"OK #{i}",
                published_at=now,
                fetched_at=now,
            )
            for i in (100, 101, 102)
            if i > cutoff
        ]


class BrokenAdapter(SourceAdapter):
    source_id = "broken_source"
    base_url = "https://broken.invalid"

    async def discover(self, since: Watermark) -> list[RawArticle]:
        _ = since
        raise SourceError("upstream 500")


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "ca06.db")
    d.migrate()
    with d.connect() as conn:
        conn.execute(
            "INSERT INTO source_state(source_id, watermark_extid) VALUES (?, ?)",
            ("broken_source", "50"),
        )
        conn.execute(
            "INSERT INTO source_state(source_id, watermark_extid) VALUES (?, ?)",
            ("ok_source", "90"),
        )
    return d


@pytest.mark.acceptance
def test_ca06_source_failure_isolated(db: Database) -> None:
    reg = SourceRegistry()
    reg.register(OkAdapter())
    reg.register(BrokenAdapter())

    result: CollectResult = asyncio.run(collect(reg, db, source_ids=("ok_source", "broken_source")))

    assert {r.source_id for r in result.successful} == {"ok_source"}
    assert {r.source_id for r in result.failed} == {"broken_source"}

    ok_ids = {a.external_id for a in result.articles if a.source_id == "ok_source"}
    assert ok_ids == {"100", "101", "102"}

    with db.connect() as conn:
        row_broken = conn.execute(
            "SELECT watermark_extid, last_error FROM source_state WHERE source_id=?",
            ("broken_source",),
        ).fetchone()
        row_ok = conn.execute(
            "SELECT watermark_extid FROM source_state WHERE source_id=?",
            ("ok_source",),
        ).fetchone()

    assert row_broken[0] == "50", "watermark de fonte quebrada não pode avançar"
    assert row_broken[1] and "upstream" in row_broken[1]
    assert row_ok[0] == "102", "watermark de fonte OK avança para o maior id"


def test_collect_no_articles_if_all_below_watermark(db: Database) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE source_state SET watermark_extid=? WHERE source_id=?",
            ("999", "ok_source"),
        )
    reg = SourceRegistry()
    reg.register(OkAdapter())
    result = asyncio.run(collect(reg, db, source_ids=("ok_source",)))
    assert result.articles == []
    assert {r.source_id for r in result.successful} == {"ok_source"}
