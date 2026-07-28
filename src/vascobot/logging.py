"""Log estruturado JSON com redação de segredos — RNF-04 / CA-08."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, TextIO

import structlog
from structlog.typing import EventDict, WrappedLogger

SECRET_KEY_PATTERN = re.compile(r"key|token|password|secret", re.IGNORECASE)
REDACTED = "***"


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (REDACTED if SECRET_KEY_PATTERN.search(k) else _redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_secrets(
    _logger: WrappedLogger | None,
    _name: str,
    event_dict: EventDict,
) -> EventDict:
    """Processor: apaga qualquer chave contendo key|token|password|secret, recursivo."""
    for key in list(event_dict.keys()):
        if SECRET_KEY_PATTERN.search(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    stream: TextIO | None = None,
    json: bool = True,
) -> None:
    """Configura structlog. `stream` só existe para testes; produção usa stderr."""
    out = stream or sys.stderr
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(stream=out, level=numeric_level, format="%(message)s")

    processors: list[structlog.typing.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
        redact_secrets,
    ]
    renderer: structlog.typing.Processor = (
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(colors=False)
    )
    processors.append(renderer)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=out),
        cache_logger_on_first_use=False,
    )
