"""Contrato do adapter SuperVasco — parsing da listagem HTML."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.models import Watermark
from vascobot.sources.supervasco import SuperVascoAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "supervasco" / "listing.html"
BRT = ZoneInfo("America/Sao_Paulo")


@pytest.mark.contract
def test_parses_listing_min_40() -> None:
    """DoD: ≥ 40 artigos com published_at aware."""
    adapter = SuperVascoAdapter()
    now = datetime(2026, 7, 27, 22, 30, tzinfo=BRT)
    arts = adapter.parse_listing(FIXTURE.read_bytes(), reference_now=now)
    assert len(arts) >= 40, len(arts)
    for a in arts:
        assert a.source_id == "supervasco"
        assert a.external_id and a.external_id.isdigit()
        assert a.url.startswith("https://www.supervasco.com/noticias/")
        assert a.published_at.tzinfo is not None
        assert a.title.strip()


@pytest.mark.contract
def test_day_boundary_respected() -> None:
    """Artigos antes do primeiro header 'Domingo, 26/07/2026' são de hoje (27/07)."""
    adapter = SuperVascoAdapter()
    now = datetime(2026, 7, 27, 22, 30, tzinfo=BRT)
    arts = adapter.parse_listing(FIXTURE.read_bytes(), reference_now=now)
    by_id = {a.external_id: a for a in arts}
    art_top = by_id["451859"]
    assert art_top.published_at.date() == date(2026, 7, 27)
    assert art_top.published_at.hour == 22
    assert art_top.published_at.minute == 9

    art_yesterday = by_id.get("451800")
    assert art_yesterday is not None
    assert art_yesterday.published_at.date() == date(2026, 7, 26)


@pytest.mark.contract
def test_top_prefix_stripped_from_time() -> None:
    adapter = SuperVascoAdapter()
    now = datetime(2026, 7, 27, 22, 30, tzinfo=BRT)
    arts = adapter.parse_listing(FIXTURE.read_bytes(), reference_now=now)
    art = next(a for a in arts if a.external_id == "451855")
    assert art.published_at.hour == 21
    assert art.published_at.minute == 17


@pytest.mark.contract
def test_ignores_external_and_schedule_headers() -> None:
    """Links que saem do domínio não viram artigo; 'às HHhMM' em header não vira divisor."""
    adapter = SuperVascoAdapter()
    now = datetime(2026, 7, 27, 22, 30, tzinfo=BRT)
    arts = adapter.parse_listing(FIXTURE.read_bytes(), reference_now=now)
    assert all("supervasco.com" in a.url for a in arts)


@pytest.mark.contract
def test_watermark_filters_by_external_id() -> None:
    adapter = SuperVascoAdapter()
    now = datetime(2026, 7, 27, 22, 30, tzinfo=BRT)
    arts = adapter.parse_listing(FIXTURE.read_bytes(), reference_now=now)
    ids = sorted((int(a.external_id) for a in arts if a.external_id), reverse=True)
    cutoff = ids[10]
    kept = adapter.filter_since(arts, Watermark(source_id="supervasco", external_id=str(cutoff)))
    assert all(int(a.external_id) > cutoff for a in kept if a.external_id)
