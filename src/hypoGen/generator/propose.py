"""
LLM-based hypothesis proposer and refiner for Claude Code traces.

Uses the project's inference providers to:
  1. propose_new()  — read sample traces, generate novel hypotheses
  2. refine()       — given a weak hypothesis + counterexamples, tighten the rule
"""
from __future__ import annotations

import json
import re
import textwrap
import traceback
from typing import Any

from src.utils.inference import call_llm, parse_json_response
from src.hypoGen.generator.hypothesis import (
    Hypothesis, iter_tool_calls, iter_tool_results,
    _parse_args, EDIT_TOOLS, READ_TOOLS, SEARCH_TOOLS, BASH_TOOL, AGENT_TOOL,
    ERROR_KWS,
)


# helpers injected into the exec sandbox
_SANDBOX_GLOBALS = {
    "json": json,
    "re": re,
    "iter_tool_calls": iter_tool_calls,
    "iter_tool_results": iter_tool_results,
    "_parse_args": _parse_args,
    "EDIT_TOOLS": EDIT_TOOLS,
    "READ_TOOLS": READ_TOOLS,
    "SEARCH_TOOLS": SEARCH_TOOLS,
    "BASH_TOOL": BASH_TOOL,
    "AGENT_TOOL": AGENT_TOOL,
    "ERROR_KWS": ERROR_KWS,
}


# -- trace formatter -----------------------------------------------------------

def format_trace(row: dict[str, Any]) -> str:
    """Compact, LLM-readable representation of a round."""
    msgs = row["msgs"]
    lines = [
        f"ROUND  id={row['session_id']}  reward={row['reward']}  "
        f"({'OK' if row['reward'] == 1.0 else 'REJECTED'})  "
        f"n_msgs={row['n_msgs']}"
    ]
    for i, m in enumerate(msgs):
        role = m["role"]
        snippet = m["content"][:150].replace("\n", " ").strip()
        tool_names = m.get("tool_names", [])
        tool_args = m.get("tool_args", [])
        if role == "assistant" and tool_names:
            tool_str = ", ".join(
                f"{tn}({list(ta.keys())[:2]})" if isinstance(ta, dict) else tn
                for tn, ta in zip(tool_names, tool_args)
            )
            lines.append(f"  [{i:03d}] assistant -> [{tool_str}]")
        elif role == "user":
            lines.append(f"  [{i:03d}] user  {snippet!r:.120}")
        elif role == "tool":
            lines.append(f"  [{i:03d}] tool({m.get('name', '?')})  {snippet!r:.120}")
    return "\n".join(lines)


# -- system prompt -------------------------------------------------------------

_SYSTEM = textwrap.dedent("""\
You are an expert in analyzing Claude Code agent round traces.

Each ROUND is one user request + all the assistant/tool messages that follow.
A round is labeled:
  reward=1.0  the next user message is OK (question, new request, etc.)
  reward=0.0  the next user message EXPLICITLY rejects the work
              (e.g. "No, that's wrong", "undo this", "that didn't work")

You will propose hypotheses of the form:
  "If the agent does X in this round, the user is more likely to reject it."

The goal: detect patterns within a round that predict the user will say "no".

Claude Code tools: Read, Edit, Write, Bash, Glob, Grep, Agent, WebSearch

=== MESSAGE SCHEMA ===
msgs = all messages within ONE round (assistant + tool messages):
  role       : "assistant" | "tool"
  content    : str
  name       : str         (tool name, when role=="tool")
  tool_names : list[str]   (tools called, when role=="assistant")
  tool_args  : list[dict]  (input dicts, when role=="assistant")
  char_len   : int

How to iterate tool calls in the round:
  for tn, args in iter_tool_calls(msgs):
      if tn == "Bash":   cmd  = args.get("command", "")
      if tn == "Read":   path = args.get("file_path", "")
      if tn == "Edit":   path = args.get("file_path", "")
      if tn == "Glob":   pat  = args.get("pattern", "")
      if tn == "Grep":   pat  = args.get("pattern", "")

How to iterate tool results:
  for name, content in iter_tool_results(msgs):
      if name == "Bash":  # stdout/stderr

Constants:
  EDIT_TOOLS   = ("Edit", "Write", "NotebookEdit")
  READ_TOOLS   = ("Read",)
  SEARCH_TOOLS = ("Glob", "Grep")
  BASH_TOOL    = "Bash"
  ERROR_KWS    = ["error:", "traceback", "exception", "failed", ...]

=== RULES ===
  1. Use msgs directly — do NOT call get_early_pct (msgs is already one round).
  2. Return a concrete bool (True/False).
  3. Prefer patterns that indicate the AI is acting carelessly or without understanding.

Available: json, re, iter_tool_calls, iter_tool_results,
  _parse_args, EDIT_TOOLS, READ_TOOLS, SEARCH_TOOLS, BASH_TOOL, AGENT_TOOL, ERROR_KWS
""")


# -- proposal prompt -----------------------------------------------------------

def _proposal_prompt(fail_traces: list[str], pass_traces: list[str],
                     existing_ids: list[str]) -> str:
    existing = ", ".join(existing_ids) if existing_ids else "none"
    fail_block = "\n\n".join(fail_traces)
    pass_block = "\n\n".join(pass_traces)
    return textwrap.dedent(f"""\
Below are REJECTED rounds (user explicitly said "no" / "that's wrong" after this round),
then OK rounds (user accepted or continued with a new request).

=== REJECTED ROUNDS ===
{fail_block}

=== OK ROUNDS ===
{pass_block}

Already known hypotheses (do NOT duplicate): {existing}

Propose 3 NEW hypotheses about patterns within a round that predict rejection.
For each output a JSON object with:
  "id"          snake_case identifier
  "description" one sentence: "If agent does X in this round, user is more likely to reject it"
  "toxic"       true (signal predicts rejection)
  "code"        Python function BODY ONLY (no def line). msgs = messages in this round.
                Do NOT use get_early_pct. Use msgs directly.
                Must return True (signal present) or False.

Output ONLY a JSON array of these objects, nothing else.
""")


