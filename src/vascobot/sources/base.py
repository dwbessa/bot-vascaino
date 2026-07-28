"""Interface e utilidades para adapters de fontes de notícia."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import httpx

from vascobot.models import RawArticle, Watermark


class RateLimiter:
    """Rate limiter por chave (host). Espaço mínimo entre chamadas = 1/rps."""

    def __init__(self, rps: float) -> None:
        if rps <= 0:
            raise ValueError("rps must be positive")
        self._min_interval = 1.0 / rps
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def acquire(self, key: str) -> None:
        async with self._lock(key):
            loop = asyncio.get_running_loop()
            now = loop.time()
            last = self._last.get(key, 0.0)
            wait = self._min_interval - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[key] = loop.time()


class SourceAdapter(ABC):
    """Contrato de um coletor de fonte. Cada implementação declara os atributos de classe."""

    source_id: str
    base_url: str
    rate_limit_rps: float = 0.5

    @abstractmethod
    async def discover(self, since: Watermark) -> list[RawArticle]:
        """Lista artigos publicados após o watermark, mais novos primeiro."""

    async def hydrate(self, raw: RawArticle) -> RawArticle:
        """Complementa o RawArticle (default: passthrough — hidratação real fica no pipeline)."""
        return raw


def host_of(url: str) -> str:
    return urlparse(url).hostname or ""


_HTTP_TOO_MANY = 429
_HTTP_SERVER_ERROR = 500


async def request_with_limits(
    client: httpx.AsyncClient,
    url: str,
    limiter: RateLimiter,
    *,
    method: str = "GET",
    retries: int = 2,
    backoff: float = 0.5,
) -> httpx.Response:
    """GET com rate limit e retry em 429/5xx. Levanta a última exceção."""
    key = host_of(url)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        await limiter.acquire(key)
        try:
            resp = await client.request(method, url)
            if resp.status_code >= _HTTP_SERVER_ERROR or resp.status_code == _HTTP_TOO_MANY:
                raise httpx.HTTPStatusError(
                    f"status={resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            await asyncio.sleep(backoff * (2**attempt))
        else:
            return resp
    assert last_exc is not None
    raise last_exc


class SourceError(Exception):
    """Falha isolada de fonte — o pipeline segue com as outras."""
