"""CLI base (T-012). Comandos: run, sources, db.

`--offline` evita chamadas de rede — usado em teste e para inspecionar setup local.
"""

from __future__ import annotations

import typer

from vascobot.config import Settings
from vascobot.db import Database
from vascobot.logging import configure_logging
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
    since: str | None = typer.Option(None, help="Timestamp ISO — sobrescreve o watermark."),
    sources: str | None = typer.Option(None, help="CSV de fontes a rodar (default = config)."),
    offline: bool = typer.Option(False, "--offline", help="Não toca rede — smoke test."),
) -> None:
    """Executa o pipeline completo (nesta fase, só coleta e imprime resumo)."""
    settings = _load_settings()
    configure_logging(level=settings.log_level)
    active = tuple(sources.split(",")) if sources else settings.sources_enabled
    typer.echo(f"run dry-run={dry_run} offline={offline} sources={list(active)} since={since}")
    if offline:
        typer.echo("offline: pulando coleta real. Pipeline completo virá em T-029.")
        return
    typer.echo("coleta real ainda não plugada aqui (bloqueada por T-029).")


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


if __name__ == "__main__":
    app()
