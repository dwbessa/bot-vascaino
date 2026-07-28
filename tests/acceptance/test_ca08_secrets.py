"""CA-08 — segredo nunca vaza no log."""

from __future__ import annotations

import io
import json

import pytest
import structlog

from vascobot.logging import configure_logging, redact_secrets

SECRET = "sk-super-segredo-abcdefg"


@pytest.mark.acceptance
def test_ca08_no_secrets_in_logs() -> None:
    """Passar segredo em qualquer chave sensível → não aparece na saída."""
    buf = io.StringIO()
    configure_logging(level="INFO", stream=buf, json=True)
    log = structlog.get_logger()

    log.info(
        "publicando",
        api_key=SECRET,
        bluesky_app_password="aaaa-bbbb-cccc-dddd",
        ollama_api_key=SECRET,
        x_client_secret=SECRET,
        nested={"token": SECRET, "user": "bot"},
        ok=True,
    )

    out = buf.getvalue()
    assert SECRET not in out
    assert "aaaa-bbbb-cccc-dddd" not in out
    assert "bot" in out
    row = json.loads(out.strip().splitlines()[-1])
    assert row["ok"] is True
    assert row["api_key"] == "***"
    assert row["nested"]["token"] == "***"


def test_redact_secrets_direct() -> None:
    """Contrato do processor puro — independe do structlog rodando."""
    event = {
        "api_key": SECRET,
        "some_token": "xyz",
        "password_hash": "hashy",
        "user_secret_ref": "sr-1",
        "harmless": "ok",
        "deep": {"inner_token": "z", "keep": 1},
        "seq": [{"key_id": "k", "v": 1}],
    }
    out = redact_secrets(None, "info", event)
    assert out["api_key"] == "***"
    assert out["some_token"] == "***"
    assert out["password_hash"] == "***"
    assert out["user_secret_ref"] == "***"
    assert out["harmless"] == "ok"
    assert out["deep"]["inner_token"] == "***"
    assert out["deep"]["keep"] == 1
    assert out["seq"][0]["key_id"] == "***"
    assert out["seq"][0]["v"] == 1
