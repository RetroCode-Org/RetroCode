"""
Seed feature functions for Claude Code round-level hypothesis testing.

Each round: one user message + all assistant/tool messages until the next user message.
Features look at ALL messages within a round (msgs) to detect patterns that predict
an explicit user rejection in the NEXT user message.

Each function: feat_<name>(msgs: list[dict]) -> bool
  msgs = messages within one round (assistant + tool messages)

Design philosophy: hypotheses should be simple, testable, and potentially
informational. A good hypothesis is one that, if confirmed, tells the user
something actionable about how agents fail.
"""
from __future__ import annotations

from src.hypoGen.generator.hypothesis import (
    iter_tool_calls, iter_tool_results, _seed, Hypothesis,
    EDIT_TOOLS, READ_TOOLS, SEARCH_TOOLS, BASH_TOOL, AGENT_TOOL, ERROR_KWS,
)


# ── Tool ordering patterns ──────────────────────────────────────────────

def feat_edit_without_read(msgs: list[dict]) -> bool:
    """[TOXIC] Agent edits a file it never Read in this round."""
    read_files: set[str] = set()
    for tn, args in iter_tool_calls(msgs):
        if tn in READ_TOOLS:
            read_files.add(args.get("file_path", ""))
        elif tn in EDIT_TOOLS:
            path = args.get("file_path", "")
            if path and path not in read_files:
                return True
    return False


def feat_edit_without_search(msgs: list[dict]) -> bool:
    """[TOXIC] Agent edits files without any Glob/Grep search first."""
    has_search = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
    has_edit = any(tn in EDIT_TOOLS for tn, _ in iter_tool_calls(msgs))
    return has_edit and not has_search


def feat_more_edits_than_reads(msgs: list[dict]) -> bool:
    """[TOXIC] Agent makes 2+ edits but fewer reads — acting without looking."""
    reads = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in READ_TOOLS)
    edits = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in EDIT_TOOLS)
    return edits >= 2 and edits > reads


# ── Error patterns ──────────────────────────────────────────────────────

def feat_bash_fails(msgs: list[dict]) -> bool:
    """[TOXIC] A Bash command produced an error keyword (traceback, failed, etc.)."""
    for name, content in iter_tool_results(msgs):
        if name == BASH_TOOL and any(kw in content.lower() for kw in ERROR_KWS):
            return True
    return False


def feat_repeated_bash_errors(msgs: list[dict]) -> bool:
    """[TOXIC] Multiple Bash commands in this round produced errors."""
    err_count = 0
    for name, content in iter_tool_results(msgs):
        if name == BASH_TOOL and any(kw in content.lower() for kw in ERROR_KWS):
            err_count += 1
    return err_count >= 2


# ── Scale / blast patterns ──────────────────────────────────────────────

def feat_many_files_edited(msgs: list[dict]) -> bool:
    """[TOXIC] Agent edited 4+ different files in one round — wide blast."""
    edited: set[str] = set()
    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            path = args.get("file_path", "")
            if path:
                edited.add(path)
    return len(edited) >= 4


def feat_long_round(msgs: list[dict]) -> bool:
    """[TOXIC] Round has 20+ messages — agent may be flailing."""
    return len(msgs) >= 20


def feat_large_edit(msgs: list[dict]) -> bool:
    """[TOXIC] Agent wrote a very long edit (new_string > 2000 chars)."""
    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            new_str = args.get("new_string", "") or args.get("content", "")
            if len(new_str) > 2000:
                return True
    return False


# ── Behavioral patterns ─────────────────────────────────────────────────

def feat_edits_same_file_repeatedly(msgs: list[dict]) -> bool:
    """[TOXIC] Agent edits the same file 3+ times — circling without converging."""
    edit_counts: dict[str, int] = {}
    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            path = args.get("file_path", "")
            if path:
                edit_counts[path] = edit_counts.get(path, 0) + 1
    return any(c >= 3 for c in edit_counts.values())


def feat_no_tool_calls(msgs: list[dict]) -> bool:
    """[TOXIC] Agent responded with only text, no tool calls at all."""
    return not any(True for _ in iter_tool_calls(msgs))


def feat_agent_delegation(msgs: list[dict]) -> bool:
    """[TOXIC] Agent spawned a sub-agent in this round."""
    return any(tn == AGENT_TOOL for tn, _ in iter_tool_calls(msgs))


def feat_write_new_file(msgs: list[dict]) -> bool:
    """[TOXIC] Agent used Write (create new file) instead of Edit (modify existing)."""
    return any(tn == "Write" for tn, _ in iter_tool_calls(msgs))


def feat_no_search_before_action(msgs: list[dict]) -> bool:
    """[TOXIC] Agent takes action (Edit/Bash) without any prior search."""
    has_action = any(
        tn in EDIT_TOOLS or tn == BASH_TOOL
        for tn, _ in iter_tool_calls(msgs)
    )
    has_search = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
    return has_action and not has_search


# ── Retry / flailing patterns ─────────────────────────────────────────

def feat_bash_retry_same_error(msgs: list[dict]) -> bool:
    """[TOXIC] Agent runs Bash, gets error, then runs a similar Bash command again."""
    last_bash_errored = False
    for m in msgs:
        if m["role"] == "tool" and m.get("name") == BASH_TOOL:
            has_err = any(kw in m["content"].lower() for kw in ERROR_KWS)
            if has_err and last_bash_errored:
                return True
            last_bash_errored = has_err
        elif m["role"] == "assistant":
            # Reset on non-Bash tool calls between retries
            pass
    return False


