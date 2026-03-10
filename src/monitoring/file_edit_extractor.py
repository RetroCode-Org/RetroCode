"""Extract file-edit events from agent traces.

Normalizes tool usage across Claude Code, Cursor, and Codex into a common
FileEditEvent stream.  Follows [coding-00018]: cross-trace action-extraction
layer that is source-agnostic at the output level.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# Tool names that correspond to file edits
_EDIT_TOOLS = {"Edit", "edit", "Write", "write", "NotebookEdit"}
_READ_TOOLS = {"Read", "read", "View", "Grep", "Glob"}

# Regex for extracting file paths from Bash commands that write to files
_BASH_WRITE_RE = re.compile(
    r'(?:>>?\s*|tee\s+(?:-a\s+)?|cp\s+\S+\s+|mv\s+\S+\s+)(["\']?)(/[^\s"\']+|[^\s"\']+)\1'
)

_COMMON_BARE_FILENAMES = {
    "Brewfile",
    "Dockerfile",
    "Gemfile",
    "Justfile",
    "LICENSE",
    "Makefile",
    "NOTICE",
    "Procfile",
    "Rakefile",
}
_INVALID_PATH_EXACT = {
    "",
    ".",
    "..",
    "-",
    "=",
    "&1",
    "/dev/null",
}
_INVALID_PATH_PREFIXES = (
    "/dev/fd/",
    "/proc/self/fd/",
)
_SHELL_META_CHARS = set("|&><*?;$(){}")

# Cursor tool call pattern: [Tool call] ToolName { ... json ... }
_CURSOR_TOOL_RE = re.compile(
    r"\[Tool call\]\s+(\w+)\s*(\{.*?\})",
    re.DOTALL,
)
_MARKDOWN_LINK_TARGET_RE = re.compile(r"\]\(([^)\s]+)\)")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_TEXT_PATH_RE = re.compile(
    r"(?<![\w/.-])("
    r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9._-]+"
    r"|"
    r"[A-Za-z0-9_.-]+\.(?:py|html|js|ts|tsx|jsx|css|md|yaml|yml|toml|json|txt|ini|cfg|sh|rst)"
    r")(?![\w.-])"
)
_TEXT_PATH_SUFFIX_RE = re.compile(r"(?:(?::\d+(?::\d+)?)|#L\d+(?:C\d+)?)$")
_CHANGE_HINTS = (
    "done.",
    "summary of changes",
    "changes made",
    "main rewrite is in",
    "i fixed",
    "fixed",
    "added",
    "updated",
    "removed",
    "replaced",
    "replacing",
    "changed",
    "switching to",
    "switched to",
    "configured",
    "tightened",
    "improved",
    "rewrote",
    "rewrite",
    "stacked",
    "cut the overview",
    "adding them to",
    "updating the",
)
_NON_CHANGE_PREFIXES = (
    "let me ",
    "checking ",
    "confirming ",
    "found it.",
    "recent commits",
    "`git-ai-search` is active",
    "result:",
    "found 1 ai session",
    "prompt id:",
    "the user wants",
    "run this test script",
    "the problem wasn't",
    "most likely cause",
    "`error_count` is computed",
)


@dataclass
class FileEditEvent:
    """One file-edit action extracted from a trace."""
    session_id: str
    source: str          # "claude-code" | "cursor" | "codex"
    round_num: int
    timestamp: str
    file_path: str       # path that was edited
    tool_name: str       # Edit, Write, Bash, etc.
    action: str          # "edit" | "write" | "create" | "bash_write"


@dataclass
class SessionSummary:
    """Aggregated edit info for one agent session."""
    session_id: str
    source: str
    timestamp: str
    rounds: list[RoundSummary] = field(default_factory=list)

    @property
    def files_edited(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for r in self.rounds:
            for e in r.edits:
                if e.file_path not in seen:
                    seen.add(e.file_path)
                    result.append(e.file_path)
        return result


@dataclass
class RoundSummary:
    """Edits within a single round of an agent session."""
    round_num: int
    user_message: str
    edits: list[FileEditEvent] = field(default_factory=list)


# ------------------------------------------------------------------
# Claude Code extraction (uses trace_parser for rich tool data)
# ------------------------------------------------------------------

def _extract_claude_sessions(working_dir: str) -> list[SessionSummary]:
    """Extract file edits from Claude Code traces using the rich trace parser."""
    from src.hypoGen.trace_parser import parse_session as rich_parse
    from src.utils.ingestion import ClaudeReader

    reader = ClaudeReader()
    sessions: list[SessionSummary] = []

    for fp in reader.find_trace_files(working_dir):
        try:
            # Get timestamp from the basic reader
            basic = reader.parse_session(fp)
            timestamp = basic["timestamp"]
            session_id = basic["session_id"]

            # Use rich parser for tool call data
            messages = rich_parse(fp)
            rounds = _split_into_rounds(messages)

            summary = SessionSummary(
                session_id=session_id,
                source="claude-code",
                timestamp=timestamp,
            )

            for round_num, (user_msg, round_msgs) in enumerate(rounds):
                rs = RoundSummary(round_num=round_num, user_message=user_msg)
                for msg in round_msgs:
                    if msg["role"] != "assistant":
                        continue
                    for tn, ta in zip(msg.get("tool_names", []), msg.get("tool_args", [])):
                        fp_str = _extract_filepath_from_args(tn, ta, working_dir)
                        if fp_str:
                            rs.edits.append(FileEditEvent(
                                session_id=session_id,
                                source="claude-code",
                                round_num=round_num,
                                timestamp=timestamp,
                                file_path=fp_str,
                                tool_name=tn,
                                action=_classify_action(tn),
                            ))
                summary.rounds.append(rs)
            sessions.append(summary)
        except Exception:
            continue

    return sessions


# ------------------------------------------------------------------
# Codex extraction
# ------------------------------------------------------------------

def _extract_codex_sessions(working_dir: str) -> list[SessionSummary]:
    """Extract file edits from Codex traces."""
    from src.utils.ingestion import CodexReader

    reader = CodexReader()
    sessions: list[SessionSummary] = []

    for fp in reader.find_trace_files(working_dir):
        try:
            data = reader.parse_session(fp)
            messages = data["messages"]
            session_id = data["session_id"]
            timestamp = data["timestamp"]
            rounds = _split_into_rounds(messages)

            summary = SessionSummary(
                session_id=session_id,
                source="codex",
                timestamp=timestamp,
            )
            inferred_edits_by_round: list[list[FileEditEvent]] = []

            for round_num, (user_msg, round_msgs) in enumerate(rounds):
                rs = RoundSummary(round_num=round_num, user_message=user_msg)
                for msg in round_msgs:
                    if msg["role"] != "assistant":
                        continue
                    for tn, ta in zip(msg.get("tool_names", []), msg.get("tool_args", [])):
                        fp_str = _extract_filepath_from_args(tn, ta, working_dir)
                        if fp_str:
                            rs.edits.append(FileEditEvent(
                                session_id=session_id,
                                source="codex",
                                round_num=round_num,
                                timestamp=timestamp,
                                file_path=fp_str,
                                tool_name=tn,
                                action=_classify_action(tn),
                            ))
                inferred_edits_by_round.append(
                    _infer_text_edits(
                        session_id=session_id,
                        source="codex",
                        round_num=round_num,
                        timestamp=timestamp,
                        round_msgs=round_msgs,
                        working_dir=working_dir,
                    )
                )
                summary.rounds.append(rs)
            if not summary.files_edited:
                for rs, inferred in zip(summary.rounds, inferred_edits_by_round):
                    rs.edits.extend(inferred)
            sessions.append(summary)
        except Exception:
            continue

    return sessions


# ------------------------------------------------------------------
# Cursor extraction (tool calls embedded in text)
# ------------------------------------------------------------------

def _extract_cursor_sessions(working_dir: str) -> list[SessionSummary]:
    """Extract file edits from Cursor traces by parsing text-embedded tool calls."""
    from src.utils.ingestion import CursorReader

    reader = CursorReader()
    sessions: list[SessionSummary] = []

    for fp in reader.find_trace_files(working_dir):
        try:
            data = reader.parse_session(fp)
            messages = data["messages"]
            session_id = data["session_id"]
            timestamp = data["timestamp"]
            rounds = _split_into_rounds(messages)

            summary = SessionSummary(
                session_id=session_id,
                source="cursor",
                timestamp=timestamp,
            )
            inferred_edits_by_round: list[list[FileEditEvent]] = []

            for round_num, (user_msg, round_msgs) in enumerate(rounds):
                rs = RoundSummary(round_num=round_num, user_message=user_msg)
                for msg in round_msgs:
                    if msg["role"] != "assistant":
                        continue
                    # Parse tool calls from the text content
                    for match in _CURSOR_TOOL_RE.finditer(msg.get("content", "")):
                        tool_name = match.group(1)
                        try:
                            tool_args = json.loads(match.group(2))
                        except json.JSONDecodeError:
                            continue
                        fp_str = _extract_filepath_from_args(tool_name, tool_args, working_dir)
                        if fp_str:
                            rs.edits.append(FileEditEvent(
                                session_id=session_id,
                                source="cursor",
                                round_num=round_num,
                                timestamp=timestamp,
                                file_path=fp_str,
                                tool_name=tool_name,
                                action=_classify_action(tool_name),
                            ))
                inferred_edits_by_round.append(
                    _infer_text_edits(
                        session_id=session_id,
                        source="cursor",
                        round_num=round_num,
                        timestamp=timestamp,
                        round_msgs=round_msgs,
                        working_dir=working_dir,
                    )
                )
                summary.rounds.append(rs)
            if not summary.files_edited:
                for rs, inferred in zip(summary.rounds, inferred_edits_by_round):
                    rs.edits.extend(inferred)
            sessions.append(summary)
        except Exception:
            continue

    return sessions


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def extract_all_sessions(working_dir: str) -> list[SessionSummary]:
    """Extract file edit events from all configured trace sources."""
    sessions: list[SessionSummary] = []
    sessions.extend(_extract_claude_sessions(working_dir))
    sessions.extend(_extract_codex_sessions(working_dir))
    sessions.extend(_extract_cursor_sessions(working_dir))
    # Sort by timestamp (most recent first), empty timestamps last
    sessions.sort(key=lambda s: s.timestamp or "", reverse=True)
    return sessions


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _split_into_rounds(messages: list[dict]) -> list[tuple[str, list[dict]]]:
    """Split a message list into (user_msg, [round_msgs]) tuples."""
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    rounds: list[tuple[str, list[dict]]] = []
    for idx, start in enumerate(user_indices):
        user_msg = messages[start].get("content", "")
        end = user_indices[idx + 1] if idx + 1 < len(user_indices) else len(messages)
        round_msgs = messages[start + 1:end]
        rounds.append((user_msg, round_msgs))
    return rounds


def _infer_text_edits(
    *,
    session_id: str,
    source: str,
    round_num: int,
    timestamp: str,
    round_msgs: list[dict],
    working_dir: str,
) -> list[FileEditEvent]:
    """Recover touched files from assistant change summaries when tool logs are absent."""
    seen: set[str] = set()
    inferred: list[FileEditEvent] = []
    if not any(_message_describes_change(msg.get("content", "")) for msg in round_msgs if msg.get("role") == "assistant"):
        return inferred

    for file_path in _extract_round_paths(round_msgs, working_dir):
            if _ignore_inferred_path(file_path):
                continue
            if file_path in seen:
                continue
            seen.add(file_path)
            inferred.append(FileEditEvent(
                session_id=session_id,
                source=source,
                round_num=round_num,
                timestamp=timestamp,
                file_path=file_path,
                tool_name="assistant-summary",
                action="edit",
            ))
    return inferred


def _extract_round_paths(round_msgs: list[dict], working_dir: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for msg in round_msgs:
        if msg.get("role") != "assistant":
            continue
        for file_path in _extract_paths_from_text(msg.get("content", ""), working_dir):
            if file_path in seen:
                continue
            seen.add(file_path)
            paths.append(file_path)
    return paths


def _message_describes_change(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized or normalized.startswith("[tool_call:"):
        return False
    if any(normalized.startswith(prefix) for prefix in _NON_CHANGE_PREFIXES):
        return False
    return any(hint in normalized for hint in _CHANGE_HINTS)


def _extract_paths_from_text(text: str, working_dir: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    candidates: list[str] = []
    for pattern in (_MARKDOWN_LINK_TARGET_RE, _CODE_SPAN_RE, _TEXT_PATH_RE):
        candidates.extend(match.group(1) for match in pattern.finditer(text))

    for candidate in candidates:
        resolved = _resolve_text_path(candidate, working_dir)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        paths.append(resolved)
    return paths


def _resolve_text_path(candidate: str, working_dir: str) -> str | None:
    raw = candidate.strip().strip("()[]{}<>\"'")
    raw = raw.split("?", 1)[0]
    raw = raw.split("#", 1)[0]
    raw = _TEXT_PATH_SUFFIX_RE.sub("", raw)
    raw = raw.rstrip(".,:;)")
    if raw.startswith(("a/", "b/")):
        raw = raw[2:]

    normalized = _normalize_project_path(raw, working_dir)
    if normalized:
        return normalized

    if "/" in raw or raw.startswith((".", "~")):
        return None

    matches = _repo_file_index(working_dir).get(raw, ())
    return matches[0] if len(matches) == 1 else None


def _ignore_inferred_path(path: str) -> bool:
    return (
        path.startswith(("build/", "dist/"))
        or ".egg-info/" in path
        or "__pycache__/" in path
    )


@lru_cache(maxsize=8)
def _repo_file_index(working_dir: str) -> dict[str, tuple[str, ...]]:
    wd = Path(working_dir).resolve()
    index: dict[str, list[str]] = {}
    for path in wd.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(wd))
        if _ignore_inferred_path(rel):
            continue
        index.setdefault(path.name, []).append(rel)
    return {name: tuple(sorted(paths)) for name, paths in index.items()}


def _extract_filepath_from_args(tool_name: str, tool_args: dict, working_dir: str) -> str | None:
    """Extract and normalize a file path from tool arguments."""
    if not isinstance(tool_args, dict):
        return None

    fp = None
    if tool_name in _EDIT_TOOLS:
        fp = tool_args.get("file_path") or tool_args.get("path")
    elif tool_name in ("Bash", "bash", "shell"):
        # Best-effort: look for file-writing patterns in bash commands
        cmd = tool_args.get("command", "")
        match = _BASH_WRITE_RE.search(cmd)
        if match:
            fp = match.group(2)
        else:
            return None
    else:
        return None

    if not fp:
        return None

    return _normalize_project_path(fp, working_dir)


def _normalize_project_path(file_path: str, working_dir: str) -> str | None:
    """Return a repo-relative file path, dropping shell junk and off-project writes."""
    candidate = file_path.strip().strip("\"'`")
    while candidate.endswith((";", ",")):
        candidate = candidate[:-1]

    if not candidate or candidate in _INVALID_PATH_EXACT:
        return None
    if candidate.startswith(_INVALID_PATH_PREFIXES):
        return None
    if any(ch in candidate for ch in _SHELL_META_CHARS):
        return None
    if candidate.startswith("~"):
        return None

    wd = Path(working_dir).resolve()
    raw_path = Path(candidate)

    # Single bare shell words like "dash" are usually command artifacts, not files.
    if (
        len(raw_path.parts) == 1
        and "." not in raw_path.name
        and raw_path.name not in _COMMON_BARE_FILENAMES
    ):
        root_candidate = wd / raw_path
        if not root_candidate.exists() or root_candidate.is_dir():
            return None

    try:
        if raw_path.is_absolute():
            resolved = raw_path.resolve(strict=False)
        else:
            resolved = (wd / raw_path).resolve(strict=False)
        relative = resolved.relative_to(wd)
    except ValueError:
        return None

    if not resolved.exists() or resolved.is_dir():
        return None

    normalized = str(relative)
    if not normalized or normalized == ".":
        return None
    return normalized


def _classify_action(tool_name: str) -> str:
    if tool_name in ("Edit", "edit"):
        return "edit"
    if tool_name in ("Write", "write"):
        return "write"
    if tool_name == "NotebookEdit":
        return "edit"
    if tool_name in ("Bash", "bash", "shell"):
        return "bash_write"
    return "edit"
