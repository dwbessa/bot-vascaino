"""Observabilidade — T-031."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vascobot.db import Database
from vascobot.observability import Alert, check_alerts, render_stats

WINDOW = ("2026-07-27T00:00:00-03:00", "2026-07-27T06:00:00-03:00")


def _insert_run(
    db: Database,
    run_id: str,
    started_at: str,
    status: str,
    counts: dict[str, int],
    *,
    costs: dict[str, float] | None = None,
) -> None:
    payload = {"counts": counts, "costs_usd": costs or {}, "per_stage_ms": {}}
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO runs(id, started_at, window_start, window_end, status, stats_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, started_at, WINDOW[0], WINDOW[1], status, json.dumps(payload)),
        )


@pytest.fixture
def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "obs.db")
    d.migrate()
    return d


def test_render_stats_empty(db: Database) -> None:
    out = render_stats(db, days=7)
    assert "sem execuções" in out.lower() or "nenhum" in out.lower()


def test_render_stats_shows_per_day(db: Database) -> None:
    _insert_run(db, "r1", "2026-07-27T06:00:00-03:00", "ok", {"collected": 10, "digests": 3})
    _insert_run(db, "r2", "2026-07-27T09:00:00-03:00", "ok", {"collected": 5, "digests": 2})
    _insert_run(db, "r3", "2026-07-26T21:00:00-03:00", "partial", {"collected": 4, "digests": 1})
    out = render_stats(db, days=7)
    assert "2026-07-27" in out
    assert "2026-07-26" in out
    # soma do dia 27: 15 coletados
    assert "15" in out


def test_render_stats_respects_days_window(db: Database) -> None:
    _insert_run(db, "old", "2026-06-01T06:00:00-03:00", "ok", {"collected": 99})
    _insert_run(db, "new", "2026-07-27T06:00:00-03:00", "ok", {"collected": 3})
    out = render_stats(db, days=7, today="2026-07-27")
    assert "99" not in out
    assert "3" in out


# ------------------------------------------------------------------- alertas
def test_alert_source_failing_3_runs(db: Database) -> None:
    for i in range(3):
        _insert_run(
            db,
            f"r{i}",
            f"2026-07-27T0{i}:00:00-03:00",
            "partial",
            {"collected": 0, "sources_failed": 1},
        )
    alerts = check_alerts(db, today="2026-07-27")
    assert any(a.kind == "source_failing" for a in alerts)


def test_no_alert_when_source_recovers(db: Database) -> None:
    _insert_run(db, "r0", "2026-07-27T00:00:00-03:00", "partial", {"sources_failed": 1})
    _insert_run(db, "r1", "2026-07-27T01:00:00-03:00", "ok", {"sources_failed": 0})
    _insert_run(db, "r2", "2026-07-27T02:00:00-03:00", "ok", {"sources_failed": 0})
    alerts = check_alerts(db, today="2026-07-27")
    assert not any(a.kind == "source_failing" for a in alerts)


def test_alert_high_llm_fallback(db: Database) -> None:
    # 8 dos 10 coletados foram pro LLM (fallback) → 80% > 70%
    _insert_run(
        db,
        "r1",
        "2026-07-27T06:00:00-03:00",
        "ok",
        {"collected": 10, "kept": 10, "llm_classified": 8},
    )
    alerts = check_alerts(db, today="2026-07-27")
    assert any(a.kind == "high_llm_fallback" for a in alerts)


def test_alert_high_pending_review(db: Database) -> None:
    # 3 de 10 em pending → 30% > 20%
    _insert_run(
        db,
        "r1",
        "2026-07-27T06:00:00-03:00",
        "ok",
        {"collected": 10, "pending_review": 3},
    )
    alerts = check_alerts(db, today="2026-07-27")
    assert any(a.kind == "high_pending_review" for a in alerts)


def test_alert_x_budget_over_80(db: Database) -> None:
    _insert_run(
        db,
        "r1",
        "2026-07-27T06:00:00-03:00",
        "ok",
        {"collected": 5},
        costs={"x_month_projected": 85.0},
    )
    alerts = check_alerts(db, today="2026-07-27", x_budget_usd=100.0)
    assert any(a.kind == "x_budget_high" for a in alerts)


def test_no_x_budget_alert_when_no_budget(db: Database) -> None:
    _insert_run(
        db,
        "r1",
        "2026-07-27T06:00:00-03:00",
        "ok",
        {"collected": 5},
        costs={"x_month_projected": 85.0},
    )
    alerts = check_alerts(db, today="2026-07-27", x_budget_usd=None)
    assert not any(a.kind == "x_budget_high" for a in alerts)


def test_alert_dataclass_has_message() -> None:
    a = Alert(kind="test", message="algo", severity="error")
    assert a.message == "algo"
    assert a.severity == "error"