def feat_ignores_tool_error(msgs: list[dict]) -> bool:
    """[TOXIC] Agent gets an error result but immediately edits without reading the error."""
    saw_error = False
    for m in msgs:
        if m["role"] == "tool":
            has_err = any(kw in m["content"].lower() for kw in ERROR_KWS)
            if has_err:
                saw_error = True
        elif m["role"] == "assistant" and saw_error:
            tool_names = m.get("tool_names", [])
            if any(tn in EDIT_TOOLS for tn in tool_names):
                # Edited right after an error without reading first
                if not any(tn in READ_TOOLS for tn in tool_names):
                    return True
            saw_error = False
    return False


def feat_search_empty_then_edit(msgs: list[dict]) -> bool:
    """[TOXIC] Agent's Glob/Grep returned no results but it still edited files."""
    search_returned_empty = False
    for m in msgs:
        if m["role"] == "tool" and m.get("name") in SEARCH_TOOLS:
            content = m["content"].strip()
            if not content or content.lower() in ("no files found", "no matches found", ""):
                search_returned_empty = True
        elif m["role"] == "assistant" and search_returned_empty:
            if any(tn in EDIT_TOOLS for tn in m.get("tool_names", [])):
                return True
    return False


def feat_escalating_edits(msgs: list[dict]) -> bool:
    """[TOXIC] Agent's edits get progressively longer — each bigger than the last."""
    edit_sizes: list[int] = []
    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            new_str = args.get("new_string", "") or args.get("content", "")
            edit_sizes.append(len(new_str))
    if len(edit_sizes) < 3:
        return False
    return all(edit_sizes[i] > edit_sizes[i - 1] for i in range(1, len(edit_sizes)))


def feat_no_verify_after_edit(msgs: list[dict]) -> bool:
    """[TOXIC] Agent edits code but never runs tests/build/lint to verify."""
    has_edit = False
    has_verify = False
    verify_kws = ("test", "pytest", "npm test", "make", "cargo", "build", "lint",
                  "eslint", "tsc", "python -m", "go test", "check")
    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            has_edit = True
        elif tn == BASH_TOOL and has_edit:
            cmd = args.get("command", "").lower()
            if any(kw in cmd for kw in verify_kws):
                has_verify = True
    return has_edit and not has_verify


def feat_text_heavy_response(msgs: list[dict]) -> bool:
    """[TOXIC] Agent's text output exceeds tool calls 3:1 — over-explaining instead of acting."""
    text_chars = 0
    tool_calls = 0
    for m in msgs:
        if m["role"] == "assistant":
            text_chars += m.get("char_len", len(m.get("content", "")))
            tool_calls += len(m.get("tool_names", []))
    if tool_calls == 0:
        return text_chars > 500
    return text_chars > tool_calls * 500


# ── Healthy patterns (predict acceptance) ──────────────────────────────

def feat_read_then_edit_same_file(msgs: list[dict]) -> bool:
    """[HEALTHY] Agent reads a file then edits the same file — careful approach."""
    read_files: set[str] = set()
    for tn, args in iter_tool_calls(msgs):
        if tn in READ_TOOLS:
            read_files.add(args.get("file_path", ""))
        elif tn in EDIT_TOOLS:
            path = args.get("file_path", "")
            if path and path in read_files:
                return True
    return False


def feat_search_read_edit_flow(msgs: list[dict]) -> bool:
    """[HEALTHY] Agent follows search → read → edit pipeline (systematic approach)."""
    phase = 0  # 0=none, 1=searched, 2=read, 3=edited
    for tn, _ in iter_tool_calls(msgs):
        if tn in SEARCH_TOOLS and phase < 1:
            phase = 1
        elif tn in READ_TOOLS and phase >= 1:
            phase = 2
        elif tn in EDIT_TOOLS and phase >= 2:
            phase = 3
    return phase == 3


def feat_single_focused_edit(msgs: list[dict]) -> bool:
    """[HEALTHY] Agent makes exactly one edit — small, focused change."""
    edit_count = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in EDIT_TOOLS)
    return edit_count == 1


SEED_HYPOTHESES: list[Hypothesis] = [
    # Tool ordering
    _seed(feat_edit_without_read,         toxic=True),
    _seed(feat_edit_without_search,       toxic=True),
    _seed(feat_more_edits_than_reads,     toxic=True),
    _seed(feat_no_search_before_action,   toxic=True),
    # Errors
    _seed(feat_bash_fails,                toxic=True),
    _seed(feat_repeated_bash_errors,      toxic=True),
    # Scale / blast
    _seed(feat_many_files_edited,         toxic=True),
    _seed(feat_long_round,                toxic=True),
    _seed(feat_large_edit,                toxic=True),
    # Behavioral
    _seed(feat_edits_same_file_repeatedly, toxic=True),
    _seed(feat_no_tool_calls,             toxic=True),
    _seed(feat_agent_delegation,          toxic=True),
    _seed(feat_write_new_file,            toxic=True),
    # Retry / flailing
    _seed(feat_bash_retry_same_error,     toxic=True),
    _seed(feat_ignores_tool_error,        toxic=True),
    _seed(feat_search_empty_then_edit,    toxic=True),
    _seed(feat_escalating_edits,          toxic=True),
    _seed(feat_no_verify_after_edit,      toxic=True),
    _seed(feat_text_heavy_response,       toxic=True),
    # Healthy (non-toxic — predict acceptance)
    _seed(feat_read_then_edit_same_file,  toxic=False),
    _seed(feat_search_read_edit_flow,     toxic=False),
    _seed(feat_single_focused_edit,       toxic=False),
]
