"""RF-13 — priorização determinística de clusters (plan.md §6.5).

| Peso | Tipo |
|---|---|
| 1 | Jogo, resultado, escalação, lesão, suspensão |
| 2 | Mercado (chegada/saída confirmada), comissão técnica |
| 3 | Mercado especulado |
| 4 | Institucional (SAF, CEO, investidor, eleição, patrocínio, estádio) |

Menor peso = maior prioridade. Empate → mais recente primeiro.
Sem LLM, sem I/O — só regex sobre título do canônico.
"""

from __future__ import annotations

import re
import unicodedata

from vascobot.pipeline.dedupe import Cluster

# Ordem importa: um mesmo título pode bater várias listas — a primeira que casar vence.
_PATTERNS: list[tuple[int, re.Pattern[str]]] = [
    (
        1,
        re.compile(
            r"\b(vence|venceu|derrota|derrotou|bate|bateu|empata|empatou|"
            r"perde|perdeu|goleia|goleou|escalacao|jogo|amistoso|"
            r"lesao|lesionad[oa]|suspenso|suspensao|expulso|cartao\s+vermelho|"
            r"pelo\s+brasileirao|classico|pelo\s+carioca)\b",
        ),
    ),
    (
        2,
        re.compile(
            r"\b(oficializa|oficializou|anuncia|anunciou\s+reforc[oa]|contratacao|"
            r"assina|assinou|renovacao|renova(?!\s+contrato\s+com\s+patrocin)|"
            r"comissao\s+tecnica|auxiliar|preparador|novo\s+tecnico|"
            r"acordo\s+com\s+jogador|apresent(a|ou)\s+refor[cç]o)\b",
        ),
    ),
    (
        3,
        re.compile(
            r"\b(oferecid[oa]|especulad[oa]|negocia|negociacao|"
            r"alvo|interesse|sondagem|pode\s+contratar|pode\s+chegar|"
            r"na\s+mira|em\s+conversas|de\s+olho\s+em)\b",
        ),
    ),
    (
        4,
        re.compile(
            r"\b(saf|ceo|investidor|eleicao|presidencial|presidente(?!\s+da\s+cbf)|"
            r"patrocin(io|ador)|master|estadio|sao\s+januario\s+projeto|"
            r"socio(-)?torcedor|diretoria|assembleia|balanco|receita|"
            r"chapa|naming\s+rights|marketing)\b",
        ),
    ),
]


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def cluster_weight(cluster: Cluster) -> int:
    """Devolve o menor peso encontrado no título canônico. Default = 4."""
    text = _normalize(cluster.canonical.article.title)
    for weight, pattern in _PATTERNS:
        if pattern.search(text):
            return weight
    return 4


def rank_clusters(clusters: list[Cluster]) -> list[Cluster]:
    """Ordena por (peso asc, published_at desc). Determinístico, sem LLM."""
    return sorted(
        clusters,
        key=lambda c: (cluster_weight(c), -c.canonical.article.published_at.timestamp()),
    )


__all__ = ["cluster_weight", "rank_clusters"]
