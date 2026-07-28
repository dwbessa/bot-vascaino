"""Publisher — plan.md §6.7."""

from __future__ import annotations

from abc import ABC, abstractmethod

from vascobot.models import PostDraft, PublishedPost


class PublishError(Exception):
    """Falha ao publicar — não pode derrubar outras plataformas."""


class Publisher(ABC):
    platform: str
    enabled: bool

    @abstractmethod
    async def publish_thread(self, drafts: list[PostDraft]) -> list[PublishedPost]:
        """Publica todos os drafts como thread. Retorna 1 PublishedPost por draft."""
