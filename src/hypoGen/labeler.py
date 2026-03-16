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


# ── Explicit rejection / correction by the user ──────────────────────────
#
# These patterns fire when the NEXT user message tells the agent it
# got something wrong, undid something, or the result didn't work.

_REJECTION_RE = re.compile(
    r"(?:^|[\s,\.!?;:\-])"
    r"("
    # Direct negations
    r"no[,\.\s!]|nope|wrong|incorrect|not right"
    r"|not what i (want|asked|meant|said|need)"
    # Explicit corrections
    r"|that'?s (wrong|not|incorrect|broken|bad)"
    r"|you (missed|forgot|broke|got it wrong|shouldn'?t|should not)"
    # Undo / revert requests
    r"|undo|revert|roll ?back|put it back|restore"
    # Failure reports
    r"|that didn'?t work|still (broken|wrong|not working|failing|doesn)"
    r"|this is (wrong|incorrect|not right|broken)"
    r"|doesn'?t work|did not work|not working|isn'?t (right|correct|working)"
    r"|that'?s not (right|what|it|correct)"
    # Frustration / stop signals
    r"|stop|wait|hold on|don'?t do that|why did you"
    r"|i (said|asked|told you|meant) (not|no|don)"
    r"|that'?s the opposite"
    # Claude Code specific: permission denial / interrupt
    r"|request interrupted"
    r")"
    r"(?:[\s,\.!?;:\-]|$)",
    re.IGNORECASE,
)

# Messages that look like rejections but are actually just new requests
_FALSE_POSITIVE_RE = re.compile(
    r"("
    r"no (need|worries|problem|rush|pressure|thanks|thank)"
    r"|not (sure|yet|now|necessarily|a big deal)"
    r"|stop (the|and|here|it from|running)"  # "stop the server" is not rejection
    r"|wait (for|until|a moment)"
    r"|no i (mean|think|was)"  # clarification, not rejection
    r"|hold on (let me|i need)"  # thinking pause, not rejection
    r")",
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

    # Check for false positives first
    if _FALSE_POSITIVE_RE.search(clean):
        return 1.0, "ok"

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
