"""Configuração via env — pydantic-settings. Fail fast se faltar segredo obrigatório."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field, SecretStr
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class XLinkPolicy(StrEnum):
    NONE = "none"
    LAST_POST = "last_post"
    ALL_POSTS = "all_posts"


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return value


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


CsvTuple = Annotated[tuple[str, ...], NoDecode, BeforeValidator(_split_csv)]
OptionalFloat = Annotated[float | None, BeforeValidator(_blank_to_none)]
OptionalSecret = Annotated[SecretStr | None, BeforeValidator(_blank_to_none)]


class Settings(BaseSettings):
    """Todas as variáveis do plan.md §7. Valida na largada."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Fontes -------------------------------------------------------------
    sources_enabled: CsvTuple = ("netvasco", "supervasco")
    max_lookback_hours: int = 8
    user_agent: str = "VascoDigestBot/1.0 (+contato@exemplo.com)"

    # --- LLM ----------------------------------------------------------------
    ollama_host: str = "https://ollama.com"
    ollama_api_key: SecretStr
    classify_model: str = "deepseek-v4-flash"
    summarize_model: str = "qwen3.5:397b"
    classify_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    classify_batch_size: int = Field(default=20, ge=1, le=100)
    include_institutional: bool = True

    # --- Bluesky ------------------------------------------------------------
    bluesky_enabled: bool = True
    bluesky_handle: str
    bluesky_app_password: SecretStr
    bluesky_session_path: Path = Path("./data/bsky_session.txt")

    # --- X ------------------------------------------------------------------
    x_enabled: bool = True
    x_client_id: OptionalSecret = None
    x_client_secret: OptionalSecret = None
    x_access_token: OptionalSecret = None
    x_refresh_token: OptionalSecret = None
    x_is_premium: bool = True
    x_link_policy: XLinkPolicy = XLinkPolicy.LAST_POST
    x_monthly_budget_usd: OptionalFloat = None

    # --- Operação -----------------------------------------------------------
    require_approval: bool = True
    max_posts_per_thread: int = Field(default=4, ge=1, le=8)
    db_path: Path = Path("./data/vascobot.db")
    log_level: str = "INFO"
    tz: str = "America/Sao_Paulo"
