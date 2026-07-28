"""CA-07 — notícia das 02:00 BRT aparece no digest das 06:00.

O container (T-030) só agenda `vascobot run` na grade. A garantia real da
cobertura é a janela `compute_window` + a grade do crontab. Este teste prova
as duas coisas sem subir Docker: a janela de cada horário e a grade do arquivo.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vascobot.pipeline.run import compute_window

BRT = ZoneInfo("America/Sao_Paulo")
CRONTAB = Path(__file__).parent.parent.parent / "crontab"
LOOKBACK = 8

GRID_HOURS = [0, 6, 9, 12, 15, 18, 21]


@pytest.mark.acceptance
def test_ca07_overnight_window_covered() -> None:
    """A run das 06:00 (lookback 8h) cobre uma notícia publicada às 02:00."""
    run_0600 = datetime(2026, 7, 27, 6, 0, tzinfo=BRT)
    start, end = compute_window(run_0600, lookback_hours=LOOKBACK)
    news_0200 = datetime(2026, 7, 27, 2, 0, tzinfo=BRT)
    assert start <= news_0200 <= end


@pytest.mark.acceptance
def test_ca07_grid_leaves_no_gap_bigger_than_lookback() -> None:
    """Nenhum intervalo entre horários da grade excede o lookback — nada some."""
    times = [datetime(2026, 7, 27, h, 0, tzinfo=BRT) for h in GRID_HOURS]
    # adiciona o primeiro horário do dia seguinte para fechar o ciclo 21h→00h
    times.append(datetime(2026, 7, 28, 0, 0, tzinfo=BRT))
    for earlier, later in pairwise(times):
        gap = later - earlier
        assert gap <= timedelta(hours=LOOKBACK), f"vão {gap} entre {earlier} e {later}"


@pytest.mark.acceptance
def test_ca07_every_instant_covered_by_some_run() -> None:
    """Qualquer instante do dia cai na janela de pelo menos um horário da grade."""
    runs = [datetime(2026, 7, 27, h, 0, tzinfo=BRT) for h in GRID_HOURS]
    runs.append(datetime(2026, 7, 28, 0, 0, tzinfo=BRT))
    windows = [compute_window(r, lookback_hours=LOOKBACK) for r in runs]

    # varre o dia de 30 em 30 min
    probe = datetime(2026, 7, 27, 0, 0, tzinfo=BRT)
    day_end = datetime(2026, 7, 28, 0, 0, tzinfo=BRT)
    while probe < day_end:
        covered = any(start <= probe <= end for start, end in windows)
        assert covered, f"instante {probe} não coberto por nenhuma run"
        probe += timedelta(minutes=30)


def test_crontab_grid_matches_spec() -> None:
    """O crontab agenda exatamente os 7 horários da RF-09."""
    content = CRONTAB.read_text(encoding="utf-8")
    match = re.search(r"^0\s+([\d,]+)\s+\*\s+\*\s+\*\s+", content, re.MULTILINE)
    assert match, "linha de cron não encontrada"
    hours = sorted(int(h) for h in match.group(1).split(","))
    assert hours == GRID_HOURS


def test_crontab_runs_as_nonroot_user() -> None:
    content = CRONTAB.read_text(encoding="utf-8")
    assert "vascobot vascobot run" in content, "job deve rodar como usuário vascobot"
