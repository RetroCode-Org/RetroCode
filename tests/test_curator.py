"""Tests for curator utility functions (no LLM calls)."""

import pytest

from contextEngineering.curator import (
    apply_operations,
    get_playbook_stats,
    load_playbook,
    save_playbook,
    DEFAULT_PLAYBOOK,
    SECTION_PREFIXES,
)


class TestGetPlaybookStats:
    def test_counts_bullets(self, populated_playbook):
        stats = get_playbook_stats(populated_playbook)
        assert stats["total_bullets"] == 3

    def test_lists_sections(self, populated_playbook):
        stats = get_playbook_stats(populated_playbook)
        assert "CODING_PATTERNS" in stats["sections"]
        assert "WORKFLOW_STRATEGIES" in stats["sections"]

    def test_empty_playbook(self, empty_playbook):
        stats = get_playbook_stats(empty_playbook)
        assert stats["total_bullets"] == 0
        assert len(stats["sections"]) > 0


class TestApplyOperations:
    def test_add_to_existing_section(self, empty_playbook):
        ops = [{"type": "ADD", "section": "CODING_PATTERNS", "content": "Read before editing."}]
        result, next_id = apply_operations(empty_playbook, ops, 1)
        assert "[pat-00001] Read before editing." in result
        assert next_id == 2

    def test_add_increments_id(self, empty_playbook):
        ops = [
            {"type": "ADD", "section": "CODING_PATTERNS", "content": "First tip."},
            {"type": "ADD", "section": "CODING_PATTERNS", "content": "Second tip."},
        ]
        result, next_id = apply_operations(empty_playbook, ops, 1)
        assert "[pat-00001]" in result
        assert "[pat-00002]" in result
        assert next_id == 3

    def test_add_uses_correct_prefix_per_section(self, empty_playbook):
        ops = [
            {"type": "ADD", "section": "WORKFLOW_STRATEGIES", "content": "Plan first."},
            {"type": "ADD", "section": "COMMON_MISTAKES", "content": "Don't guess paths."},
            {"type": "ADD", "section": "TOOL_USAGE", "content": "Use Grep not bash grep."},
        ]
        result, _ = apply_operations(empty_playbook, ops, 1)
        assert "[wf-00001]" in result
        assert "[mis-00002]" in result
        assert "[tool-00003]" in result

    def test_add_to_nonexistent_section_creates_it(self, empty_playbook):
        ops = [{"type": "ADD", "section": "OTHERS", "content": "Misc tip."}]
        result, _ = apply_operations(empty_playbook, ops, 1)
        assert "## OTHERS" in result
        assert "[oth-00001] Misc tip." in result

    def test_skips_empty_content(self, empty_playbook):
        ops = [{"type": "ADD", "section": "CODING_PATTERNS", "content": "  "}]
        result, next_id = apply_operations(empty_playbook, ops, 1)
        assert next_id == 1  # no ID consumed

    def test_skips_unknown_operation_type(self, empty_playbook):
        ops = [{"type": "DELETE", "section": "CODING_PATTERNS", "content": "something"}]
        result, next_id = apply_operations(empty_playbook, ops, 1)
        assert result == empty_playbook
        assert next_id == 1

    def test_respects_starting_id(self, empty_playbook):
        ops = [{"type": "ADD", "section": "CODING_PATTERNS", "content": "A tip."}]
        result, next_id = apply_operations(empty_playbook, ops, 42)
        assert "[pat-00042]" in result
        assert next_id == 43

    def test_bullet_inserted_after_section_header(self, empty_playbook):
        ops = [{"type": "ADD", "section": "CODING_PATTERNS", "content": "A tip."}]
        result, _ = apply_operations(empty_playbook, ops, 1)
        lines = result.splitlines()
        header_idx = next(i for i, l in enumerate(lines) if "## CODING_PATTERNS" in l)
        bullet_idx = next(i for i, l in enumerate(lines) if "[pat-00001]" in l)
        assert bullet_idx == header_idx + 1


class TestLoadSavePlaybook:
    def test_load_missing_file_returns_default(self, tmp_path):
        content, next_id = load_playbook(str(tmp_path / "missing.txt"))
        assert content == DEFAULT_PLAYBOOK
        assert next_id == 1

    def test_load_existing_file(self, tmp_path, populated_playbook):
        path = tmp_path / "playbook.txt"
        path.write_text(populated_playbook)
        content, next_id = load_playbook(str(path))
        assert content == populated_playbook
        assert next_id == 4  # max existing ID is 3

    def test_load_sets_next_id_from_max(self, tmp_path):
        playbook = "## CODING_PATTERNS\n[pat-00010] tip.\n[pat-00005] other.\n"
        path = tmp_path / "playbook.txt"
        path.write_text(playbook)
        _, next_id = load_playbook(str(path))
        assert next_id == 11

    def test_save_and_reload(self, tmp_path, populated_playbook):
        path = str(tmp_path / "playbook.txt")
        save_playbook(path, populated_playbook)
        content, _ = load_playbook(path)
        assert content == populated_playbook
