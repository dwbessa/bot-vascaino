"""CLI base (T-012). Comandos: run, sources, db.

`--offline` evita chamadas de rede — usado em teste e para inspecionar setup local.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import typer

from vascobot.config import Settings
from vascobot.db import Database
from vascobot.logging import configure_logging
from vascobot.repo import PostRepo
from vascobot.sources.netvasco import NetVascoAdapter
from vascobot.sources.registry import SourceRegistry
from vascobot.sources.supervasco import SuperVascoAdapter

app = typer.Typer(help="Vasco Digest Bot — CLI")
sources_app = typer.Typer(help="Comandos de fontes")
db_app = typer.Typer(help="Comandos do banco de dados")
app.add_typer(sources_app, name="sources")
app.add_typer(db_app, name="db")


def _load_settings() -> Settings:
    return Settings()


def _default_registry() -> SourceRegistry:
    reg = SourceRegistry()
    reg.register(NetVascoAdapter())
    reg.register(SuperVascoAdapter())
    return reg


@app.command()
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="Não publica, só imprime stats."),
    sources: str | None = typer.Option(None, help="CSV de fontes a rodar (default = config)."),
    offline: bool = typer.Option(False, "--offline", help="Não toca rede — smoke test."),
) -> None:
    """Executa o pipeline completo: coleta → classifica → resume → compõe → publica."""
    settings = _load_settings()
    configure_logging(level=settings.log_level)
    active = tuple(sources.split(",")) if sources else settings.sources_enabled

    if offline:
        typer.echo(f"offline smoke: sources={list(active)} dry_run={dry_run}")
        return

    # Imports pesados (atproto, ollama) só quando for rodar de verdade.
    from vascobot.llm.ollama_cloud import OllamaCloudProvider  # noqa: PLC0415
    from vascobot.pipeline.run import run_pipeline  # noqa: PLC0415
    from vascobot.publishers.bluesky import BlueskyPublisher  # noqa: PLC0415
    from vascobot.publishers.registry import PublisherRegistry  # noqa: PLC0415

    db = Database(settings.db_path)
    db.migrate()

    source_reg = _default_registry()
    pub_reg = PublisherRegistry()
    if settings.bluesky_enabled:
        pub_reg.register(BlueskyPublisher.from_settings(settings))
    # X é plugado aqui quando habilitado — omitido no dry-run offline padrão.

    provider = OllamaCloudProvider.from_settings(settings)
    now = datetime.now(tz=ZoneInfo(settings.tz))

    stats = asyncio.run(
        run_pipeline(
            db=db,
            settings=settings,
            source_registry=source_reg,
            publisher_registry=pub_reg,
            llm_provider=provider,
            now=now,
            dry_run=dry_run,
        ),
    )
    typer.echo(json.dumps({"run_id": stats.run_id, "status": stats.status.value, **stats.counts}))


@sources_app.command("check")
def sources_check(
    offline: bool = typer.Option(False, "--offline", help="Não toca rede — só lista o registro."),
) -> None:
    """Lista fontes registradas e opcionalmente faz ping em cada uma."""
    settings = _load_settings()
    configure_logging(level=settings.log_level)
    registry = _default_registry()
    for source_id in registry.ids():
        adapter = registry.get(source_id)
        status = "registered" if offline else "check-not-implemented"
        typer.echo(f"{source_id:12s} {adapter.base_url:40s} {status}")


@db_app.command("migrate")
def db_migrate() -> None:
    """Aplica migrations no SQLite. Idempotente."""
    settings = _load_settings()
    configure_logging(level=settings.log_level)
    db = Database(settings.db_path)
    applied = db.migrate()
    if applied:
        typer.echo(f"migrations aplicadas: {', '.join(applied)}")
    else:
        typer.echo("nenhuma migration pendente — schema ok")


@app.command()
def approve(
    run_id: str = typer.Option(..., "--run-id", help="Run cujos posts pending serão liberados."),
    category: str | None = typer.Option(None, "--category", help="Filtra por categoria."),
) -> None:
    """RF-10 — mostra os drafts pending e libera para publicação."""
    settings = _load_settings()
    configure_logging(level=settings.log_level)
    repo = PostRepo(Database(settings.db_path))

    pending = [p for p in repo.list_pending() if _matches(p, category)]
    if not pending:
        typer.echo("nenhum post pending para esse filtro")
        return
    for p in pending:
        typer.echo(f"[{p.platform}] {p.idempotency_key}\n  {p.text}")
    n = repo.approve(run_id=run_id, category=category)
    typer.echo(f"aprovados: {n}")


@app.command()
def reject(
    run_id: str = typer.Option(..., "--run-id", help="Run cujos posts pending serão rejeitados."),
    category: str | None = typer.Option(None, "--category", help="Filtra por categoria."),
) -> None:
    """Rejeita drafts pending — marca como skipped, nunca publica."""
    settings = _load_settings()
    configure_logging(level=settings.log_level)
    repo = PostRepo(Database(settings.db_path))
    n = repo.reject(run_id=run_id, category=category)
    typer.echo(f"rejeitados: {n}")


def _matches(post: object, category: str | None) -> bool:
    if category is None:
        return True
    key = getattr(post, "idempotency_key", "")
    return f":{category}:" in key


@app.command()
def stats(
    days: int = typer.Option(7, "--days", help="Janela de dias a resumir."),
) -> None:
    """Tabela por dia + alertas (T-031)."""
    from vascobot.observability import check_alerts, render_stats  # noqa: PLC0415

    settings = _load_settings()
    configure_logging(level=settings.log_level)
    db = Database(settings.db_path)

    typer.echo(render_stats(db, days=days))
    alerts = check_alerts(db, x_budget_usd=settings.x_monthly_budget_usd, lookback_days=days)
    if alerts:
        typer.echo("\nALERTAS:")
        for a in alerts:
            typer.echo(f"  [{a.severity}] {a.kind}: {a.message}")


if __name__ == "__main__":
    app()
