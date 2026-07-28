"""Publisher Bluesky — T-025 (unit sem rede)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from vascobot.models import Platform, PostDraft, PostStatus
from vascobot.publishers.base import PublishError
from vascobot.publishers.bluesky import BlueskyPublisher, _url_spans

BRT = ZoneInfo("America/Sao_Paulo")


# ------------------------------------------------------------------ facets
def test_url_spans_simple_ascii() -> None:
    text = "veja: https://a.com/p aqui"
    spans = _url_spans(text)
    assert spans == [("https://a.com/p", 6, 6 + len("https://a.com/p"))]


def test_url_spans_byte_offsets_with_emoji_and_accent() -> None:
    """Offset é em BYTES UTF-8 — emoji e acento não podem bagunçar."""
    prefix = "🔵⚫ São Januário: "
    url = "https://netvasco.com.br/n/1/x"
    text = f"{prefix}{url}"
    spans = _url_spans(text)
    assert len(spans) == 1
    got_url, byte_start, byte_end = spans[0]
    assert got_url == url
    assert byte_start == len(prefix.encode("utf-8"))
    assert byte_end == len(text.encode("utf-8"))


def test_url_spans_multiple_urls() -> None:
    text = "fontes: https://a.com/1 · https://b.com/2"
    spans = _url_spans(text)
    assert [s[0] for s in spans] == ["https://a.com/1", "https://b.com/2"]


def test_url_spans_strips_trailing_ellipsis() -> None:
    text = "fontes: https://a.com/muito-longo…"
    spans = _url_spans(text)
    assert spans[0][0] == "https://a.com/muito-longo"


def test_url_spans_empty_when_no_url() -> None:
    assert _url_spans("🔵⚫ PROFISSIONAL\nsem link aqui") == []


@dataclass
class _FakeClient:
    login_calls: list[tuple[str, str, str | None]] = field(default_factory=list)
    posts: list[dict[str, Any]] = field(default_factory=list)
    session_string: str = "SESSION_TOKEN"
    raise_on_login: Exception | None = None
    raise_on_session_login: Exception | None = None
    raise_on_post_index: int | None = None

    def login(self, handle: str, password: str, session_string: str | None = None) -> None:
        self.login_calls.append((handle, password, session_string))
        if session_string is not None and self.raise_on_session_login is not None:
            raise self.raise_on_session_login
        if self.raise_on_login is not None:
            raise self.raise_on_login

    def send_post(
        self, text: str, reply_to: Any | None = None, facets: Any | None = None
    ) -> dict[str, str]:
        idx = len(self.posts)
        if self.raise_on_post_index is not None and idx == self.raise_on_post_index:
            raise RuntimeError("boom")
        rec = {
            "text": text,
            "reply_to": reply_to,
            "facets": facets,
            "uri": f"at://did/{idx}",
            "cid": f"cid{idx}",
        }
        self.posts.append(rec)
        return rec

    def export_session_string(self) -> str:
        return self.session_string


def _drafts(n: int) -> list[PostDraft]:
    return [
        PostDraft(
            digest_id="d",
            platform=Platform.BLUESKY,
            thread_index=i,
            text=f"post {i}",
            has_link=(i == n - 1),
            idempotency_key=f"r:profissional:bluesky:{i}",
        )
        for i in range(n)
    ]


def _pub(tmp_path: Path, client: _FakeClient, session_seed: str | None = None) -> BlueskyPublisher:
    session_path = tmp_path / "bsky.txt"
    if session_seed is not None:
        session_path.write_text(session_seed, encoding="utf-8")
    return BlueskyPublisher(
        client=client,  # type: ignore[arg-type]
        handle="bot.bsky.social",
        app_password="aaaa-bbbb-cccc-dddd",
        session_path=session_path,
        now=datetime(2026, 7, 27, 12, tzinfo=BRT),
    )


def test_first_run_logs_in_with_password_and_persists_session(tmp_path: Path) -> None:
    client = _FakeClient()
    pub = _pub(tmp_path, client)
    asyncio.run(pub.publish_thread(_drafts(1)))
    # 1 login sem session_string
    assert len(client.login_calls) == 1
    assert client.login_calls[0][2] is None
    # sessão gravada
    assert (tmp_path / "bsky.txt").read_text().strip() == "SESSION_TOKEN"


def test_second_run_reuses_persisted_session(tmp_path: Path) -> None:
    client = _FakeClient()
    pub = _pub(tmp_path, client, session_seed="SESSION_TOKEN")
    asyncio.run(pub.publish_thread(_drafts(1)))
    # Passou session_string na chamada — respeitando limite de createSession
    assert client.login_calls[0][2] == "SESSION_TOKEN"


def test_stale_session_falls_back_to_fresh_login(tmp_path: Path) -> None:
    """Sessão obsoleta (troca de handle / expiração) → refaz login com senha."""
    client = _FakeClient(
        raise_on_session_login=RuntimeError("Profile not found"),
    )
    pub = _pub(tmp_path, client, session_seed="STALE_FROM_OLD_HANDLE")
    posts = asyncio.run(pub.publish_thread(_drafts(1)))

    assert all(p.status is PostStatus.PUBLISHED for p in posts)
    # 1ª tentativa com session_string (falha), 2ª limpa (sucesso)
    assert client.login_calls[0][2] == "STALE_FROM_OLD_HANDLE"
    assert client.login_calls[1][2] is None
    # sessão nova (válida) foi persistida por cima da obsoleta
    assert (tmp_path / "bsky.txt").read_text().strip() == "SESSION_TOKEN"


def test_fresh_login_failure_still_raises_publish_error(tmp_path: Path) -> None:
    """Se até o login limpo falha (credencial ruim), erro claro."""
    client = _FakeClient(
        raise_on_session_login=RuntimeError("stale"),
        raise_on_login=RuntimeError("bad password"),
    )
    pub = _pub(tmp_path, client, session_seed="STALE")
    with pytest.raises(PublishError):
        asyncio.run(pub.publish_thread(_drafts(1)))


def test_publish_thread_uses_refs_root_and_parent(tmp_path: Path) -> None:
    client = _FakeClient()
    pub = _pub(tmp_path, client)
    posts = asyncio.run(pub.publish_thread(_drafts(3)))

    assert len(posts) == 3
    assert all(p.status is PostStatus.PUBLISHED for p in posts)

    # o primeiro post não tem reply_to; o 2º e o 3º sim
    assert client.posts[0]["reply_to"] is None
    root_ref = {"uri": client.posts[0]["uri"], "cid": client.posts[0]["cid"]}
    parent_ref_1 = {"uri": client.posts[0]["uri"], "cid": client.posts[0]["cid"]}
    assert client.posts[1]["reply_to"] == {"root": root_ref, "parent": parent_ref_1}
    parent_ref_2 = {"uri": client.posts[1]["uri"], "cid": client.posts[1]["cid"]}
    assert client.posts[2]["reply_to"] == {"root": root_ref, "parent": parent_ref_2}


def test_single_login_across_multiple_publish_calls(tmp_path: Path) -> None:
    """Instância única não abre nova sessão — protege o limite de 30/5min."""
    client = _FakeClient()
    pub = _pub(tmp_path, client)
    asyncio.run(pub.publish_thread(_drafts(1)))
    asyncio.run(pub.publish_thread(_drafts(1)))
    assert len(client.login_calls) == 1


def test_post_with_url_gets_facets(tmp_path: Path) -> None:
    """Link vira clicável — facet enviado ao send_post quando há URL no texto."""
    client = _FakeClient()
    pub = _pub(tmp_path, client)
    drafts = [
        PostDraft(
            digest_id="d",
            platform=Platform.BLUESKY,
            thread_index=0,
            text="fontes: https://netvasco.com.br/n/1/x",
            has_link=True,
            idempotency_key="r:profissional:bluesky:0",
        ),
    ]
    asyncio.run(pub.publish_thread(drafts))
    facets = client.posts[0]["facets"]
    assert facets is not None
    assert len(facets) == 1


def test_post_without_url_has_no_facets(tmp_path: Path) -> None:
    client = _FakeClient()
    pub = _pub(tmp_path, client)
    drafts = [
        PostDraft(
            digest_id="d",
            platform=Platform.BLUESKY,
            thread_index=0,
            text="🔵⚫ PROFISSIONAL\nVasco vence",
            has_link=False,
            idempotency_key="r:profissional:bluesky:0",
        ),
    ]
    asyncio.run(pub.publish_thread(drafts))
    assert client.posts[0]["facets"] is None


def test_login_failure_raises_publish_error(tmp_path: Path) -> None:
    client = _FakeClient(raise_on_login=RuntimeError("bad creds"))
    pub = _pub(tmp_path, client)
    with pytest.raises(PublishError):
        asyncio.run(pub.publish_thread(_drafts(1)))


def test_post_failure_stops_thread_and_marks_failed(tmp_path: Path) -> None:
    client = _FakeClient(raise_on_post_index=1)
    pub = _pub(tmp_path, client)
    posts = asyncio.run(pub.publish_thread(_drafts(3)))
    # 1 sucesso, 1 falha, 3º não sai
    assert [p.status for p in posts] == [PostStatus.PUBLISHED, PostStatus.FAILED]
    assert posts[-1].error and "boom" in posts[-1].error


def test_empty_drafts_no_login(tmp_path: Path) -> None:
    client = _FakeClient()
    pub = _pub(tmp_path, client)
    result = asyncio.run(pub.publish_thread([]))
    assert result == []
    assert client.login_calls == []


def test_costs_are_zero(tmp_path: Path) -> None:
    client = _FakeClient()
    pub = _pub(tmp_path, client)
    posts = asyncio.run(pub.publish_thread(_drafts(2)))
    assert all(p.cost_usd == 0.0 for p in posts)
