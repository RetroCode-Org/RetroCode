from collections import Counter
import time

import monitoring.server as server
from monitoring.depgraph import DependencyGraph
from monitoring.file_edit_extractor import FileEditEvent, RoundSummary, SessionSummary
from monitoring.server import _answer_file_chat, _build_file_chat_context, _file_detail_payload


def build_project(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)

    (project / "src" / "__init__.py").write_text("")
    (project / "src" / "core.py").write_text("VALUE = 1\n")
    (project / "src" / "feature_a.py").write_text("from src.core import VALUE\nprint(VALUE)\n")
    (project / "src" / "feature_b.py").write_text("from src.core import VALUE\nprint(VALUE)\n")

    graph = DependencyGraph(str(project))
    graph.build()
    return project, graph


def make_sessions():
    return [
        SessionSummary(
            session_id="cursor-1",
            source="cursor",
            timestamp="2026-03-09T08:00:00Z",
            rounds=[
                RoundSummary(
                    round_num=0,
                    user_message="Tighten the shared core path.",
                    edits=[
                        FileEditEvent(
                            session_id="cursor-1",
                            source="cursor",
                            round_num=0,
                            timestamp="2026-03-09T08:00:00Z",
                            file_path="src/core.py",
                            tool_name="Edit",
                            action="edit",
                        )
                    ],
                )
            ],
        ),
        SessionSummary(
            session_id="codex-1",
            source="codex",
            timestamp="2026-03-09T09:15:00Z",
            rounds=[
                RoundSummary(
                    round_num=1,
                    user_message="Adjust the core invariant and note the callers.",
                    edits=[
                        FileEditEvent(
                            session_id="codex-1",
                            source="codex",
                            round_num=1,
                            timestamp="2026-03-09T09:15:00Z",
                            file_path="src/core.py",
                            tool_name="Write",
                            action="write",
                        )
                    ],
                )
            ],
        ),
    ]


def test_file_detail_payload_includes_trace_metadata(tmp_path):
    project, graph = build_project(tmp_path)
    sessions = make_sessions()
    payload = _file_detail_payload(
        "src/core.py",
        graph,
        sessions,
        Counter({"src/core.py": 2}),
        str(project),
        "Affects 2 files",
    )

    assert payload["last_edit"]["source"] == "codex"
    assert payload["edit_history"][0]["session_narrative"]
    assert payload["edit_history"][0]["user_message_preview"].startswith("Adjust the core invariant")


def test_build_file_chat_context_groups_editor_activity(tmp_path):
    project, graph = build_project(tmp_path)
    sessions = make_sessions()
    payload = _file_detail_payload(
        "src/core.py",
        graph,
        sessions,
        Counter({"src/core.py": 2}),
        str(project),
        "Affects 2 files",
    )

    context = _build_file_chat_context(payload)

    assert context["file"]["path"] == "src/core.py"
    assert [item["source"] for item in context["editor_activity"]] == ["codex", "cursor"]
    assert context["recent_traces"][0]["session_id"] == "codex-1"


def test_answer_file_chat_uses_llm_callable():
    seen = {}
    context = {
        "file": {"path": "src/core.py", "tier": 2, "blast_radius": 2, "edit_count": 2},
        "signals": [{"label": "Critical + quiet"}],
        "recommended_actions": ["Read the diff manually before merging."],
        "direct_imports": [],
        "direct_imported_by": ["src/feature_a.py", "src/feature_b.py"],
        "editor_activity": [
            {"source": "codex", "edit_count": 1, "last_timestamp": "2026-03-09T09:15:00Z", "last_tool": "Write"},
            {"source": "cursor", "edit_count": 1, "last_timestamp": "2026-03-09T08:00:00Z", "last_tool": "Edit"},
        ],
        "recent_traces": [
            {"session_id": "codex-1", "source": "codex", "timestamp": "2026-03-09T09:15:00Z", "round_num": 1, "tool_name": "Write"},
        ],
    }

    def fake_llm(system, prompt, **kwargs):
        seen["system"] = system
        seen["prompt"] = prompt
        seen["kwargs"] = kwargs
        return "Cross-editor summary"

    answer, used_llm, warning = _answer_file_chat(
        "What changed across editors?",
        context,
        model="gpt-5.2",
        llm_callable=fake_llm,
    )

    assert answer == "Cross-editor summary"
    assert used_llm is True
    assert warning is None
    assert seen["kwargs"]["model"] == "gpt-5.2"
    assert "src/core.py" in seen["prompt"]
    assert "codex" in seen["prompt"]


def test_answer_file_chat_falls_back_when_llm_fails():
    context = {
        "file": {"path": "src/core.py", "tier": 2, "blast_radius": 2, "edit_count": 2},
        "signals": [{"label": "Critical + quiet"}],
        "recommended_actions": ["Read the diff manually before merging."],
        "direct_imports": [],
        "direct_imported_by": ["src/feature_a.py", "src/feature_b.py"],
        "editor_activity": [
            {"source": "codex", "edit_count": 1, "last_timestamp": "2026-03-09T09:15:00Z", "last_tool": "Write"},
            {"source": "cursor", "edit_count": 1, "last_timestamp": "2026-03-09T08:00:00Z", "last_tool": "Edit"},
        ],
        "recent_traces": [
            {"session_id": "codex-1", "source": "codex", "timestamp": "2026-03-09T09:15:00Z", "round_num": 1, "tool_name": "Write"},
        ],
    }

    answer, used_llm, warning = _answer_file_chat(
        "Summarize the recent edits.",
        context,
        llm_callable=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    assert used_llm is False
    assert "heuristic summary" in warning
    assert "src/core.py" in answer
    assert "codex" in answer


def test_answer_file_chat_times_out_to_fallback(monkeypatch):
    context = {
        "file": {"path": "src/core.py", "tier": 2, "blast_radius": 2, "edit_count": 2},
        "signals": [{"label": "Critical + quiet"}],
        "recommended_actions": ["Read the diff manually before merging."],
        "direct_imports": [],
        "direct_imported_by": ["src/feature_a.py"],
        "editor_activity": [{"source": "cursor", "edit_count": 1, "last_timestamp": "2026-03-09T08:00:00Z", "last_tool": "Edit"}],
        "recent_traces": [{"session_id": "cursor-1", "source": "cursor", "timestamp": "2026-03-09T08:00:00Z", "round_num": 0, "tool_name": "Edit"}],
    }

    monkeypatch.setattr(server, "_FILE_CHAT_TIMEOUT_S", 0.01)

    def slow_llm(*args, **kwargs):
        time.sleep(0.05)
        return "too slow"

    answer, used_llm, warning = _answer_file_chat(
        "What happened?",
        context,
        llm_callable=slow_llm,
    )

    assert used_llm is False
    assert "timed out" in warning
    assert "src/core.py" in answer
