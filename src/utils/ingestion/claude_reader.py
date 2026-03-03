"""
Claude Code trace reader.

Claude stores session traces at:
  ~/.claude/projects/<project-key>/<session-id>.jsonl

The project key is derived from the working directory by replacing every
'/' with '-', e.g. /data/lhc/RetroCode -> -data-lhc-RetroCode
"""

import json
import logging
from pathlib import Path

from .base import BaseReader

logger = logging.getLogger(__name__)


class ClaudeReader(BaseReader):

    @property
    def tool_name(self) -> str:
        return "claude-code"

    def find_trace_files(self, working_dir: str | Path) -> list[Path]:
        project_dir = self._project_dir(working_dir)
        if not project_dir.is_dir():
            return []
        return sorted(project_dir.glob("*.jsonl"))

    def read_head_tail(self, filepath: Path, n: int = 5) -> tuple[list[str], list[str]]:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        head = [line.rstrip("\n") for line in lines[:n]]
        tail = [line.rstrip("\n") for line in lines[-n:]] if len(lines) > n else []
        return head, tail

    def parse_session(self, filepath: Path) -> dict:
        """Parse a .jsonl session file into a Conversation-compatible dict.

        Returns a dict with:
            session_id  – the file stem (UUID)
            timestamp   – ISO timestamp of the first message
            messages    – list of {role, content} dicts (user/assistant only)
        """
        messages = []
        timestamp = ""

        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") not in ("user", "assistant"):
                    continue

                msg = obj.get("message", {})
                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                text = _extract_text(msg.get("content", ""))
                if not text:
                    continue

                if not timestamp:
                    timestamp = obj.get("timestamp", "")

                messages.append({"role": role, "content": text})

        return {
            "session_id": filepath.stem,
            "timestamp": timestamp,
            "messages": messages,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _project_key(working_dir: str | Path) -> str:
        """Convert an absolute path to a Claude project key.

        Example: /data/lhc/RetroCode -> -data-lhc-RetroCode
        """
        return str(Path(working_dir).resolve()).replace("/", "-")

    @classmethod
    def _project_dir(cls, working_dir: str | Path) -> Path:
        return Path.home() / ".claude" / "projects" / cls._project_key(working_dir)


def _extract_text(content) -> str:
    """Extract plain text from a Claude message content field.

    Content may be:
      - a plain string
      - a list of blocks: {type: "text", text: "..."} | {type: "thinking", ...}
                          | {type: "tool_use", ...} | {type: "tool_result", ...}

    Only "text" blocks are included; tool calls and thinking are skipped.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return " ".join(p.strip() for p in parts if p.strip())
    return ""
