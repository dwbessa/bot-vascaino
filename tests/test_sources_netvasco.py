"""Contrato do adapter NetVasco — parsing contra fixture RSS real."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from vascobot.models import Watermark
from vascobot.sources.netvasco import NetVascoAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "netvasco" / "rss.xml"


@pytest.mark.contract
def test_parses_rss_fixture() -> None:
    adapter = NetVascoAdapter()
    articles = asyncio.run(adapter.parse_rss(FIXTURE.read_bytes()))
    assert len(articles) >= 20, len(articles)

    for art in articles:
        assert art.source_id == "netvasco"
        assert art.external_id and art.external_id.isdigit()
        assert art.url.startswith("https://www.netvasco.com.br/n/")
        assert art.title.strip()
        assert art.published_at.tzinfo is not None
        assert art.fetched_at.tzinfo is not None


@pytest.mark.contract
def test_external_id_matches_url_segment() -> None:
    adapter = NetVascoAdapter()
    articles = asyncio.run(adapter.parse_rss(FIXTURE.read_bytes()))
    for art in articles[:5]:
        expected = art.url.split("/n/")[1].split("/")[0]
        assert art.external_id == expected


@pytest.mark.contract
def test_watermark_by_external_id_filters_older() -> None:
    """Watermark primário é o ID sequencial — imune a fuso."""
    adapter = NetVascoAdapter()
    all_articles = asyncio.run(adapter.parse_rss(FIXTURE.read_bytes()))
    ids_sorted = sorted((int(a.external_id) for a in all_articles if a.external_id), reverse=True)
    cutoff = ids_sorted[5]
    wm = Watermark(source_id="netvasco", external_id=str(cutoff))
    filtered = adapter.filter_since(all_articles, wm)
    remaining_ids = {int(a.external_id) for a in filtered if a.external_id}
    assert all(rid > cutoff for rid in remaining_ids)


@pytest.mark.contract
def test_pubdate_is_brt_aware() -> None:
    """RSS trazia `-0300` — a saída precisa ser aware, timestamp preservado."""
    adapter = NetVascoAdapter()
    arts = asyncio.run(adapter.parse_rss(FIXTURE.read_bytes()))
    for art in arts[:3]:
        offset = art.published_at.utcoffset()
        assert offset is not None
        assert offset.total_seconds() == -3 * 3600
