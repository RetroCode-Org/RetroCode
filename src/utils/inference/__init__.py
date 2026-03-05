"""Inference package: provider-agnostic LLM calls.

Usage:
    # Use env var LLM_PROVIDER (anthropic | openai | openrouter), default: anthropic
    from src.utils.inference import call_llm, call_llm_json

    # Or select a provider explicitly:
    from src.utils.inference import get_provider, call_llm
    provider = get_provider("openai", api_key="sk-...")
    result = call_llm(system, prompt, model="gpt-4o", provider=provider)
"""

import os
import logging
from typing import Optional

from .base import BaseProvider, parse_json_response
from ._anthropic import AnthropicProvider
from ._openai import OpenAIProvider
from ._openrouter import OpenRouterProvider
from ._commonstack import CommonStackProvider
from ._gemini import GeminiProvider

logger = logging.getLogger(__name__)

_PROVIDERS = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "openrouter": OpenRouterProvider,
    "commonstack": CommonStackProvider,
    "gemini": GeminiProvider,
}

_default_provider: Optional[BaseProvider] = None


def get_provider(name: Optional[str] = None, api_key: Optional[str] = None) -> BaseProvider:
    """Instantiate a provider by name.

    Args:
        name: One of 'anthropic', 'openai', 'openrouter', 'gemini', 'commonstack'.
              Falls back to LLM_PROVIDER env var, then 'commonstack'.
        api_key: Optional API key override (otherwise reads from env).
    """
    name = name or os.environ.get("LLM_PROVIDER", "commonstack")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider '{name}'. Choose from: {list(_PROVIDERS)}")
    return cls(api_key=api_key)


def _get_default_provider() -> BaseProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = get_provider()
    return _default_provider


def call_llm(
    system: str,
    prompt: str,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    retries: int = 3,
    provider: Optional[BaseProvider] = None,
) -> str:
    """Call an LLM with retry logic.

    Uses the default provider (set via LLM_PROVIDER env var) unless
    a provider instance is passed explicitly.

    Args:
        system: System prompt.
        prompt: User prompt.
        model: Model ID. Defaults to the provider's DEFAULT_MODEL.
        max_tokens: Maximum tokens in the response.
        temperature: Sampling temperature.
        retries: Number of retries on failure.
        provider: Explicit provider instance (overrides default).
    """
    p = provider or _get_default_provider()
    model = model or p.DEFAULT_MODEL
    return p.call_with_retry(system, prompt, model, max_tokens, temperature, retries)


def call_llm_json(
    system: str,
    prompt: str,
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    provider: Optional[BaseProvider] = None,
) -> dict:
    """Call an LLM and parse the response as JSON."""
    raw = call_llm(system, prompt, model, max_tokens, temperature, provider=provider)
    return parse_json_response(raw)


__all__ = [
    "call_llm",
    "call_llm_json",
    "get_provider",
    "parse_json_response",
    "BaseProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "OpenRouterProvider",
    "GeminiProvider",
]
