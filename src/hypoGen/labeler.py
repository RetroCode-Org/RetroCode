"""
Round-level outcome labeler.

A round is labeled 0.0 only when the next user message contains an
explicit rejection or correction — the user is clearly saying the AI
got something wrong.

Everything else (follow-up questions, new requests, clarifications)
is labeled 1.0. We only want to detect obviously bad rounds.
"""
from __future__ import annotations

import json
import re
from typing import Optional


# Explicit rejection / correction by the user
_REJECTION_RE = re.compile(
    r"(?:^|[\s,\.!?])"
    r"(no[,\s]|nope|wrong|incorrect|not right|not what i (want|asked|meant|said)"
    r"|that'?s (wrong|not|incorrect)|you (missed|forgot|broke|got it wrong)"
    r"|undo|revert|that didn'?t work|still (broken|wrong|not working|failing)"
    r"|this is (wrong|incorrect|not right|broken)|doesn'?t work|did not work"
    r"|not working|that'?s not (right|what|it|correct))"
    r"(?:[\s,\.!?]|$)",
    re.IGNORECASE,
)


def label_round(user_msg: str, next_user_msg: Optional[str]) -> tuple[float, str]:
    """Label a round based on the next user message.

    Returns (reward, reason):
        (0.0, "rejection")  — next message explicitly rejects/corrects the AI
        (1.0, "last_round") — no next message
        (1.0, "ok")         — next message is a question, new request, etc.
    """
    if next_user_msg is None:
        return 1.0, "last_round"

    # Strip Claude Code UI boilerplate injected into messages
    clean = re.sub(r"<[^>]+>[^<]*</[^>]+>", "", next_user_msg).strip()
    if not clean:
        return 1.0, "last_round"

    if _REJECTION_RE.search(clean):
        return 0.0, "rejection"

    return 1.0, "ok"


class LabelStore:
    """Persist round labels across runs in .retro/hypoGen/labeled_traces.json."""

    def __init__(self, path: str):
        self.path = path
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self):
        import os
        if os.path.exists(self.path):
            with open(self.path) as f:
                self._data = json.load(f)

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2)

    def get(self, round_id: str) -> Optional[float]:
        entry = self._data.get(round_id)
        return entry["reward"] if entry else None

    def set(self, round_id: str, reward: float, reason: str,
            user_msg: str = "", next_user_msg: Optional[str] = None):
        self._data[round_id] = {
            "reward": reward,
            "reason": reason,
            "user_msg": user_msg[:300],
            "next_user_msg": next_user_msg[:300] if next_user_msg else None,
        }

    def summary(self) -> str:
        total = len(self._data)
        n_pass = sum(1 for e in self._data.values() if e["reward"] == 1.0)
        n_fail = total - n_pass
        return f"{total} rounds labeled  ({n_pass} ok, {n_fail} rejected)"
