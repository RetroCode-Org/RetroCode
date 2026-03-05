"""
Seed feature functions for Claude Code round-level hypothesis testing.

Each round: one user message + all assistant/tool messages until the next user message.
Features look at ALL messages within a round (msgs) to detect patterns that predict
an explicit user rejection in the NEXT user message.

Each function: feat_<name>(msgs: list[dict]) -> bool
  msgs = messages within one round (assistant + tool messages)
"""
from __future__ import annotations

from src.hypoGen.generator.hypothesis import (
    iter_tool_calls, iter_tool_results, _seed, Hypothesis,
    EDIT_TOOLS, READ_TOOLS, SEARCH_TOOLS, BASH_TOOL, AGENT_TOOL, ERROR_KWS,
)


def feat_edit_without_read(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, agent edits a file without having Read it first."""
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
    """[TOXIC] In this round, agent edits files without any Glob/Grep search."""
    has_search = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
    has_edit = any(tn in EDIT_TOOLS for tn, _ in iter_tool_calls(msgs))
    return has_edit and not has_search


def feat_more_edits_than_reads(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, agent makes more edits than reads."""
    reads = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in READ_TOOLS)
    edits = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in EDIT_TOOLS)
    return edits >= 2 and edits > reads


def feat_bash_fails(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, a Bash command produced an error."""
    for name, content in iter_tool_results(msgs):
        if name == BASH_TOOL and any(kw in content.lower() for kw in ERROR_KWS):
            return True
    return False


def feat_no_search_before_action(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, agent takes action (Edit/Bash) without any search."""
    has_action = any(
        tn in EDIT_TOOLS or tn == BASH_TOOL
        for tn, _ in iter_tool_calls(msgs)
    )
    has_search = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
    return has_action and not has_search


SEED_HYPOTHESES: list[Hypothesis] = [
    _seed(feat_edit_without_read,       toxic=True),
    _seed(feat_edit_without_search,     toxic=True),
    _seed(feat_more_edits_than_reads,   toxic=True),
    _seed(feat_bash_fails,              toxic=True),
    _seed(feat_no_search_before_action, toxic=True),
]
