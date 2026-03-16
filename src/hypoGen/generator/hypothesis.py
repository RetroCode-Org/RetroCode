"""
Hypothesis definitions and helpers for Claude Code trace analysis.

A Hypothesis maps an "early-turn signal" (bool feature extracted from the first
portion of a session) to a predicted outcome.

  toxic=True:  feature=True  →  predicts PROBLEMATIC session
  toxic=False: feature=True  →  predicts SUCCESSFUL session

All feature_fn signatures: (msgs: list[dict]) -> bool

Each message dict has:
  role        str                 user / assistant / tool
  content     str                 text content
  name        str                 tool name (role=tool messages only)
  tool_names  list[str]           tools invoked (role=assistant only)
  tool_args   list[dict]          parsed args for each tool call
  char_len    int                 len(content)

Claude Code tools: Read, Edit, Write, Bash, Glob, Grep, Agent,
                   NotebookEdit, WebFetch, WebSearch, TaskCreate, TaskUpdate, etc.
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from typing import Callable


# -- helpers available to all feature functions --------------------------------

def _parse_args(ta) -> dict:
    """Parse tool arguments whether they arrive as a dict or a JSON string."""
    if isinstance(ta, dict):
        return ta
    try:
        return json.loads(ta) if ta else {}
    except Exception:
        return {}


def get_early_pct(msgs: list[dict], pct: float = 0.30) -> list[dict]:
    """Return messages from the first `pct` fraction of the session."""
    cutoff = max(1, int(len(msgs) * pct))
    return msgs[:cutoff]


def iter_tool_calls(msgs: list[dict]):
    """Yield (tool_name, args_dict) for every tool call in msgs."""
    for m in msgs:
        if m["role"] == "assistant":
            for tn, ta in zip(m.get("tool_names", []), m.get("tool_args", [])):
                yield tn, (_parse_args(ta) if not isinstance(ta, dict) else ta)


def iter_tool_results(msgs: list[dict]):
    """Yield (tool_name, content_str) for every tool result in msgs."""
    for m in msgs:
        if m["role"] == "tool":
            yield m.get("name", ""), m.get("content", "")


# -- Claude Code tool name constants ------------------------------------------

EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")
READ_TOOLS = ("Read",)
SEARCH_TOOLS = ("Glob", "Grep")
BASH_TOOL = "Bash"
AGENT_TOOL = "Agent"

ERROR_KWS = [
    "error:", "traceback", "exception", "failed",
    "command not found", "permission denied", "no such file",
]


# -- Hypothesis dataclass -----------------------------------------------------

@dataclass
class Hypothesis:
    id: str
    description: str
    feature_fn: Callable[[list[dict]], bool]
    toxic: bool = True   # True → signal predicts PROBLEMATIC; False → SUCCESSFUL
    code_src: str = ""   # Python source of the feature function (for export)

    # populated by verify()
    n_pos: int = 0            # sessions where feature = True
    n_neg: int = 0            # sessions where feature = False
    pass_rate_pos: float = 0.0
    pass_rate_neg: float = 0.0
    p_value: float = 1.0
    odds_ratio: float = 1.0
    or_ci_lo: float = 0.0
    or_ci_hi: float = 0.0

    @property
    def is_significant(self) -> bool:
        return self.p_value < 0.05

    def summary(self) -> str:
        sig = "SIGNIFICANT" if self.is_significant else "not significant"
        rej_when = (1 - self.pass_rate_pos) * 100 if self.n_pos else 0
        rej_base = (1 - self.pass_rate_neg) * 100 if self.n_neg else 0
        return (
            f"\n{'─' * 60}\n"
            f"  {self.id}  [{sig}]\n"
            f"  {self.description}\n"
            f"  When this fires: {rej_when:.0f}% rejected  ({self.n_pos} rounds)\n"
            f"  Baseline:        {rej_base:.0f}% rejected  ({self.n_neg} rounds)\n"
            f"  OR={self.odds_ratio:.2f} [{self.or_ci_lo:.2f}, {self.or_ci_hi:.2f}]   "
            f"p={self.p_value:.4f}"
        )


def _seed(fn, **kwargs) -> Hypothesis:
    return Hypothesis(
        id=fn.__name__.removeprefix("feat_"),
        description=(fn.__doc__ or "").strip().split("\n")[0],
        feature_fn=fn,
        code_src=inspect.getsource(fn),
        **kwargs,
    )
