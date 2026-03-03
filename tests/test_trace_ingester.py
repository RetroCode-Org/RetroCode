"""Tests for TraceIngester and related data classes."""

import json
import pytest

from contextEngineering.trace_ingester import (
    Conversation,
    TraceIngester,
    TraceState,
    TRACE_STATE_FILE,
)


class TestConversation:
    def test_rounds_counts_user_messages(self):
        conv = Conversation(
            session_id="s1",
            timestamp="",
            messages=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "how are you?"},
                {"role": "assistant", "content": "good"},
            ],
        )
        assert conv.rounds == 2

    def test_rounds_empty_messages(self):
        conv = Conversation(session_id="s1", timestamp="", messages=[])
        assert conv.rounds == 0

    def test_rounds_only_assistant(self):
        conv = Conversation(
            session_id="s1",
            timestamp="",
            messages=[{"role": "assistant", "content": "hello"}],
        )
        assert conv.rounds == 0


class TestTraceState:
    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / TRACE_STATE_FILE)
        state = TraceState(
            processed_session_ids=["a", "b"],
            last_run_timestamp="2026-03-01T00:00:00Z",
        )
        state.save(path)

        loaded = TraceState.load(path)
        assert loaded.processed_session_ids == ["a", "b"]
        assert loaded.last_run_timestamp == "2026-03-01T00:00:00Z"

    def test_load_missing_file_returns_empty(self, tmp_path):
        state = TraceState.load(str(tmp_path / "nonexistent.json"))
        assert state.processed_session_ids == []
        assert state.last_run_timestamp is None


class TestTraceIngester:
    def test_ingest_reads_all_json_files(self, traces_dir, state_dir):
        ingester = TraceIngester(str(traces_dir), str(state_dir))
        convs = ingester.ingest()
        assert len(convs) == 2
        ids = {c.session_id for c in convs}
        assert ids == {"session_001", "session_002"}

    def test_ingest_missing_dir_returns_empty(self, tmp_path, state_dir):
        ingester = TraceIngester(str(tmp_path / "no_such_dir"), str(state_dir))
        assert ingester.ingest() == []

    def test_ingest_skips_malformed_json(self, tmp_path, state_dir):
        (tmp_path / "bad.json").write_text("not json {{{")
        (tmp_path / "good.json").write_text(json.dumps({
            "session_id": "good",
            "timestamp": "",
            "messages": [{"role": "user", "content": "hi"}],
        }))
        ingester = TraceIngester(str(tmp_path), str(state_dir))
        convs = ingester.ingest()
        assert len(convs) == 1
        assert convs[0].session_id == "good"

    def test_ingest_uses_filename_stem_when_no_session_id(self, tmp_path, state_dir):
        (tmp_path / "my_session.json").write_text(json.dumps({
            "timestamp": "",
            "messages": [],
        }))
        ingester = TraceIngester(str(tmp_path), str(state_dir))
        convs = ingester.ingest()
        assert convs[0].session_id == "my_session"

    def test_get_new_conversations_excludes_processed(self, traces_dir, state_dir):
        ingester = TraceIngester(str(traces_dir), str(state_dir))
        convs = ingester.ingest()
        ingester.mark_processed([convs[0]], "2026-03-01T00:00:00Z")

        ingester2 = TraceIngester(str(traces_dir), str(state_dir))
        convs2 = ingester2.ingest()
        new = ingester2.get_new_conversations(convs2)
        assert len(new) == 1
        assert new[0].session_id == "session_002"

    def test_get_new_conversations_all_new_when_no_state(self, traces_dir, state_dir):
        ingester = TraceIngester(str(traces_dir), str(state_dir))
        convs = ingester.ingest()
        assert len(ingester.get_new_conversations(convs)) == 2

    def test_count_new_rounds(self, traces_dir, state_dir):
        ingester = TraceIngester(str(traces_dir), str(state_dir))
        convs = ingester.ingest()
        new = ingester.get_new_conversations(convs)
        # session_001 has 2 rounds, session_002 has 1 round
        assert ingester.count_new_rounds(new) == 3

    def test_mark_processed_persists_state(self, traces_dir, state_dir):
        ingester = TraceIngester(str(traces_dir), str(state_dir))
        convs = ingester.ingest()
        ingester.mark_processed(convs, "2026-03-02T00:00:00Z")

        state = TraceState.load(str(state_dir / TRACE_STATE_FILE))
        assert set(state.processed_session_ids) == {"session_001", "session_002"}
        assert state.last_run_timestamp == "2026-03-02T00:00:00Z"

    def test_mark_processed_accumulates_across_runs(self, traces_dir, state_dir):
        ingester = TraceIngester(str(traces_dir), str(state_dir))
        convs = ingester.ingest()
        ingester.mark_processed([convs[0]], "t1")
        ingester.mark_processed([convs[1]], "t2")

        state = TraceState.load(str(state_dir / TRACE_STATE_FILE))
        assert len(state.processed_session_ids) == 2
