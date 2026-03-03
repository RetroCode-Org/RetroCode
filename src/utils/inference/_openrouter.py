"""OpenRouter inference provider (supports many models via one API)."""

import logging
from typing import Optional

from .base import BaseProvider

logger = logging.getLogger(__name__)


class OpenRouterProvider(BaseProvider):
    """OpenRouter exposes an OpenAI-compatible API for many model providers."""

    BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "anthropic/claude-sonnet-4"

    def __init__(self, api_key: Optional[str] = None):
        self._client = None
        self._api_key = api_key

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=self.BASE_URL,
                api_key=self._api_key,
            )
        return self._client

    def complete(
        self,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content
