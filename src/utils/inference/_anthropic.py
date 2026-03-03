"""Anthropic (Claude) inference provider."""

import logging
from typing import Optional

from anthropic import Anthropic

from .base import BaseProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(BaseProvider):
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key: Optional[str] = None):
        self._client: Optional[Anthropic] = None
        self._api_key = api_key

    @property
    def client(self) -> Anthropic:
        if self._client is None:
            self._client = Anthropic(api_key=self._api_key) if self._api_key else Anthropic()
        return self._client

    def complete(
        self,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
