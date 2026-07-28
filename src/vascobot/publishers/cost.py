"""Cálculo de custo do X — research.md §3.

Fev/2026 — tier gratuito descontinuado. Preço por post depende de ter URL.
Números são estimativa; reconferir na doc oficial antes de fechar orçamento.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vascobot.models import PostDraft, PublishedPost

COST_POST_WITH_LINK_USD = 0.20
COST_POST_WITHOUT_LINK_USD = 0.015


@dataclass
class CostSummary:
    """Contabiliza gastos por post/thread e projeta o mês."""

    posts_with_link: int = 0
    posts_without_link: int = 0
    total_usd: float = 0.0
    per_platform: dict[str, float] = field(default_factory=dict)

    def add(self, platform: str, has_link: bool) -> None:
        cost = COST_POST_WITH_LINK_USD if has_link else COST_POST_WITHOUT_LINK_USD
        if platform == "x":
            if has_link:
                self.posts_with_link += 1
            else:
                self.posts_without_link += 1
            self.total_usd += cost
        # Bluesky é grátis — nunca soma total, mas registra no per_platform como 0
        self.per_platform[platform] = self.per_platform.get(platform, 0.0) + (
            cost if platform == "x" else 0.0
        )


def cost_of_post(*, has_link: bool) -> float:
    """Custo de um post do X isolado."""
    return COST_POST_WITH_LINK_USD if has_link else COST_POST_WITHOUT_LINK_USD


def cost_of_thread(drafts: list[PostDraft]) -> float:
    """Custo previsto do lote — só posts do X contam."""
    total = 0.0
    for d in drafts:
        if d.platform.value != "x":
            continue
        total += cost_of_post(has_link=d.has_link)
    return round(total, 4)


def cost_of_published(posts: list[PublishedPost]) -> float:
    """Custo já executado — soma `cost_usd` gravado no PublishedPost."""
    return round(sum(p.cost_usd for p in posts), 4)


def project_month(spent_this_month_usd: float, day_of_month: int) -> float:
    """Projeção linear simples: gasto x dias_do_mês / dia_atual.

    Não usa dias-do-mês reais para não amarrar em `calendar` — 30 é bom o
    suficiente pra alerta preventivo.
    """
    if day_of_month <= 0:
        return spent_this_month_usd
    days_in_month = 30
    return round(spent_this_month_usd * days_in_month / day_of_month, 2)


__all__ = [
    "COST_POST_WITHOUT_LINK_USD",
    "COST_POST_WITH_LINK_USD",
    "CostSummary",
    "cost_of_post",
    "cost_of_published",
    "cost_of_thread",
    "project_month",
]
