"""RF-13 — priorização determinística por palavra-chave (T-019b).

Pesos: 1 = jogo/elenco/lesão/suspensão, 2 = mercado confirmado/comissão,
3 = mercado especulado, 4 = institucional.
Empate → mais recente primeiro.
Peso 4 nunca desloca peso 1.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from vascobot.models import Article, ArticleStatus, Category
from vascobot.pipeline.classify_pipeline import ClassifiedArticle
from vascobot.pipeline.dedupe import Cluster
from vascobot.pipeline.priority import cluster_weight, rank_clusters

BRT = ZoneInfo("America/Sao_Paulo")


def _cluster(
    headline: str, minutes_after: int = 0, category: Category = Category.PROFISSIONAL
) -> Cluster:
    base = datetime(2026, 7, 27, 12, tzinfo=BRT)
    art = Article(
        id=f"h-{headline[:10]}",
        source_id="netvasco",
        external_id="1",
        url=f"https://x/y/{headline[:5]}",
        title=headline,
        summary=None,
        body=None,
        published_at=base + timedelta(minutes=minutes_after),
        fetched_at=base + timedelta(minutes=minutes_after),
        content_hash="h",
        status=ArticleStatus.OK.value,
        run_id="r",
    )
    ca = ClassifiedArticle(
        article=art,
        category=category,
        confidence=0.9,
        method=None,  # type: ignore[arg-type]
        llm_model=None,
        status=ArticleStatus.OK.value,
        motivo="",
    )
    return Cluster(canonical=ca, items=[ca])


# ------------------------------------------------------------------ pesos base
def test_weight_1_jogo() -> None:
    assert cluster_weight(_cluster("Vasco vence o Bahia por 2 a 1")) == 1


def test_weight_1_lesao() -> None:
    assert cluster_weight(_cluster("Vegetti tem lesão muscular confirmada")) == 1


def test_weight_1_suspensao() -> None:
    assert cluster_weight(_cluster("Volante do Vasco é suspenso por 3º amarelo")) == 1


def test_weight_1_escalacao() -> None:
    assert cluster_weight(_cluster("Escalação: Vasco vai com Vegetti no comando")) == 1


def test_weight_2_mercado_confirmado() -> None:
    assert cluster_weight(_cluster("Vasco oficializa a contratação do zagueiro Cuesta")) == 2


def test_weight_2_comissao() -> None:
    assert cluster_weight(_cluster("Comissão técnica avalia poupar titulares")) == 2


def test_weight_3_mercado_especulado() -> None:
    assert cluster_weight(_cluster("Meia Boschilia é oferecido ao Vasco")) == 3


def test_weight_3_negocia_verbo_especulado() -> None:
    assert cluster_weight(_cluster("Vasco negocia rescisão amigável com atacante")) == 3


def test_weight_4_institucional_saf() -> None:
    assert cluster_weight(_cluster("SAF do Vasco aprova balanço com receita recorde")) == 4


def test_weight_4_institucional_patrocinio() -> None:
    assert (
        cluster_weight(_cluster("Vasco fecha novo patrocínio máster com marca de energéticos")) == 4
    )


def test_weight_4_institucional_eleicao() -> None:
    assert (
        cluster_weight(_cluster("Chapa oposicionista lança pré-candidato à presidência do Vasco"))
        == 4
    )


def test_weight_defaults_to_4_when_no_pattern_matches() -> None:
    """Sem palavra-chave conhecida → peso 4 (institucional/genérico), nunca crasha."""
    assert cluster_weight(_cluster("Torcedores fazem visita à sede histórica")) == 4


# ------------------------------------------------------------------ ordenação
def test_rank_puts_jogo_before_institucional_regardless_of_time() -> None:
    """Peso 1 sempre bate peso 4, mesmo mais antigo."""
    old_game = _cluster("Vasco vence o Bahia por 2 a 1", minutes_after=0)
    fresh_inst = _cluster("SAF anuncia balanço com receita recorde", minutes_after=300)
    ranked = rank_clusters([fresh_inst, old_game])
    assert ranked[0] is old_game
    assert ranked[1] is fresh_inst


def test_rank_breaks_ties_by_recency() -> None:
    a = _cluster("Vasco vence o Bahia", minutes_after=0)
    b = _cluster("Vasco derrota o Santos", minutes_after=60)
    ranked = rank_clusters([a, b])
    assert ranked[0] is b


def test_rank_never_lets_p4_bump_p1_out_of_top_2() -> None:
    """DoD do T-019b: com 5 institucionais + 1 jogo, o jogo entra."""
    institucionais = [_cluster(f"SAF assunto {i}", minutes_after=i * 10) for i in range(5)]
    jogo = _cluster("Vasco vence o Bahia por 2 a 1", minutes_after=0)
    ranked = rank_clusters([*institucionais, jogo])
    top2 = ranked[:2]
    assert jogo in top2


def test_rank_stable_for_same_weight_same_time() -> None:
    a = _cluster("Vasco vence o Bahia", minutes_after=0)
    b = _cluster("Vasco vence o Fla", minutes_after=0)
    ranked = rank_clusters([a, b])
    assert len(ranked) == 2
    ids = {id(x) for x in ranked}
    assert ids == {id(a), id(b)}


def test_rank_no_llm_call_required() -> None:
    """Compromisso do RF-13: peso é regra auditável, nunca chama LLM."""
    import inspect

    from vascobot.pipeline import priority

    src = inspect.getsource(priority)
    assert "provider" not in src.lower()
    assert "await" not in src.lower()
    assert "async " not in src.lower()
