"""Abstract base class for LLM inference providers."""

import json
import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    """Common interface for all LLM inference providers."""

    @abstractmethod
    def complete(
        self,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Send a completion request and return the response text."""
        ...

    def call_with_retry(
        self,
        system: str,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
        retries: int,
    ) -> str:
        for attempt in range(retries):
            try:
                return self.complete(system, prompt, model, max_tokens, temperature)
            except Exception as e:
                logger.warning(f"[{self.__class__.__name__}] attempt {attempt + 1} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise


def parse_json_response(text: str) -> dict:
    """Extract and parse JSON from an LLM response, handling code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)
    return json.loads(cleaned)
