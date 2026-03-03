"""OpenAI inference provider."""

import logging
from typing import Optional

from .base import BaseProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseProvider):
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, api_key: Optional[str] = None):
        self._client = None
        self._api_key = api_key

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key) if self._api_key else OpenAI()
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
            max_completion_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content
