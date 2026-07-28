"""Config validation — RNF-04."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from vascobot.config import Settings, XLinkPolicy

BASE_ENV: dict[str, str] = {
    "OLLAMA_API_KEY": "sk-fake-value-123",
    "BLUESKY_HANDLE": "bot.bsky.social",
    "BLUESKY_APP_PASSWORD": "aaaa-bbbb-cccc-dddd",
    "X_ENABLED": "false",
}


def _apply(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_missing_ollama_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {k: v for k, v in BASE_ENV.items() if k != "OLLAMA_API_KEY"}
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    _apply(monkeypatch, env)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert "ollama_api_key" in str(exc.value).lower()


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, BASE_ENV)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.max_lookback_hours == 8
    assert s.classify_confidence_threshold == 0.7
    assert s.classify_batch_size == 20
    assert s.include_institutional is True
    assert s.max_posts_per_thread == 4
    assert s.x_link_policy is XLinkPolicy.LAST_POST
    assert s.tz == "America/Sao_Paulo"


def test_sources_enabled_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, BASE_ENV)
    monkeypatch.setenv("SOURCES_ENABLED", "netvasco,supervasco")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.sources_enabled == ("netvasco", "supervasco")


def test_x_link_policy_enum(monkeypatch: pytest.MonkeyPatch) -> None:
    _apply(monkeypatch, BASE_ENV)
    monkeypatch.setenv("X_LINK_POLICY", "none")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.x_link_policy is XLinkPolicy.NONE
