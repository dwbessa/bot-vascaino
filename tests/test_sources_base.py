"""SourceAdapter iface + registry — T-007."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vascobot.models import RawArticle, Watermark
from vascobot.sources.base import RateLimiter, SourceAdapter
from vascobot.sources.registry import SourceRegistry

BRT = ZoneInfo("America/Sao_Paulo")


class FakeAdapter(SourceAdapter):
    source_id = "fake"
    base_url = "https://example.invalid"
    rate_limit_rps = 100.0

    async def discover(self, since: Watermark) -> list[RawArticle]:
        _ = since
        now = datetime(2026, 7, 27, 12, tzinfo=BRT)
        return [
            RawArticle(
                source_id=self.source_id,
                external_id="1",
                url="https://example.invalid/n/1/x",
                title="Título de teste",
                published_at=now,
                fetched_at=now,
            ),
        ]


def test_registry_discovers_fake_adapter() -> None:
    reg = SourceRegistry()
    reg.register(FakeAdapter())
    assert "fake" in reg.ids()
    adapter = reg.get("fake")
    result = asyncio.run(adapter.discover(Watermark(source_id="fake")))
    assert len(result) == 1
    assert result[0].external_id == "1"


def test_registry_from_config_filters_enabled() -> None:
    reg = SourceRegistry()
    reg.register(FakeAdapter())
    active = reg.enabled(("fake",))
    assert [a.source_id for a in active] == ["fake"]
    assert reg.enabled(()) == []
    assert reg.enabled(("outra",)) == []


def test_registry_rejects_duplicate() -> None:
    reg = SourceRegistry()
    reg.register(FakeAdapter())
    with pytest.raises(ValueError, match="already"):
        reg.register(FakeAdapter())


def test_rate_limiter_gates_second_call() -> None:
    """1 req/s: segunda chamada consecutiva deve esperar."""

    async def _drive() -> tuple[float, float]:
        rl = RateLimiter(rps=1.0)
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await rl.acquire("host-a")
        t1 = loop.time()
        await rl.acquire("host-a")
        t2 = loop.time()
        return t1 - t0, t2 - t1

    first, second = asyncio.run(_drive())
    assert first < 0.05, first
    assert second >= 0.9, second


def test_rate_limiter_independent_per_host() -> None:
    async def _drive() -> float:
        rl = RateLimiter(rps=1.0)
        loop = asyncio.get_running_loop()
        await rl.acquire("host-a")
        t0 = loop.time()
        await rl.acquire("host-b")
        return loop.time() - t0

    delay = asyncio.run(_drive())
    assert delay < 0.05
