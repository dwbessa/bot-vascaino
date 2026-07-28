"""Empacotamento de threads — menos posts (economia no X)."""

from __future__ import annotations

from vascobot.config import XLinkPolicy
from vascobot.models import Category, Digest, Platform
from vascobot.pipeline.compose import (
    _pack,
    compose_thread,
    fits_bluesky,
    fits_x,
)


def _digest(headline: str, bullets: list[str], urls: list[str]) -> Digest:
    return Digest(
        id="d1",
        run_id="r1",
        category=Category.PROFISSIONAL,
        headline=headline,
        bullets=bullets,
        source_urls=urls,
        llm_model="fake",
    )


def test_two_bullets_thread_packs_to_two_posts_not_four() -> None:
    """Cenário real: raiz + 2 bullets + fontes cabia em 2 posts, não 4."""
    d = _digest(
        headline="Vasco avança por Sosa e 777 contesta SAF",
        bullets=[
            "Segundo Tomas Davila, Vasco está perto de acordo com o Racing por Sosa.",
            "777 Carioca contesta argumentos do Vasco na recuperação judicial.",
        ],
        urls=["https://netvasco.com.br/n/1/sosa", "https://supervasco.com/noticias/saf-2.html"],
    )
    drafts = compose_thread(d, platform=Platform.BLUESKY, run_id="r1")
    assert len(drafts) <= 2
    for dd in drafts:
        assert fits_bluesky(dd.text)


def test_zero_bullets_thread_packs_to_one_post() -> None:
    """Digest só com headline + 1 fonte cabe num único post."""
    d = _digest(
        headline="Pedro Emanuel observa atleta do Sub-20 durante treino",
        bullets=[],
        urls=["https://supervasco.com/noticias/sub-20-451834.html"],
    )
    drafts = compose_thread(d, platform=Platform.BLUESKY, run_id="r1")
    assert len(drafts) == 1
    assert fits_bluesky(drafts[0].text)


def test_packing_never_exceeds_bluesky_limit() -> None:
    d = _digest(
        headline="H" * 70,
        bullets=["x" * 140, "y" * 140],
        urls=["https://x/y/" + "a" * 60],
    )
    drafts = compose_thread(d, platform=Platform.BLUESKY, run_id="r1")
    assert all(fits_bluesky(dd.text) for dd in drafts)


def test_packing_never_exceeds_x_free_limit() -> None:
    d = _digest(
        headline="Vasco vence e mantém invencibilidade em casa",
        bullets=["Payet marcou dois gols nos acréscimos do segundo tempo do jogo."],
        urls=["https://netvasco.com.br/n/1/jogo"],
    )
    drafts = compose_thread(
        d,
        platform=Platform.X,
        run_id="r1",
        x_is_premium=False,
        x_link_policy=XLinkPolicy.LAST_POST,
    )
    assert all(fits_x(dd.text, is_premium=False) for dd in drafts)


def test_source_urls_capped_to_three() -> None:
    """Muitas URLs não incham a thread — no máximo 3 aparecem."""
    d = _digest(
        headline="Resumo",
        bullets=[],
        urls=[f"https://netvasco.com.br/n/{i}/x" for i in range(20)],
    )
    drafts = compose_thread(d, platform=Platform.BLUESKY, run_id="r1")
    joined = "\n".join(dd.text for dd in drafts)
    assert joined.count("https://") <= 3


def test_x_none_policy_packs_without_link() -> None:
    d = _digest(
        headline="Vasco vence",
        bullets=["Payet decidiu."],
        urls=["https://netvasco.com.br/n/1/x"],
    )
    drafts = compose_thread(
        d,
        platform=Platform.X,
        run_id="r1",
        x_link_policy=XLinkPolicy.NONE,
    )
    assert not any(dd.has_link for dd in drafts)
    assert all("http" not in dd.text for dd in drafts)


def test_pack_empty_blocks_returns_empty() -> None:
    assert _pack([], fits_bluesky) == []


def test_pack_skips_empty_text_blocks() -> None:
    blocks = [("", False), ("real", True), ("", False)]
    packed = _pack(blocks, fits_bluesky)
    assert packed == [("real", True)]


def test_compose_ignores_empty_bullet() -> None:
    d = _digest(headline="Vasco vence", bullets=["", "Payet marcou."], urls=[])
    drafts = compose_thread(d, platform=Platform.BLUESKY, run_id="r1")
    joined = "\n".join(dd.text for dd in drafts)
    assert "Payet marcou." in joined


def test_packed_posts_keep_sequential_indices() -> None:
    d = _digest(
        headline="H" * 70,
        bullets=["x" * 140, "y" * 140, "z" * 140],
        urls=["https://x/y/1"],
    )
    drafts = compose_thread(d, platform=Platform.BLUESKY, run_id="r1")
    assert [dd.thread_index for dd in drafts] == list(range(len(drafts)))
