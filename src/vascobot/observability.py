"""Observabilidade — T-031.

- `render_stats(db, days)`: tabela por dia e por categoria (via CLI `stats`).
- `check_alerts(db, ...)`: dispara alertas (log ERROR) quando:
  fonte falha 3 runs seguidos, fallback p/ LLM > 70%, gasto do X > 80% do teto,
  ou taxa de `pending_review` > 20%.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from vascobot.db import Database

BRT = ZoneInfo("America/Sao_Paulo")

_SOURCE_FAIL_STREAK = 3
_LLM_FALLBACK_MAX = 0.70
_PENDING_REVIEW_MAX = 0.20
_X_BUDGET_ALERT_FRACTION = 0.80


@dataclass(frozen=True)
class Alert:
    kind: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class _RunRow:
    run_id: str
    started_at: str
    status: str
    counts: dict[str, int]
    costs: dict[str, float]

    @property
    def day(self) -> str:
        return self.started_at[:10]


def _load_runs(db: Database, *, since_day: str) -> list[_RunRow]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, started_at, status, stats_json FROM runs"
            " WHERE substr(started_at, 1, 10) >= ?"
            " ORDER BY started_at",
            (since_day,),
        ).fetchall()
    out: list[_RunRow] = []
    for run_id, started_at, status, stats_json in rows:
        payload = json.loads(stats_json) if stats_json else {}
        out.append(
            _RunRow(
                run_id=str(run_id),
                started_at=str(started_at),
                status=str(status),
                counts=payload.get("counts", {}),
                costs=payload.get("costs_usd", {}),
            ),
        )
    return out


def _since_day(today: str | None, days: int) -> tuple[str, str]:
    ref = date.fromisoformat(today) if today else datetime.now(tz=BRT).date()
    start = ref - timedelta(days=days)
    return start.isoformat(), ref.isoformat()


def render_stats(db: Database, *, days: int = 7, today: str | None = None) -> str:
    since, _ref = _since_day(today, days)
    runs = _load_runs(db, since_day=since)
    if not runs:
        return "sem execuções na janela"

    by_day: dict[str, dict[str, int]] = {}
    for r in runs:
        agg = by_day.setdefault(r.day, {})
        for key in ("collected", "kept", "descartado", "digests", "pending_review"):
            agg[key] = agg.get(key, 0) + int(r.counts.get(key, 0))

    lines = ["dia         | runs | coletados | mantidos | descartados | digests | pending"]
    lines.append("-" * len(lines[0]))
    runs_per_day: dict[str, int] = {}
    for r in runs:
        runs_per_day[r.day] = runs_per_day.get(r.day, 0) + 1
    for day in sorted(by_day, reverse=True):
        agg = by_day[day]
        lines.append(
            f"{day} | {runs_per_day[day]:>4} | {agg.get('collected', 0):>9} |"
            f" {agg.get('kept', 0):>8} | {agg.get('descartado', 0):>11} |"
            f" {agg.get('digests', 0):>7} | {agg.get('pending_review', 0):>7}",
        )
    return "\n".join(lines)


def check_alerts(
    db: Database,
    *,
    today: str | None = None,
    x_budget_usd: float | None = None,
    lookback_days: int = 7,
) -> list[Alert]:
    since, _ref = _since_day(today, lookback_days)
    runs = _load_runs(db, since_day=since)
    alerts: list[Alert] = []

    _check_source_streak(runs, alerts)
    _check_llm_fallback(runs, alerts)
    _check_pending_review(runs, alerts)
    _check_x_budget(runs, alerts, x_budget_usd)
    return alerts


def _check_source_streak(runs: list[_RunRow], alerts: list[Alert]) -> None:
    if len(runs) < _SOURCE_FAIL_STREAK:
        return
    tail = runs[-_SOURCE_FAIL_STREAK:]
    if all(int(r.counts.get("sources_failed", 0)) > 0 for r in tail):
        alerts.append(
            Alert(
                kind="source_failing",
                message=f"fonte falhou nos últimos {_SOURCE_FAIL_STREAK} runs seguidos",
            ),
        )


def _check_llm_fallback(runs: list[_RunRow], alerts: list[Alert]) -> None:
    kept = sum(int(r.counts.get("kept", 0)) for r in runs)
    llm = sum(int(r.counts.get("llm_classified", 0)) for r in runs)
    if kept > 0 and llm / kept > _LLM_FALLBACK_MAX:
        alerts.append(
            Alert(
                kind="high_llm_fallback",
                message=f"taxa de fallback p/ LLM {llm / kept:.0%} > {_LLM_FALLBACK_MAX:.0%}",
            ),
        )


def _check_pending_review(runs: list[_RunRow], alerts: list[Alert]) -> None:
    collected = sum(int(r.counts.get("collected", 0)) for r in runs)
    pending = sum(int(r.counts.get("pending_review", 0)) for r in runs)
    if collected > 0 and pending / collected > _PENDING_REVIEW_MAX:
        rate = pending / collected
        alerts.append(
            Alert(
                kind="high_pending_review",
                message=f"taxa de pending_review {rate:.0%} > {_PENDING_REVIEW_MAX:.0%}",
            ),
        )


def _check_x_budget(runs: list[_RunRow], alerts: list[Alert], x_budget_usd: float | None) -> None:
    if x_budget_usd is None or x_budget_usd <= 0:
        return
    projected = max((r.costs.get("x_month_projected", 0.0) for r in runs), default=0.0)
    if projected > _X_BUDGET_ALERT_FRACTION * x_budget_usd:
        alerts.append(
            Alert(
                kind="x_budget_high",
                message=f"projeção do X US$ {projected:.2f} > 80% do teto US$ {x_budget_usd:.2f}",
            ),
        )


__all__ = ["Alert", "check_alerts", "render_stats"]
