"""Publisher Bluesky — atproto.

Detalhes decisivos (research.md §2):
- Handle + App Password. `createSession` limitado a 30/5min e 300/dia por handle.
- Sessão persistida em disco (`BLUESKY_SESSION_PATH`) e reaproveitada entre runs.
- Facets: nunca concatenar string com URL, usar `TextBuilder`.
- Thread: reply precisa de refs `root` **e** `parent`.
- Custo = 0.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from zoneinfo import ZoneInfo

import structlog

from vascobot.models import PostDraft, PostStatus, PublishedPost
from vascobot.publishers.base import Publisher, PublishError

if TYPE_CHECKING:
    from vascobot.config import Settings

_log = structlog.get_logger(__name__)


def _make_atproto_client() -> Any:  # wrapper — importa só quando construir de verdade
    from atproto import Client  # noqa: PLC0415

    return Client()


class _BlueskyLike(Protocol):
    """Só o que a gente realmente usa da atproto — permite mock trivial."""

    def login(self, login: str, password: str, *, session_string: str | None = ...) -> Any: ...

    def send_post(self, text: str, reply_to: Any | None = ..., facets: Any | None = ...) -> Any: ...

    def export_session_string(self) -> str: ...


class BlueskyPublisher(Publisher):
    platform = "bluesky"

    def __init__(
        self,
        *,
        client: _BlueskyLike,
        handle: str,
        app_password: str,
        session_path: Path,
        enabled: bool = True,
        now: datetime | None = None,
    ) -> None:
        self._client = client
        self._handle = handle
        self._password = app_password
        self._session_path = session_path
        self.enabled = enabled
        self._now = now or datetime.now(tz=ZoneInfo("America/Sao_Paulo"))
        self._logged_in = False

    @classmethod
    def from_settings(cls, settings: Settings) -> BlueskyPublisher:
        client = _make_atproto_client()
        return cls(
            client=client,
            handle=settings.bluesky_handle,
            app_password=settings.bluesky_app_password.get_secret_value(),
            session_path=settings.bluesky_session_path,
            enabled=settings.bluesky_enabled,
        )

    def _ensure_session(self) -> None:
        if self._logged_in:
            return
        session_str: str | None = None
        if self._session_path.exists():
            try:
                session_str = self._session_path.read_text(encoding="utf-8").strip() or None
            except OSError:
                session_str = None
        try:
            if session_str:
                self._client.login(self._handle, self._password, session_string=session_str)
            else:
                self._client.login(self._handle, self._password)
        except Exception as exc:
            raise PublishError(f"bluesky login failed: {exc}") from exc

        try:
            fresh = self._client.export_session_string()
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            self._session_path.write_text(fresh, encoding="utf-8")
        except (AttributeError, OSError) as exc:
            _log.warning("bluesky.session.persist_failed", error=str(exc))
        self._logged_in = True

    async def publish_thread(self, drafts: list[PostDraft]) -> list[PublishedPost]:
        if not drafts:
            return []
        self._ensure_session()
        posted: list[PublishedPost] = []
        root_ref: Any | None = None
        parent_ref: Any | None = None
        for draft in drafts:
            reply_to = None
            if root_ref is not None and parent_ref is not None:
                reply_to = {"root": root_ref, "parent": parent_ref}
            try:
                resp = self._client.send_post(text=draft.text, reply_to=reply_to)
            except Exception as exc:
                posted.append(_failed(draft, str(exc), self._now))
                break

            ref = _ref_of(resp)
            if root_ref is None:
                root_ref = ref
            parent_ref = ref

            posted.append(
                PublishedPost(
                    id=f"bsky-{draft.thread_index}-{draft.idempotency_key[-8:]}",
                    digest_id=draft.digest_id,
                    platform=draft.platform,
                    thread_index=draft.thread_index,
                    text=draft.text,
                    has_link=draft.has_link,
                    status=PostStatus.PUBLISHED,
                    external_id=getattr(resp, "uri", None)
                    or (resp.get("uri") if isinstance(resp, dict) else None),
                    cost_usd=0.0,
                    published_at=self._now,
                    idempotency_key=draft.idempotency_key,
                ),
            )
        return posted


def _failed(draft: PostDraft, error: str, now: datetime) -> PublishedPost:
    return PublishedPost(
        id=f"bsky-fail-{draft.thread_index}-{draft.idempotency_key[-8:]}",
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


def _ref_of(resp: Any) -> dict[str, str]:
    uri = getattr(resp, "uri", None) or (resp.get("uri") if isinstance(resp, dict) else None)
    cid = getattr(resp, "cid", None) or (resp.get("cid") if isinstance(resp, dict) else None)
    return {"uri": uri or "", "cid": cid or ""}


__all__ = ["BlueskyPublisher"]
