"""CommonStack inference provider."""

import logging
import os
from typing import Optional

import requests

from .base import BaseProvider

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = "https://api.commonstack.ai/v1/chat/completions"


def _with_provider_prefix(model: str) -> str:
    """CommonStack routes by provider; bare IDs like gpt-5.2 need openai/ prefix."""
    if "/" in model:
        return model
    if model.startswith("gpt-"):
        return f"openai/{model}"
    if "claude" in model.lower():
        return f"anthropic/{model}"
    return model


class CommonStackProvider(BaseProvider):
    DEFAULT_MODEL = "openai/gpt-5.2"

    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        self._api_key = api_key or os.environ.get("COMMONSTACK_API_KEY", "")
        self._api_url = api_url or os.environ.get("COMMONSTACK_API_URL", _DEFAULT_API_URL)

    def complete(
        self,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        model = _with_provider_prefix(model)
        response = requests.post(
            self._api_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        if not response.ok:
            try:
                err_body = response.json()
            except Exception:
                err_body = response.text
            logger.error(
                "CommonStack %s: url=%s model=%s body=%s",
                response.status_code,
                self._api_url,
                model,
                err_body,
            )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
