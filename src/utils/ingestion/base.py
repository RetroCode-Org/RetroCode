"""
Abstract base class for tool-specific trace readers.

To add support for a new tool, subclass BaseReader and implement all
abstract methods, then pass an instance to run_daemon() in src/main.py.
"""

from abc import ABC, abstractmethod
from pathlib import Path


# ── Tool name normalization ───────────────────────────────────────────
#
# All readers should produce the same canonical tool names so that
# downstream features, hypotheses, and stats see a uniform view.
#
# Canonical names (Claude Code native):
#   Read, Edit, Write, Bash, Glob, Grep, Agent, NotebookEdit,
#   WebFetch, WebSearch, Skill
#
# Source-specific names are mapped to canonical names at parse time.

TOOL_NAME_MAP: dict[str, str] = {
    # Codex CLI function names
    "exec_command":     "Bash",
    "shell":            "Bash",
    "terminal":         "Bash",
    "write_stdin":      "Bash",         # stdin to a running process
    "read_file":        "Read",
    "readfile":         "Read",
    "write_file":       "Write",
    "writefile":        "Write",
    "edit_file":        "Edit",
    "editfile":         "Edit",
    "patch":            "Edit",
    "apply_diff":       "Edit",
    "search":           "Grep",
    "grep":             "Grep",
    "find_files":       "Glob",
    "glob":             "Glob",
    "list_dir":         "Glob",
    "listdir":          "Glob",
    "ls":               "Glob",
    "update_plan":      "Agent",        # Codex planning = agent-like
    # Cursor tool names (if extracted)
    "run_terminal_cmd": "Bash",
    "read_file_tool":   "Read",
    "edit_file_tool":   "Edit",
    "search_files":     "Grep",
    "list_files":       "Glob",
    "file_search":      "Glob",
    "codebase_search":  "Grep",
}


def normalize_tool_name(name: str) -> str:
    """Map a source-specific tool name to its canonical equivalent."""
    return TOOL_NAME_MAP.get(name, TOOL_NAME_MAP.get(name.lower(), name))


def normalize_messages(messages: list[dict]) -> list[dict]:
    """Normalize all tool names in a message list in-place."""
    for msg in messages:
        if msg.get("role") == "assistant":
            msg["tool_names"] = [normalize_tool_name(tn) for tn in msg.get("tool_names", [])]
        elif msg.get("role") == "tool":
            msg["name"] = normalize_tool_name(msg.get("name", ""))
    return messages


class BaseReader(ABC):

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Human-readable name of the tool whose traces this reader handles."""

    @abstractmethod
    def find_trace_files(self, working_dir: str | Path) -> list[Path]:
        """Return all trace files relevant to *working_dir*, sorted."""

    @abstractmethod
    def read_head_tail(self, filepath: Path, n: int = 5) -> tuple[list[str], list[str]]:
        """Return (head, tail) where each is at most *n* lines from *filepath*.

        If the file has <= n lines, tail should be empty to avoid duplication.
        Lines must be stripped of their trailing newline.
        """
