"""Integração REAL contra Ollama Cloud. Só via `make integration`, nunca CI.

Requer OLLAMA_API_KEY e OLLAMA_HOST configurados.
Este teste custa uma chamada por execução (rápida, modelo pequeno).
"""

from __future__ import annotations

import asyncio
import os

import pytest

from vascobot.config import Settings
from vascobot.llm.ollama_cloud import OllamaCloudProvider
from vascobot.llm.schemas import Categoria, Classificacao


@pytest.mark.integration
def test_ollama_cloud_classifies_headline_live() -> None:
    if not os.getenv("OLLAMA_API_KEY"):
        pytest.skip("OLLAMA_API_KEY ausente — pulando integração")

    settings = Settings()
    provider = OllamaCloudProvider.from_settings(settings)

    prompt = (
        "Classifique a manchete numa das categorias: "
        "profissional, feminino, base_sub20, base_sub17, base_sub15, descartado.\n"
        "Manchete: 'Vasco vence o Bahia por 2 a 1 em São Januário'\n"
        "Devolva JSON com {categoria, confianca, motivo}."
    )

    out = asyncio.run(
        provider.structured(
            prompt=prompt,
            schema=Classificacao,
            model=settings.classify_model,
        ),
    )
    assert isinstance(out, Classificacao)
    # esperamos profissional, mas o teste real prova apenas o schema aderente
    assert out.categoria in set(Categoria)
    assert 0.0 <= out.confianca <= 1.0
