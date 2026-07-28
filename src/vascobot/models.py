"""Modelos de domínio — Pydantic v2. Todo datetime é aware (DTZ)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl


class Category(StrEnum):
    PROFISSIONAL = "profissional"
    FEMININO = "feminino"
    BASE_SUB20 = "base_sub20"
    BASE_SUB17 = "base_sub17"
    BASE_SUB15 = "base_sub15"
    DESCARTADO = "descartado"


class Platform(StrEnum):
    BLUESKY = "bluesky"
    X = "x"


class RunStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class PostStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"
    SKIPPED = "skipped"


class ArticleStatus(StrEnum):
    OK = "ok"
    PENDING_REVIEW = "pending_review"


class ClassifyMethod(StrEnum):
    RULE_EXCLUSION = "rule_exclusion"
    RULE_POSITIVE = "rule_positive"
    LLM = "llm"


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must be timezone-aware")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]


class _Base(BaseModel):
    model_config = ConfigDict(frozen=False, use_enum_values=False, str_strip_whitespace=True)


class RawArticle(_Base):
    """Saída do adapter — ainda não normalizado nem classificado."""

    source_id: str
    external_id: str | None
    url: str
    title: str
    summary: str | None = None
    body: str | None = None
    published_at: AwareDatetime
    fetched_at: AwareDatetime
    author: str | None = None


class Article(_Base):
    """Notícia normalizada, classificada, pronta para clustering."""

    id: str
    source_id: str
    external_id: str | None = None
    url: str
    title: str
    summary: str | None = None
    body: str | None = None
    published_at: AwareDatetime
    fetched_at: AwareDatetime
    content_hash: str
    category: Category | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    classify_method: str | None = None
    llm_model: str | None = None
    status: str = ArticleStatus.OK.value
    cluster_id: str | None = None
    run_id: str


class Cluster(_Base):
    id: str
    canonical_article_id: str
    category: Category
    size: int = Field(ge=1)
    run_id: str


class Digest(_Base):
    id: str
    run_id: str
    category: Category
    headline: str = Field(max_length=80)
    bullets: list[str] = Field(default_factory=list, max_length=4)
    source_urls: list[str] = Field(default_factory=list)
    llm_model: str | None = None


class PostDraft(_Base):
    digest_id: str
    platform: Platform
    thread_index: int = Field(ge=0)
    text: str
    has_link: bool
    idempotency_key: str


class PublishedPost(_Base):
    id: str
    digest_id: str
    platform: Platform
    thread_index: int = Field(ge=0)
    text: str
    has_link: bool
    status: PostStatus
    external_id: str | None = None
    cost_usd: float = 0.0
    published_at: AwareDatetime | None = None
    error: str | None = None
    idempotency_key: str


class Watermark(_Base):
    """Estado por fonte. Duplo: id sequencial (primário), ts (secundário)."""

    source_id: str
    ts: AwareDatetime | None = None
    external_id: str | None = None


class RunStats(_Base):
    run_id: str
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    window_start: AwareDatetime
    window_end: AwareDatetime
    status: RunStatus
    counts: dict[str, int] = Field(default_factory=dict)
    costs_usd: dict[str, float] = Field(default_factory=dict)
    per_stage_ms: dict[str, int] = Field(default_factory=dict)


__all__ = [
    "Article",
    "ArticleStatus",
    "AwareDatetime",
    "Category",
    "ClassifyMethod",
    "Cluster",
    "Digest",
    "HttpUrl",
    "Platform",
    "PostDraft",
    "PostStatus",
    "PublishedPost",
    "RawArticle",
    "RunStats",
    "RunStatus",
    "Watermark",
]
