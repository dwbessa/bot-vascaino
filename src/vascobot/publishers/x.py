"""Publisher X — httpx + OAuth 2.0 user context.

Budget guard (RF-07 / D8):
- Se `X_MONTHLY_BUDGET_USD` estiver definido e for estourado → `skipped` +
  alerta, **sem exceção**. Bluesky segue normal.
- Se estiver vazio, só registra o gasto pra decisão futura.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

import structlog

from vascobot.models import PostDraft, PostStatus, PublishedPost
from vascobot.publishers.base import Publisher
from vascobot.publishers.cost import cost_of_post

if TYPE_CHECKING:
    from vascobot.config import Settings

_log = structlog.get_logger(__name__)
_TWEET_URL = "https://api.twitter.com/2/tweets"


def _make_http_client() -> Any:
    import httpx  # noqa: PLC0415 — só quando for construir httpx real

    return httpx.AsyncClient(timeout=15.0)


class _HTTPClient(Protocol):
    async def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> Any: ...
    async def aclose(self) -> None: ...


@dataclass(frozen=True)
class MonthlyUsage:
    spent_usd: float
    budget_usd: float | None

    @property
    def exhausted(self) -> bool:
        return self.budget_usd is not None and self.spent_usd >= self.budget_usd


class XPublisher(Publisher):
    platform = "x"

    def __init__(
        self,
        *,
        client: _HTTPClient,
        access_token: str,
        usage: MonthlyUsage,
        enabled: bool = True,
        is_premium: bool = True,
        now: datetime | None = None,
    ) -> None:
        self._client = client
        self._access_token = access_token
        self._usage = usage
        self.enabled = enabled
        self._is_premium = is_premium
        self._now = now or datetime.now(tz=ZoneInfo("America/Sao_Paulo"))

    @classmethod
    def from_settings(cls, settings: Settings, *, usage: MonthlyUsage) -> XPublisher:
        client = _make_http_client()
        token_secret = settings.x_access_token
        if token_secret is None:
            raise ValueError("X_ACCESS_TOKEN required when X_ENABLED=true")
        return cls(
            client=client,
            access_token=token_secret.get_secret_value(),
            usage=usage,
            enabled=settings.x_enabled,
            is_premium=settings.x_is_premium,
        )

    async def publish_thread(self, drafts: list[PostDraft]) -> list[PublishedPost]:
        if not drafts:
            return []
        if self._usage.exhausted:
            _log.warning(
                "x.budget_exhausted",
                spent_usd=self._usage.spent_usd,
                budget_usd=self._usage.budget_usd,
                skipped_drafts=len(drafts),
            )
            return [_skip(d, self._now) for d in drafts]

        posted: list[PublishedPost] = []
        reply_to: str | None = None
        for draft in drafts:
            payload: dict[str, Any] = {"text": draft.text}
            if reply_to is not None:
                payload["reply"] = {"in_reply_to_tweet_id": reply_to}

            try:
                resp = await self._client.post(
                    _TWEET_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
            except Exception as exc:
                posted.append(_failed(draft, str(exc), self._now))
                break

            tweet_id = _extract_tweet_id(resp)
            if not tweet_id:
                posted.append(_failed(draft, "resposta do X sem id", self._now))
                break
            reply_to = tweet_id

            cost = cost_of_post(has_link=draft.has_link)
            posted.append(
                PublishedPost(
                    id=f"x-{draft.thread_index}-{draft.idempotency_key[-8:]}",
                    digest_id=draft.digest_id,
                    platform=draft.platform,
                    thread_index=draft.thread_index,
                    text=draft.text,
                    has_link=draft.has_link,
                    status=PostStatus.PUBLISHED,
                    external_id=tweet_id,
                    cost_usd=cost,
                    published_at=self._now,
                    idempotency_key=draft.idempotency_key,
                ),
            )
        return posted


def _extract_tweet_id(resp: Any) -> str | None:
    payload: dict[str, Any]
    if hasattr(resp, "json"):
        payload = resp.json()
    elif isinstance(resp, dict):
        payload = resp
    else:
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        val = data.get("id")
        return str(val) if val is not None else None
    return None


def _skip(draft: PostDraft, now: datetime) -> PublishedPost:
    return PublishedPost(
        id=f"x-skip-{draft.thread_index}-{draft.idempotency_key[-8:]}",
        digest_id=draft.digest_id,
        platform=draft.platform,
        thread_index=draft.thread_index,
        text=draft.text,
        has_link=draft.has_link,
        status=PostStatus.SKIPPED,
        external_id=None,
        cost_usd=0.0,
        published_at=now,
        error="orçamento mensal do X estourado",
        idempotency_key=draft.idempotency_key,
    )


def _failed(draft: PostDraft, error: str, now: datetime) -> PublishedPost:
    return PublishedPost(
        id=f"x-fail-{draft.thread_index}-{draft.idempotency_key[-8:]}",
        digest_id=draft.digest_id,
        platform=draft.platform,
        thread_index=draft.thread_index,
        text=draft.text,
        has_link=draft.has_link,
        status=PostStatus.FAILED,
        external_id=None,
        cost_usd=0.0,
        published_at=now,
        error=error,
        idempotency_key=draft.idempotency_key,
    )


__all__ = ["MonthlyUsage", "XPublisher"]
