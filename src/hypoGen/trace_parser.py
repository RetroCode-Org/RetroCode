"""
Parse Claude Code JSONL session traces into rounds.

A round = one human user message + all assistant/tool messages until
the next human user message.

Round dict:
    session_id   str
    round_id     str           "{session_id}:{round_num}"
    round_num    int
    user_msg     str           the triggering human message
    msgs         list[dict]    assistant + tool messages within this round
    next_user_msg str | None   the next human message (used for labeling)
    n_msgs       int

Each message in msgs:
    role        "assistant" | "tool"
    content     str
    tool_names  list[str]   (assistant only)
    tool_args   list[dict]  (assistant only)
    name        str          (tool only: which tool produced this result)
    char_len    int
"""
from __future__ import annotations

import json
from pathlib import Path


def parse_session(filepath: str | Path) -> list[dict]:
    """Parse a .jsonl file into a flat list of messages (assistant + tool + user).

    Used internally; most callers want parse_rounds().
    """
    filepath = Path(filepath)
    messages: list[dict] = []
    tool_id_to_name: dict[str, str] = {}

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
            if entry_type not in ("user", "assistant"):
                continue

            msg = obj.get("message", {})
            role = msg.get("role")
            content_raw = msg.get("content", "")

            if role == "assistant":
                text_parts, tool_names, tool_args = _parse_assistant_content(
                    content_raw, tool_id_to_name
                )
                text = " ".join(text_parts).strip()
                messages.append({
                    "role": "assistant",
                    "content": text,
                    "tool_names": tool_names,
                    "tool_args": tool_args,
                    "name": "",
                    "char_len": len(text),
                })

            elif role == "user":
                text_parts, tool_results = _parse_user_content(
                    content_raw, tool_id_to_name
                )
                for tr_name, tr_content in tool_results:
                    messages.append({
                        "role": "tool",
                        "content": tr_content,
                        "tool_names": [],
                        "tool_args": [],
                        "name": tr_name,
                        "char_len": len(tr_content),
                    })
                text = " ".join(text_parts).strip()
                if text:
                    messages.append({
                        "role": "user",
                        "content": text,
                        "tool_names": [],
                        "tool_args": [],
                        "name": "",
                        "char_len": len(text),
                    })

    return messages


def parse_rounds(filepath: str | Path) -> list[dict]:
    """Split a session into rounds.

    A round starts at each human user message and contains all
    subsequent assistant/tool messages until the next human user
    message (which becomes next_user_msg).

    Returns list of round dicts.
    """
    filepath = Path(filepath)
    session_id = filepath.stem
    all_msgs = parse_session(filepath)

    # Find indices of human user messages
    user_indices = [i for i, m in enumerate(all_msgs) if m["role"] == "user"]

    rounds: list[dict] = []
    for round_num, start in enumerate(user_indices):
        user_msg = all_msgs[start]["content"]

        # Messages within this round = everything after user_msg until next user_msg
        end = user_indices[round_num + 1] if round_num + 1 < len(user_indices) else len(all_msgs)
        round_msgs = all_msgs[start + 1 : end]

        next_user_msg = (
            all_msgs[user_indices[round_num + 1]]["content"]
            if round_num + 1 < len(user_indices)
            else None
        )

        rounds.append({
            "session_id": session_id,
            "round_id": f"{session_id}:{round_num}",
            "round_num": round_num,
            "user_msg": user_msg,
            "msgs": round_msgs,
            "next_user_msg": next_user_msg,
            "n_msgs": len(round_msgs),
        })

    return rounds


# ---------------------------------------------------------------------------
# Internal parsers
# ---------------------------------------------------------------------------

def _parse_assistant_content(
    content, tool_id_to_name: dict[str, str]
) -> tuple[list[str], list[str], list[dict]]:
    if isinstance(content, str):
        return [content], [], []
    text_parts: list[str] = []
    tool_names: list[str] = []
    tool_args: list[dict] = []
    if not isinstance(content, list):
        return text_parts, tool_names, tool_args
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            name = block.get("name", "")
            tool_names.append(name)
            tool_args.append(block.get("input", {}))
            tool_id = block.get("id", "")
            if tool_id:
                tool_id_to_name[tool_id] = name
    return text_parts, tool_names, tool_args


def _parse_user_content(
    content, tool_id_to_name: dict[str, str]
) -> tuple[list[str], list[tuple[str, str]]]:
    if isinstance(content, str):
        return [content], []
    text_parts: list[str] = []
    tool_results: list[tuple[str, str]] = []
    if not isinstance(content, list):
        return text_parts, tool_results
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_result":
            tool_use_id = block.get("tool_use_id", "")
            tool_name = tool_id_to_name.get(tool_use_id, "unknown")
            raw = block.get("content", "")
            if isinstance(raw, list):
                parts = []
                for sub in raw:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        parts.append(sub.get("text", ""))
                raw = "\n".join(parts)
            tool_results.append((tool_name, str(raw)))
    return text_parts, tool_results
