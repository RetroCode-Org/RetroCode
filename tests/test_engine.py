"""Tests for ContextEngine (LLM calls mocked out)."""

import pytest
from unittest.mock import MagicMock, patch

from contextEngineering.engine import ContextEngine
from contextEngineering.trace_ingester import Conversation


MOCK_REFLECTION = {
    "insights": [
        {
            "category": "CODING_PATTERNS",
            "observation": "Assistant always reads files before editing.",
            "recommendation": "Always read a file before editing it.",
            "evidence": "Let me read the file first.",
        }
    ],
    "summary": "The assistant consistently reads files before modifying them.",
}

MOCK_CURATOR_RESULT = (
    "## CODING_PATTERNS\n[pat-00001] Always read a file before editing it.\n",
    2,
)


def make_conversations():
    return [
        Conversation(
            session_id="s1",
            timestamp="2026-03-01T10:00:00Z",
            messages=[
                {"role": "user", "content": "Fix the bug"},
                {"role": "assistant", "content": "Read file, fixed it."},
                {"role": "user", "content": "Add a test"},
                {"role": "assistant", "content": "Added test."},
            ],
        )
    ]


class TestContextEngine:
    @pytest.fixture
    def engine(self, tmp_path):
        return ContextEngine(playbook_path=str(tmp_path / "playbook.txt"))

    def test_run_calls_reflector_and_curator(self, engine):
        engine.reflector = MagicMock()
        engine.curator = MagicMock()
        engine.reflector.reflect.return_value = MOCK_REFLECTION
        engine.curator.curate.return_value = MOCK_CURATOR_RESULT

        result = engine.run(make_conversations())

        engine.reflector.reflect.assert_called_once()
        engine.curator.curate.assert_called_once()
        assert "[pat-00001]" in result

    def test_run_saves_playbook_to_file(self, engine, tmp_path):
        engine.reflector = MagicMock()
        engine.curator = MagicMock()
        engine.reflector.reflect.return_value = MOCK_REFLECTION
        engine.curator.curate.return_value = MOCK_CURATOR_RESULT

        engine.run(make_conversations())

        playbook_file = tmp_path / "playbook.txt"
        assert playbook_file.exists()
        assert "[pat-00001]" in playbook_file.read_text()

    def test_run_skips_curation_when_no_insights(self, engine):
        engine.reflector = MagicMock()
        engine.curator = MagicMock()
        engine.reflector.reflect.return_value = {"insights": [], "summary": "nothing"}

        engine.run(make_conversations())

        engine.curator.curate.assert_not_called()

    def test_run_passes_traces_as_dicts_to_reflector(self, engine):
        engine.reflector = MagicMock()
        engine.curator = MagicMock()
        engine.reflector.reflect.return_value = {"insights": [], "summary": ""}

        convs = make_conversations()
        engine.run(convs)

        call_args = engine.reflector.reflect.call_args[0]
        traces_arg = call_args[0]
        assert isinstance(traces_arg, list)
        assert traces_arg[0]["session_id"] == "s1"
        assert isinstance(traces_arg[0]["messages"], list)

    def test_run_returns_unchanged_playbook_when_no_insights(self, engine, tmp_path):
        initial = "## CODING_PATTERNS\n[pat-00001] Existing tip.\n"
        (tmp_path / "playbook.txt").write_text(initial)

        engine.reflector = MagicMock()
        engine.curator = MagicMock()
        engine.reflector.reflect.return_value = {"insights": [], "summary": ""}

        result = engine.run(make_conversations())
        assert result == initial
