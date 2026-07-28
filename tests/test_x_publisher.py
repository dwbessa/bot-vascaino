"""Publisher X — T-026 (unit, sem rede)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from vascobot.models import Platform, PostDraft, PostStatus
from vascobot.publishers.cost import COST_POST_WITH_LINK_USD, COST_POST_WITHOUT_LINK_USD
from vascobot.publishers.x import MonthlyUsage, XPublisher

BRT = ZoneInfo("America/Sao_Paulo")


@dataclass
class _FakeResp:
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


@dataclass
class _FakeHTTP:
    responses: list[_FakeResp | Exception] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any:
        self.calls.append({"url": url, "json": json, "headers": headers})
        if not self.responses:
            raise RuntimeError("no more responses queued")
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    async def aclose(self) -> None:
        return None


def _drafts(n: int, *, all_links: bool = False) -> list[PostDraft]:
    return [
        PostDraft(
            digest_id="d",
            platform=Platform.X,
            thread_index=i,
            text=f"tweet {i}",
            has_link=(all_links or i == n - 1),
            idempotency_key=f"r:profissional:x:{i}",
        )
        for i in range(n)
    ]


def _pub(http: _FakeHTTP, *, usage: MonthlyUsage | None = None, enabled: bool = True) -> XPublisher:
    return XPublisher(
        client=http,  # type: ignore[arg-type]
        access_token="fake-token",
        usage=usage or MonthlyUsage(spent_usd=0.0, budget_usd=None),
        enabled=enabled,
        now=datetime(2026, 7, 27, 12, tzinfo=BRT),
    )


def _tweet_response(tid: str) -> _FakeResp:
    return _FakeResp({"data": {"id": tid}})


def test_publishes_thread_and_chains_reply_ids() -> None:
    http = _FakeHTTP(responses=[_tweet_response("1"), _tweet_response("2"), _tweet_response("3")])
    pub = _pub(http)
    posts = asyncio.run(pub.publish_thread(_drafts(3)))
    assert [p.status for p in posts] == [PostStatus.PUBLISHED] * 3
    assert [c["json"].get("reply") for c in http.calls] == [
        None,
        {"in_reply_to_tweet_id": "1"},
        {"in_reply_to_tweet_id": "2"},
    ]
    assert [p.external_id for p in posts] == ["1", "2", "3"]


def test_cost_recorded_per_post() -> None:
    http = _FakeHTTP(responses=[_tweet_response("1"), _tweet_response("2")])
    pub = _pub(http)
    posts = asyncio.run(pub.publish_thread(_drafts(2)))
    # 1º sem link (0.015), 2º com link (0.20) — default last-index has_link=True
    assert posts[0].cost_usd == COST_POST_WITHOUT_LINK_USD
    assert posts[1].cost_usd == COST_POST_WITH_LINK_USD


def test_budget_guard_skips_without_exception() -> None:
    http = _FakeHTTP(responses=[])
    pub = _pub(http, usage=MonthlyUsage(spent_usd=100.0, budget_usd=100.0))
    posts = asyncio.run(pub.publish_thread(_drafts(4)))
    assert [p.status for p in posts] == [PostStatus.SKIPPED] * 4
    assert http.calls == []
    for p in posts:
        assert p.cost_usd == 0.0


def test_budget_guard_over_limit_skips() -> None:
    http = _FakeHTTP(responses=[])
    pub = _pub(http, usage=MonthlyUsage(spent_usd=200.0, budget_usd=100.0))
    posts = asyncio.run(pub.publish_thread(_drafts(1)))
    assert posts[0].status is PostStatus.SKIPPED


def test_no_budget_records_spent_only() -> None:
    http = _FakeHTTP(responses=[_tweet_response("1")])
    pub = _pub(http, usage=MonthlyUsage(spent_usd=9999.0, budget_usd=None))
    posts = asyncio.run(pub.publish_thread(_drafts(1)))
    assert posts[0].status is PostStatus.PUBLISHED


def test_transport_error_stops_thread() -> None:
    http = _FakeHTTP(responses=[_tweet_response("1"), RuntimeError("upstream 500")])
    pub = _pub(http)
    posts = asyncio.run(pub.publish_thread(_drafts(3)))
    assert [p.status for p in posts] == [PostStatus.PUBLISHED, PostStatus.FAILED]


def test_missing_tweet_id_marks_failed() -> None:
    http = _FakeHTTP(responses=[_FakeResp({"data": {}})])
    pub = _pub(http)
    posts = asyncio.run(pub.publish_thread(_drafts(1)))
    assert posts[0].status is PostStatus.FAILED
    assert posts[0].error and "id" in posts[0].error.lower()


def test_empty_drafts_no_call() -> None:
    http = _FakeHTTP(responses=[])
    pub = _pub(http)
    posts = asyncio.run(pub.publish_thread([]))
    assert posts == []
    assert http.calls == []


def test_authorization_header_present() -> None:
    http = _FakeHTTP(responses=[_tweet_response("1")])
    pub = _pub(http)
    asyncio.run(pub.publish_thread(_drafts(1)))
    assert http.calls[0]["headers"]["Authorization"] == "Bearer fake-token"
