"""Registry de publishers — montado a partir da config (plan.md §6.7)."""

from __future__ import annotations

from vascobot.publishers.base import Publisher


class PublisherRegistry:
    def __init__(self) -> None:
        self._by_platform: dict[str, Publisher] = {}

    def register(self, pub: Publisher) -> None:
        if pub.platform in self._by_platform:
            raise ValueError(f"publisher '{pub.platform}' already registered")
        self._by_platform[pub.platform] = pub

    def enabled(self) -> list[Publisher]:
        """Só as plataformas com `enabled=True`. Pipeline itera sobre isso."""
        return [p for p in self._by_platform.values() if p.enabled]

    def platforms(self) -> list[str]:
        return list(self._by_platform)


__all__ = ["PublisherRegistry"]
