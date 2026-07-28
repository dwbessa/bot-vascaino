"""CA-03 — par NetVasco/SuperVasco do mesmo fato agrupa; times diferentes não."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from vascobot.models import Article, ArticleStatus, Category
from vascobot.pipeline.classify_pipeline import ClassifiedArticle
from vascobot.pipeline.dedupe import cluster

BRT = ZoneInfo("America/Sao_Paulo")


def _classified(
    ext_id: str,
    title: str,
    *,
    source: str = "netvasco",
    minutes_after: int = 0,
    category: Category = Category.PROFISSIONAL,
) -> ClassifiedArticle:
    base = datetime(2026, 7, 27, 12, tzinfo=BRT)
    published = base + timedelta(minutes=minutes_after)
    article = Article(
        id=f"h-{ext_id}",
        source_id=source,
        external_id=ext_id,
        url=f"https://{source}.invalid/n/{ext_id}",
        title=title,
        summary=None,
        body=None,
        published_at=published,
        fetched_at=published,
        content_hash=f"c-{ext_id}",
        status=ArticleStatus.OK.value,
        run_id="r",
    )
    return ClassifiedArticle(
        article=article,
        category=category,
        confidence=0.95,
        method=None,  # type: ignore[arg-type]  # não importa aqui
        llm_model=None,
        status=ArticleStatus.OK.value,
        motivo="",
    )


@pytest.mark.acceptance
def test_ca03_cross_source_dedup() -> None:
    """Mesmo fato descrito por NetVasco e SuperVasco cai no mesmo cluster.

    Pareamento realista: SuperVasco frequentemente republica NetVasco
    (`NTV: ...`) — títulos quase idênticos, variação mínima. Ver research.md §1.2.
    """
    items = [
        _classified(
            "1",
            "Vasco vence o Bahia por 2 a 1 em São Januário",
            source="netvasco",
            minutes_after=0,
        ),
        _classified(
            "2",
            "NTV: Vasco vence o Bahia por 2 a 1 em São Januário (foto)",
            source="supervasco",
            minutes_after=15,
        ),
        _classified(
            "3",
            "Vasco vence o Santos e mantém invencibilidade",
            source="netvasco",
            minutes_after=120,
        ),
    ]

    clusters = cluster(items)
    ids_por_cluster = [sorted(a.article.external_id for a in c.items) for c in clusters]
    ids_por_cluster.sort()
    assert ["1", "2"] in ids_por_cluster
    assert ["3"] in ids_por_cluster


@pytest.mark.acceptance
def test_ca03_negative_similar_but_different_opponents_do_not_cluster() -> None:
    """Ancoragem por entidade: 'Vasco vence Bahia' ≠ 'Vasco vence Santos'."""
    items = [
        _classified("1", "Vasco vence o Bahia", source="netvasco"),
        _classified("2", "Vasco vence o Santos", source="supervasco", minutes_after=30),
    ]
    clusters = cluster(items)
    ids = [sorted(a.article.external_id for a in c.items) for c in clusters]
    ids.sort()
    assert ids == [["1"], ["2"]]


def test_canonical_article_is_oldest_of_cluster() -> None:
    items = [
        _classified("newer", "Vasco vence o Bahia por 2 a 1", minutes_after=60),
        _classified("older", "Vasco vence Bahia 2-1", minutes_after=0),
    ]
    clusters = cluster(items)
    (only,) = clusters
    assert only.canonical.article.external_id == "older"


def test_clusters_do_not_cross_categories() -> None:
    """Mesmo texto, categorias diferentes — não agrupa."""
    items = [
        _classified("a", "Vasco vence o Bahia", category=Category.PROFISSIONAL),
        _classified("b", "Vasco vence o Bahia", category=Category.BASE_SUB20),
    ]
    clusters = cluster(items)
    assert len(clusters) == 2


def test_url_dedup_beats_titles() -> None:
    """Mesma URL canônica → um único cluster, sem apelar pra fuzzy match."""
    base = datetime(2026, 7, 27, 12, tzinfo=BRT)
    art = Article(
        id="h-same",
        source_id="netvasco",
        external_id="9",
        url="https://x/y/9",
        title="A",
        summary=None,
        body=None,
        published_at=base,
        fetched_at=base,
        content_hash="c-same",
        status=ArticleStatus.OK.value,
        run_id="r",
    )
    art2 = art.model_copy(update={"id": "h-same2", "title": "B"})
    items = [
        ClassifiedArticle(
            article=art,
            category=Category.PROFISSIONAL,
            confidence=1.0,
            method=None,
            llm_model=None,
            status="ok",
            motivo="",  # type: ignore[arg-type]
        ),
        ClassifiedArticle(
            article=art2,
            category=Category.PROFISSIONAL,
            confidence=1.0,
            method=None,
            llm_model=None,
            status="ok",
            motivo="",  # type: ignore[arg-type]
        ),
    ]
    clusters = cluster(items)
    assert len(clusters) == 1
    assert len(clusters[0].items) == 2
