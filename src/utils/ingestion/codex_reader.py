"""
OpenAI Codex CLI trace reader.

Codex stores session traces at:
  ~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-<timestamp>-<uuid>.jsonl

Sessions are NOT organized by project — all projects share the same date tree.
We filter by matching the `cwd` field in the `session_meta` entry against the
working directory.

JSONL entry types we care about:
  session_meta        → cwd, session id, timestamp
  response_item       → role=user/assistant messages and function_call/function_call_output
  (everything else is ignored)

response_item payload types:
  message             → role in (user, assistant, developer); content list of {type, text}
  function_call       → name, arguments (tool call)
  function_call_output→ call_id, output (tool result)
"""

import json
import logging
from pathlib import Path

from .base import BaseReader, normalize_messages

logger = logging.getLogger(__name__)

_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"


class CodexReader(BaseReader):

    @property
    def tool_name(self) -> str:
        return "codex"

    def find_trace_files(self, working_dir: str | Path) -> list[Path]:
        """Return all Codex session files whose cwd matches working_dir."""
        working_dir = str(Path(working_dir).resolve())
        matched: list[Path] = []
        if not _SESSIONS_ROOT.is_dir():
            return matched
        for jsonl in sorted(_SESSIONS_ROOT.rglob("rollout-*.jsonl")):
            try:
                cwd = _read_cwd(jsonl)
                if cwd == working_dir:
                    matched.append(jsonl)
            except Exception:
                continue
        return matched

    def read_head_tail(self, filepath: Path, n: int = 5) -> tuple[list[str], list[str]]:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        head = [line.rstrip("\n") for line in lines[:n]]
        tail = [line.rstrip("\n") for line in lines[-n:]] if len(lines) > n else []
        return head, tail

    def parse_session(self, filepath: Path) -> dict:
        """Parse a Codex rollout JSONL into a session dict.

        Returns:
            session_id  – UUID from session_meta
            timestamp   – ISO timestamp from session_meta
            messages    – list of {role, content} dicts (user/assistant only)
        """
        session_id = filepath.stem
        timestamp = ""
        messages: list[dict] = []
        # map call_id -> tool_name for pairing function_call_output
        pending_calls: dict[str, str] = {}

        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = obj.get("type")
                payload = obj.get("payload", {})

                if entry_type == "session_meta":
                    session_id = payload.get("id", session_id)
                    timestamp = payload.get("timestamp", "")
                    continue

                if entry_type != "response_item":
                    continue

                item_type = payload.get("type")

                if item_type == "message":
                    role = payload.get("role", "")
                    if role not in ("user", "assistant"):
                        continue
                    text = _extract_text(payload.get("content", []))
                    if text:
                        messages.append({"role": role, "content": text})

                elif item_type == "function_call":
                    name = payload.get("name", "unknown")
                    call_id = payload.get("call_id", "")
                    args = payload.get("arguments", "")
                    if call_id:
                        pending_calls[call_id] = name
                    # Represent as an assistant tool-call message
                    messages.append({
                        "role": "assistant",
                        "content": f"[tool_call: {name}] {args}",
                        "tool_names": [name],
                        "tool_args": [_parse_args(args)],
                        "name": "",
                    })

                elif item_type == "function_call_output":
                    call_id = payload.get("call_id", "")
                    output = str(payload.get("output", ""))
                    tool_name = pending_calls.pop(call_id, "unknown")
                    messages.append({
                        "role": "tool",
                        "content": output,
                        "tool_names": [],
                        "tool_args": [],
                        "name": tool_name,
                    })

        # Normalize Codex-specific tool names to canonical names
        normalize_messages(messages)

        return {
            "session_id": session_id,
            "timestamp": timestamp,
            "messages": messages,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_cwd(filepath: Path) -> str:
    """Read only the first session_meta entry to get cwd without parsing the whole file."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "session_meta":
                return obj.get("payload", {}).get("cwd", "")
    return ""


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("text")
        ]
        return " ".join(p.strip() for p in parts if p.strip())
    return ""


def _parse_args(args) -> dict:
    if isinstance(args, dict):
        return args
    try:
        return json.loads(args) if args else {}
    except Exception:
        return {}