# -- refinement prompt ---------------------------------------------------------

def _refine_prompt(hyp: Hypothesis, wrong_examples: list[str]) -> str:
    examples_block = "\n\n".join(wrong_examples)
    return textwrap.dedent(f"""\
The following hypothesis was NOT statistically significant:

  id: {hyp.id}
  description: {hyp.description}
  toxic: {hyp.toxic}
  p-value: {hyp.p_value:.4f}

Here are rounds where the hypothesis made the WRONG prediction:

{examples_block}

Propose a single REFINED hypothesis that fixes the weakness.
Output ONE JSON object with keys: "id", "description", "toxic", "code".
The "code" field: Python function body (no def line), msgs is one round.
Do NOT call get_early_pct. Use msgs directly.
Output ONLY the JSON object, nothing else.
""")


# -- parse LLM output ---------------------------------------------------------

def _parse_response(text: str) -> list[dict]:
    """Extract and parse the JSON array (or single object) from LLM response."""
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("```").strip()
    m = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if m:
        text = m.group(1)
    parsed = json.loads(text)
    if isinstance(parsed, dict):
        parsed = [parsed]
    return parsed


def _build_hypothesis(obj: dict) -> Hypothesis | None:
    """Compile LLM-generated code into a Hypothesis, or return None on error."""
    hid = obj.get("id", "llm_hyp")
    desc = obj.get("description", "")
    toxic = bool(obj.get("toxic", True))
    code = obj.get("code", "")

    if not code.lstrip().startswith("def "):
        indented = textwrap.indent(textwrap.dedent(code), "    ")
        src = f"def _feature(msgs):\n{indented}\n"
    else:
        src = code

    ns = dict(_SANDBOX_GLOBALS)
    try:
        exec(compile(src, f"<hyp:{hid}>", "exec"), ns)  # noqa: S102
        fn = ns.get("_feature") or ns.get("feature")
        if fn is None:
            # Try last callable in namespace
            for v in reversed(list(ns.values())):
                if callable(v) and not isinstance(v, type):
                    fn = v
                    break
        if not callable(fn):
            raise ValueError("No callable found after exec")
        fn([])  # smoke test
    except Exception as e:
        print(f"  [propose] failed to compile hypothesis '{hid}': {e}")
        return None

    return Hypothesis(id=hid, description=desc, feature_fn=fn, toxic=toxic, code_src=src)


# -- public API ----------------------------------------------------------------

def propose_new(
    sample_rows: list[dict[str, Any]],
    n_fail: int = 4,
    n_pass: int = 4,
    existing_ids: list[str] | None = None,
) -> list[Hypothesis]:
    """Ask LLM to propose new hypotheses by reading sample traces."""
    fails = [r for r in sample_rows if r["reward"] == 0.0][:n_fail]
    passes = [r for r in sample_rows if r["reward"] == 1.0][:n_pass]

    if not fails or not passes:
        print("  [propose] not enough pass/fail examples in sample.")
        return []

    prompt = _proposal_prompt(
        [format_trace(r) for r in fails],
        [format_trace(r) for r in passes],
        existing_ids or [],
    )

    print("  [propose] calling LLM ...")
    text = call_llm(_SYSTEM, prompt, max_tokens=2048)
    print(f"  [propose] raw response ({len(text)} chars):\n{text[:600]}\n...")

    try:
        objects = _parse_response(text)
    except Exception as e:
        print(f"  [propose] JSON parse failed: {e}\nRaw:\n{text}")
        return []

    hypotheses = []
    for obj in objects:
        h = _build_hypothesis(obj)
        if h:
            hypotheses.append(h)
            print(f"  [propose] ok  '{h.id}': {h.description}")
    return hypotheses


def refine(
    hyp: Hypothesis,
    all_rows: list[dict[str, Any]],
    n_wrong: int = 4,
) -> Hypothesis | None:
    """Ask LLM to refine a weak hypothesis using counterexamples."""
    wrong = []
    for row in all_rows:
        try:
            feat = hyp.feature_fn(row["msgs"])
        except Exception:
            feat = False
        if hyp.toxic:
            is_wrong = (feat and row["reward"] == 1.0) or (not feat and row["reward"] == 0.0)
        else:
            is_wrong = (feat and row["reward"] == 0.0) or (not feat and row["reward"] == 1.0)
        if is_wrong:
            wrong.append(row)
        if len(wrong) >= n_wrong:
            break

    if not wrong:
        print(f"  [refine] no counterexamples found for '{hyp.id}'")
        return None

    prompt = _refine_prompt(hyp, [format_trace(r) for r in wrong])

    print(f"  [refine] calling LLM for '{hyp.id}' ...")
    text = call_llm(_SYSTEM, prompt, max_tokens=1024)
    print(f"  [refine] raw response:\n{text[:400]}\n...")

    try:
        objects = _parse_response(text)
        obj = objects[0]
        obj["id"] = hyp.id + "_v2"
        h = _build_hypothesis(obj)
        if h:
            print(f"  [refine] ok  refined as '{h.id}': {h.description}")
        return h
    except Exception as e:
        print(f"  [refine] failed: {e}")
        return None
