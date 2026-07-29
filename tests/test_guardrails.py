"""Guardrails pós-LLM — T-021."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from vascobot.llm.schemas import ResumoCategoria
from vascobot.models import Article, ArticleStatus, Category
from vascobot.pipeline.classify_pipeline import ClassifiedArticle
from vascobot.pipeline.dedupe import Cluster
from vascobot.pipeline.guardrails import (
    GuardrailResult,
    check_summary,
    literal_overlap_ok,
    proper_nouns_grounded,
)

BRT = ZoneInfo("America/Sao_Paulo")


def _cluster_with_body(title: str, body: str) -> Cluster:
    now = datetime(2026, 7, 27, 12, tzinfo=BRT)
    art = Article(
        id="h1",
        source_id="s",
        external_id="1",
        url="https://x/1",
        title=title,
        summary=None,
        body=body,
        published_at=now,
        fetched_at=now,
        content_hash="h",
        status=ArticleStatus.OK.value,
        run_id="r",
    )
    ca = ClassifiedArticle(
        article=art,
        category=Category.PROFISSIONAL,
        confidence=0.9,
        method=None,
        llm_model=None,
        status=ArticleStatus.OK.value,
        motivo="",  # type: ignore[arg-type]
    )
    return Cluster(canonical=ca, items=[ca])


# ------------------------------------------------------------ overlap literal
def test_literal_overlap_rejects_10_word_copy() -> None:
    source = "O Vasco vence o Bahia por 2 a 1 em São Januário nesta noite fria"
    bullet = "O Vasco vence o Bahia por 2 a 1 em São Januário confirmou o clube"
    assert literal_overlap_ok(bullet, [source]) is False


def test_literal_overlap_accepts_shorter_copies() -> None:
    source = "O Vasco vence o Bahia por 2 a 1"
    bullet = "Vasco venceu o Bahia com dois gols de Payet"
    assert literal_overlap_ok(bullet, [source]) is True


def test_literal_overlap_accent_case_normalized() -> None:
    source = "vasco vence o bahia por 2 a 1 em sao januario nesta noite fria"
    bullet = "Vasco vence o Bahia por 2 a 1 em São Januário nesta noite fria"
    assert literal_overlap_ok(bullet, [source]) is False


# ------------------------------------------------------------ nomes próprios
def test_proper_noun_present_in_cluster_passes() -> None:
    cluster = _cluster_with_body(
        "Vasco vence o Bahia por 2 a 1",
        "Payet marcou os dois gols nos acréscimos",
    )
    assert proper_nouns_grounded("Payet decidiu", [cluster]) is True


def test_proper_noun_absent_from_cluster_fails() -> None:
    cluster = _cluster_with_body(
        "Vasco vence o Bahia por 2 a 1",
        "Payet marcou os dois gols nos acréscimos",
    )
    # Vegetti não aparece em lugar nenhum do cluster → rejeitar
    assert proper_nouns_grounded("Vegetti fez os dois", [cluster]) is False


def test_common_stopword_capitalized_ignored() -> None:
    """Palavra comum que aparece no início de frase não deve virar 'nome'."""
    cluster = _cluster_with_body("Vasco vence", "corpo")
    assert proper_nouns_grounded("Vasco vence e o time comemora", [cluster]) is True


# ------------------------------------------------------------ tamanho
def test_long_content_is_not_rejected_by_guardrail() -> None:
    """Tamanho não derruba mais o resumo — o compose trunca por plataforma (CA-04).

    Um headline/bullet uns chars acima do estilo não pode custar a categoria.
    """
    result = check_summary(
        ResumoCategoria(headline="x" * 120, bullets=["a" * 200]),
        source_bodies=["corpo"],
        clusters=[_cluster_with_body("t", "corpo")],
    )
    assert result.passed


# ------------------------------------------------------------ integração
def test_check_summary_all_ok() -> None:
    cluster = _cluster_with_body(
        "Vasco vence o Bahia por 2 a 1",
        "Payet marcou os dois gols nos acréscimos e Léo Jardim defendeu pênalti",
    )
    summary = ResumoCategoria(
        headline="Vasco bate o Bahia; Payet decide",
        bullets=[
            "Payet fez os dois gols do Cruzmaltino",
            "Léo Jardim defendeu pênalti nos acréscimos",
        ],
    )
    result: GuardrailResult = check_summary(
        summary,
        source_bodies=[cluster.canonical.article.body or ""],
        clusters=[cluster],
    )
    assert result.passed
    assert result.reason == ""


def test_check_summary_rejects_hallucinated_player() -> None:
    cluster = _cluster_with_body(
        "Vasco vence o Bahia",
        "Payet marcou os dois",
    )
    summary = ResumoCategoria(
        headline="Vasco vence",
        bullets=["Vegetti brilhou", "Payet passou bola"],
    )
    result = check_summary(
        summary,
        source_bodies=[cluster.canonical.article.body or ""],
        clusters=[cluster],
    )
    assert not result.passed
    assert "vegetti" in result.reason.lower()
