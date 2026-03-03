"""Tests for the inference package (provider selection, JSON parsing, retry)."""

import os
import pytest
from unittest.mock import MagicMock, patch

from utils.inference import (
    get_provider,
    call_llm,
    call_llm_json,
    parse_json_response,
    AnthropicProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from utils.inference.base import BaseProvider


class TestGetProvider:
    def test_default_is_anthropic(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_PROVIDER", None)
            p = get_provider()
        assert isinstance(p, AnthropicProvider)

    def test_explicit_anthropic(self):
        assert isinstance(get_provider("anthropic"), AnthropicProvider)

    def test_explicit_openai(self):
        assert isinstance(get_provider("openai"), OpenAIProvider)

    def test_explicit_openrouter(self):
        assert isinstance(get_provider("openrouter"), OpenRouterProvider)

    def test_env_var_selects_provider(self):
        with patch.dict(os.environ, {"LLM_PROVIDER": "openai"}):
            p = get_provider()
        assert isinstance(p, OpenAIProvider)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider("badprovider")

    def test_api_key_passed_to_provider(self):
        p = get_provider("anthropic", api_key="test-key")
        assert p._api_key == "test-key"


class TestParseJsonResponse:
    def test_plain_json(self):
        result = parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_fence(self):
        result = parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_json_in_plain_fence(self):
        result = parse_json_response('```\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_whitespace_stripped(self):
        result = parse_json_response('  \n{"key": "value"}\n  ')
        assert result == {"key": "value"}

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            parse_json_response("not json")

    def test_nested_json(self):
        raw = '```json\n{"operations": [{"type": "ADD", "section": "X", "content": "y"}]}\n```'
        result = parse_json_response(raw)
        assert result["operations"][0]["type"] == "ADD"


class TestCallLlm:
    def _make_provider(self, return_value="hello"):
        mock = MagicMock(spec=BaseProvider)
        mock.DEFAULT_MODEL = "mock-model"
        mock.call_with_retry.return_value = return_value
        return mock

    def test_uses_provided_provider(self):
        p = self._make_provider("response text")
        result = call_llm("sys", "prompt", provider=p)
        assert result == "response text"
        p.call_with_retry.assert_called_once()

    def test_passes_model_to_provider(self):
        p = self._make_provider()
        call_llm("sys", "prompt", model="my-model", provider=p)
        args = p.call_with_retry.call_args[0]
        assert "my-model" in args

    def test_uses_provider_default_model_when_none(self):
        p = self._make_provider()
        call_llm("sys", "prompt", provider=p)
        args = p.call_with_retry.call_args[0]
        assert "mock-model" in args

    def test_passes_max_tokens_and_temperature(self):
        p = self._make_provider()
        call_llm("sys", "prompt", max_tokens=512, temperature=0.5, provider=p)
        args = p.call_with_retry.call_args[0]
        assert 512 in args
        assert 0.5 in args


class TestCallLlmJson:
    def test_returns_parsed_dict(self):
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.DEFAULT_MODEL = "mock-model"
        mock_provider.call_with_retry.return_value = '{"result": 42}'
        result = call_llm_json("sys", "prompt", provider=mock_provider)
        assert result == {"result": 42}

    def test_handles_fenced_json(self):
        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.DEFAULT_MODEL = "mock-model"
        mock_provider.call_with_retry.return_value = '```json\n{"ok": true}\n```'
        result = call_llm_json("sys", "prompt", provider=mock_provider)
        assert result == {"ok": True}


class TestRetryLogic:
    def test_retries_on_failure_then_succeeds(self):
        provider = MagicMock(spec=BaseProvider)
        provider.DEFAULT_MODEL = "mock-model"
        # Fail twice, succeed on third attempt
        provider.complete.side_effect = [
            RuntimeError("timeout"),
            RuntimeError("timeout"),
            "success",
        ]

        # Use real call_with_retry from base
        from utils.inference.base import BaseProvider as RealBase
        real_provider = MagicMock(spec=RealBase)
        real_provider.DEFAULT_MODEL = "mock-model"
        real_provider.complete.side_effect = [
            RuntimeError("timeout"),
            RuntimeError("timeout"),
            "success",
        ]
        real_provider.call_with_retry = RealBase.call_with_retry.__get__(real_provider)

        with patch("time.sleep"):  # skip actual sleep
            result = real_provider.call_with_retry("sys", "prompt", "model", 100, 0.0, 3)
        assert result == "success"
        assert real_provider.complete.call_count == 3

    def test_raises_after_all_retries_exhausted(self):
        from utils.inference.base import BaseProvider as RealBase
        real_provider = MagicMock(spec=RealBase)
        real_provider.complete.side_effect = RuntimeError("always fails")
        real_provider.call_with_retry = RealBase.call_with_retry.__get__(real_provider)

        with patch("time.sleep"):
            with pytest.raises(RuntimeError, match="always fails"):
                real_provider.call_with_retry("sys", "prompt", "model", 100, 0.0, 3)
        assert real_provider.complete.call_count == 3
