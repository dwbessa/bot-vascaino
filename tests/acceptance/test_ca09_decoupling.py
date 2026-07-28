"""CA-09 — X_ENABLED=false → pipeline roda inteiro, zero draft de X."""

from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from vascobot.llm.schemas import ResumoCategoria
from vascobot.models import Category, Digest, Platform, PostDraft, PostStatus, PublishedPost
from vascobot.publishers.base import Publisher
from vascobot.publishers.registry import PublisherRegistry

BRT = ZoneInfo("America/Sao_Paulo")


class FakeBluesky(Publisher):
    platform = "bluesky"

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.calls: list[list[PostDraft]] = []

    async def publish_thread(self, drafts: list[PostDraft]) -> list[PublishedPost]:
        self.calls.append(drafts)
        return [
            PublishedPost(
                id=f"p-{i}",
                digest_id=d.digest_id,
                platform=d.platform,
                thread_index=d.thread_index,
                text=d.text,
                has_link=d.has_link,
                status=PostStatus.PUBLISHED,
                external_id=f"at://did/{i}",
                published_at=datetime(2026, 7, 27, 12, tzinfo=BRT),
                idempotency_key=d.idempotency_key,
            )
            for i, d in enumerate(drafts)
        ]


class FakeX(Publisher):
    platform = "x"

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.calls: list[list[PostDraft]] = []

    async def publish_thread(self, drafts: list[PostDraft]) -> list[PublishedPost]:
        self.calls.append(drafts)
        return []


def _draft(platform: Platform, idx: int) -> PostDraft:
    return PostDraft(
        digest_id="d",
        platform=platform,
        thread_index=idx,
        text=f"post {idx}",
        has_link=False,
        idempotency_key=f"r:profissional:{platform.value}:{idx}",
    )


@pytest.mark.acceptance
def test_ca09_x_fully_decoupled() -> None:
    """X off → registry devolve só Bluesky, compose nunca deve criar draft de X."""
    reg = PublisherRegistry()
    bsky = FakeBluesky(enabled=True)
    x = FakeX(enabled=False)  # ← interruptor único (RF-07)
    reg.register(bsky)
    reg.register(x)

    active = reg.enabled()
    assert [p.platform for p in active] == ["bluesky"]

    # Simula o pipeline: só compõe drafts para as plataformas ativas.
    drafts_by_platform = {p.platform: [_draft(Platform(p.platform), 0)] for p in active}
    assert "x" not in drafts_by_platform
    assert list(drafts_by_platform) == ["bluesky"]

    # Executa: só Bluesky é chamado.
    for pub in active:
        asyncio.run(pub.publish_thread(drafts_by_platform[pub.platform]))
    assert len(bsky.calls) == 1
    assert x.calls == []


def test_ca09_negative_both_enabled_calls_both() -> None:
    """Sanity — quando ambos ativos, ambos publicam. Sem contaminação."""
    reg = PublisherRegistry()
    bsky = FakeBluesky(enabled=True)
    x = FakeX(enabled=True)
    reg.register(bsky)
    reg.register(x)

    active = reg.enabled()
    assert {p.platform for p in active} == {"bluesky", "x"}


def test_registry_rejects_duplicate() -> None:
    reg = PublisherRegistry()
    reg.register(FakeBluesky(enabled=True))
    with pytest.raises(ValueError, match="already"):
        reg.register(FakeBluesky(enabled=True))


def test_can_test_digest_creation_without_platform_reference() -> None:
    """O pipeline monta digests sem 'saber' quais plataformas existem."""
    resumo = ResumoCategoria(headline="h", bullets=["b1"])
    Digest(
        id="d1",
        run_id="r1",
        category=Category.FEMININO,
        headline=resumo.headline,
        bullets=resumo.bullets,
        source_urls=["https://x/y"],
        llm_model="fake",
    )
