"""Configuração global do pytest.

Restaura os defaults do structlog entre testes. Sem isso, um teste que chame
`configure_logging(stream=io.StringIO(), ...)` deixa o `PrintLoggerFactory`
apontando pra um stream fechado, e o próximo teste que logar explode.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
import structlog


@pytest.fixture(autouse=True)
def _reset_structlog_between_tests() -> Generator[None, None, None]:
    yield
    structlog.reset_defaults()
