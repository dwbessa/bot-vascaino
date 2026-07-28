"""URL canonical, content_hash, hidratação."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from vascobot.models import RawArticle
from vascobot.pipeline.normalize import canonical_url, content_hash, normalize

BRT = ZoneInfo("America/Sao_Paulo")


def _raw(url: str, title: str = "T", body: str | None = None) -> RawArticle:
    now = datetime(2026, 7, 27, 12, tzinfo=BRT)
    return RawArticle(
        source_id="netvasco",
        external_id="1",
        url=url,
        title=title,
        summary=None,
        body=body,
        published_at=now,
        fetched_at=now,
    )


def test_canonical_url_strips_utm() -> None:
    src = "https://www.netvasco.com.br/n/1/x?utm_source=fb&utm_medium=cpc&keep=1"
    assert canonical_url(src) == "https://netvasco.com.br/n/1/x?keep=1"


def test_canonical_url_strips_q_and_fragment() -> None:
    src = "https://netvasco.com.br/n/1/x?q=abc#top"
    assert canonical_url(src) == "https://netvasco.com.br/n/1/x"


def test_canonical_url_normalizes_www() -> None:
    a = canonical_url("https://www.netvasco.com.br/n/1/x")
    b = canonical_url("https://netvasco.com.br/n/1/x")
    assert a == b == "https://netvasco.com.br/n/1/x"


def test_canonical_url_lowercases_host() -> None:
    assert canonical_url("HTTPS://NetVasco.COM.BR/n/1/x") == "https://netvasco.com.br/n/1/x"


def test_canonical_url_strips_trailing_slash() -> None:
    assert canonical_url("https://netvasco.com.br/n/1/x/") == "https://netvasco.com.br/n/1/x"


def test_two_urls_same_article_same_id() -> None:
    a = normalize(_raw("https://www.netvasco.com.br/n/1/x?utm_source=x"))
    b = normalize(_raw("https://netvasco.com.br/n/1/x?q=y#foo"))
    assert a.id == b.id
    assert a.url == b.url


def test_content_hash_is_stable_and_ignores_whitespace() -> None:
    h1 = content_hash("Título", "Corpo do artigo com detalhes")
    h2 = content_hash("Título", "Corpo  do   artigo  com detalhes")
    assert h1 == h2
    assert h1 != content_hash("Título", "Corpo diferente")


def test_normalize_falls_back_to_summary_when_no_body() -> None:
    raw = _raw("https://x/y", body=None)
    raw = raw.model_copy(update={"summary": "lide curto"})
    art = normalize(raw)
    assert art.body == "lide curto"


def test_normalize_populates_content_hash() -> None:
    art = normalize(_raw("https://x/y", body="corpo"))
    assert art.content_hash
    assert len(art.content_hash) == 64  # sha256 hex


def test_normalize_preserves_run_id_when_provided() -> None:
    art = normalize(_raw("https://x/y"), run_id="run-42")
    assert art.run_id == "run-42"
