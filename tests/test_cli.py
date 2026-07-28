"""CLI base — comandos vascobot."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from vascobot.cli import _default_registry, app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OLLAMA_API_KEY", "sk-fake")
    monkeypatch.setenv("BLUESKY_HANDLE", "bot.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "aaaa-bbbb-cccc-dddd")
    monkeypatch.setenv("X_ENABLED", "false")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "vascobot.db"))


def test_cli_help() -> None:
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "run" in r.stdout
    assert "sources" in r.stdout
    assert "db" in r.stdout


def test_default_registry_wires_client_into_adapters() -> None:
    """Regressão: o `run` real coletava 0 porque os adapters vinham sem client.

    Sem client injetado, `discover()` levanta RuntimeError e a coleta zera.
    """
    sentinel = object()
    reg = _default_registry(sentinel)
    for source_id in reg.ids():
        adapter = reg.get(source_id)
        assert adapter._client is sentinel, f"{source_id} não recebeu o client"


def test_default_registry_without_client_is_listing_only() -> None:
    reg = _default_registry()
    for source_id in reg.ids():
        assert reg.get(source_id)._client is None


def test_db_migrate_creates_file(tmp_path: Path) -> None:
    r = runner.invoke(app, ["db", "migrate"])
    assert r.exit_code == 0, r.stdout
    out = r.stdout.lower()
    assert "aplicad" in out or "migration" in out or "schema" in out


def test_sources_check_lists_registered() -> None:
    r = runner.invoke(app, ["sources", "check", "--offline"])
    assert r.exit_code == 0, r.stdout
    assert "netvasco" in r.stdout
    assert "supervasco" in r.stdout


def test_run_dry_run_prints_stats(tmp_path: Path) -> None:
    runner.invoke(app, ["db", "migrate"])
    r = runner.invoke(app, ["run", "--dry-run", "--offline"])
    assert r.exit_code == 0, r.stdout
    assert "offline smoke" in r.stdout.lower()
    assert "dry_run=true" in r.stdout.lower()
