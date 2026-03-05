"""
Cursor agent trace reader.

Cursor stores agent transcripts at:
  ~/.cursor/projects/<project-key>/agent-transcripts/<session-id>/<session-id>.jsonl

The project key is derived from the working directory the same way Claude Code does it:
replace every '/' with '-', e.g. /data/lhc/RetroCode -> -data-lhc-RetroCode

Each JSONL line is: {role: "user"|"assistant", message: {content: [{type: "text", text: "..."}]}}
Tool calls appear as [Tool call] / [Tool result] blocks embedded in the assistant text.
"""

import json
import logging
import re
from pathlib import Path

from .base import BaseReader

logger = logging.getLogger(__name__)

# Cursor embeds tool calls/results as plain text markers in assistant messages.
_TOOL_CALL_RE = re.compile(r"^\[Tool call\]", re.MULTILINE)
_TOOL_RESULT_RE = re.compile(r"^\[Tool result\]", re.MULTILINE)
# Strip <user_query>...</user_query> and <attached_files>...</attached_files> wrappers
_USER_QUERY_RE = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL)
_ATTACHED_FILES_RE = re.compile(r"<attached_files>.*?</attached_files>", re.DOTALL)


class CursorReader(BaseReader):

    @property
    def tool_name(self) -> str:
        return "cursor"

    def find_trace_files(self, working_dir: str | Path) -> list[Path]:
        transcripts_dir = self._transcripts_dir(working_dir)
        if not transcripts_dir.is_dir():
            return []
        # Each session is a subdirectory containing <uuid>.jsonl
        return sorted(transcripts_dir.glob("*/*.jsonl"))

    def read_head_tail(self, filepath: Path, n: int = 5) -> tuple[list[str], list[str]]:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        head = [line.rstrip("\n") for line in lines[:n]]
        tail = [line.rstrip("\n") for line in lines[-n:]] if len(lines) > n else []
        return head, tail

    def parse_session(self, filepath: Path) -> dict:
        """Parse a Cursor .jsonl session file.

        Returns a dict with:
            session_id  – the file stem (UUID)
            timestamp   – empty string (Cursor does not store timestamps)
            messages    – list of {role, content} dicts (user/assistant only)
        """
        messages = []

        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = obj.get("role")
                if role not in ("user", "assistant"):
                    continue

                content = obj.get("message", {}).get("content", "")
                text = _extract_text(content, role)
                if not text:
                    continue

                messages.append({"role": role, "content": text})

        return {
            "session_id": filepath.stem,
            "timestamp": "",
            "messages": messages,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _project_key(working_dir: str | Path) -> str:
        """Convert an absolute path to a Cursor project key.

        Cursor uses the same slash->dash substitution as Claude Code but strips
        the leading dash that results from the leading '/' in absolute paths.
        e.g. /data/lhc/RetroCode -> data-lhc-RetroCode
        """
        return str(Path(working_dir).resolve()).replace("/", "-").lstrip("-")

    @classmethod
    def _transcripts_dir(cls, working_dir: str | Path) -> Path:
        key = cls._project_key(working_dir)
        return Path.home() / ".cursor" / "projects" / key / "agent-transcripts"


def _extract_text(content, role: str) -> str:
    """Extract plain text from a Cursor message content field.

    For user messages, strips <user_query> and <attached_files> wrappers.
    For assistant messages, keeps the full text (tool calls are embedded).
    """
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = " ".join(p.strip() for p in parts if p.strip())
    else:
        return ""

    if role == "user":
        # Strip attached file context, keep only the actual query
        text = _ATTACHED_FILES_RE.sub("", text)
        m = _USER_QUERY_RE.search(text)
        if m:
            text = m.group(1)

    return text.strip()
