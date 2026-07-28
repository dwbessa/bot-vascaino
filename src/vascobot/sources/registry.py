"""Registry de fontes. Config decide quem está ativo."""

from __future__ import annotations

from collections.abc import Iterable

from vascobot.sources.base import SourceAdapter


class SourceRegistry:
    def __init__(self) -> None:
        self._by_id: dict[str, SourceAdapter] = {}

    def register(self, adapter: SourceAdapter) -> None:
        if adapter.source_id in self._by_id:
            raise ValueError(f"source '{adapter.source_id}' already registered")
        self._by_id[adapter.source_id] = adapter

    def get(self, source_id: str) -> SourceAdapter:
        return self._by_id[source_id]

    def ids(self) -> list[str]:
        return list(self._by_id)

    def enabled(self, ids: Iterable[str]) -> list[SourceAdapter]:
        wanted = set(ids)
        return [a for sid, a in self._by_id.items() if sid in wanted]
