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
    reward = row.get("reward", "?")
    label = "REJECTED" if reward == 0.0 else "OK"

    lines = [
        f"ROUND  reward={reward} ({label})  n_msgs={row.get('n_msgs', len(msgs))}"
    ]

    # Show what the user asked (context for understanding rejection)
    user_msg = row.get("user_msg", "")
    if user_msg:
        lines.append(f"  USER REQUEST: {user_msg[:200].replace(chr(10), ' ')!r}")

    for i, m in enumerate(msgs[:30]):  # cap at 30 messages for context window
        role = m["role"]
        snippet = m["content"][:200].replace("\n", " ").strip()
        tool_names = m.get("tool_names", [])
        tool_args = m.get("tool_args", [])
        if role == "assistant" and tool_names:
            tool_str = ", ".join(
                f"{tn}({', '.join(f'{k}={str(v)[:40]}' for k, v in (ta if isinstance(ta, dict) else {}).items() if k != 'content')})"
                for tn, ta in zip(tool_names, tool_args)
            )
            lines.append(f"  [{i:03d}] assistant -> [{tool_str}]")
            if snippet and not tool_names:
                lines.append(f"         text: {snippet!r:.120}")
        elif role == "user":
            lines.append(f"  [{i:03d}] user  {snippet!r:.120}")
        elif role == "tool":
            # Show error indicators in tool results
            is_err = any(kw in snippet.lower() for kw in ("error", "traceback", "failed"))
            err_mark = " [ERROR]" if is_err else ""
            lines.append(f"  [{i:03d}] tool({m.get('name', '?')}){err_mark}  {snippet!r:.120}")

    if len(msgs) > 30:
        lines.append(f"  ... ({len(msgs) - 30} more messages)")

    # Show what the user said NEXT (the rejection or acceptance)
    next_msg = row.get("next_user_msg", "")
    if next_msg:
        lines.append(f"  NEXT USER MSG: {next_msg[:200].replace(chr(10), ' ')!r}")

    return "\n".join(lines)


# -- system prompt -------------------------------------------------------------

_SYSTEM = textwrap.dedent("""\
You are an expert in analyzing Claude Code agent traces to understand
why users reject AI-generated work.

=== CONTEXT ===
A user works with Claude Code (an AI coding assistant) for days. Sometimes
the user says "No" / "that's wrong" / "undo" after the agent does something.
We want to find patterns that predict WHEN the user will say no.

Each ROUND = one user request + all the assistant/tool messages that follow.
  reward=1.0  the user accepted the work (or moved on to a new topic)
  reward=0.0  the user REJECTED the work ("no", "wrong", "undo", "doesn't work")

=== YOUR TASK ===
Propose hypotheses about agent behavior patterns. Two kinds:
  TOXIC:   "If the agent does X, the user is more likely to reject."
  HEALTHY: "If the agent does X, the user is more likely to accept."

Good hypotheses are:
  - SIMPLE: one clear condition, easy to check programmatically
  - INFORMATIONAL: tells the user something useful about when agents fail or succeed
  - CONTRIBUTABLE: other users can verify on their own traces
  - DIVERSE: cover different aspects (tool ordering, error handling, scale, workflow)

Bad hypotheses:
  - Too broad ("agent used any tool") — fires too often, no signal
  - Too narrow ("agent edited file X") — only applies to one project
  - Trivial ("agent produced output") — not informative

=== MESSAGE SCHEMA ===
msgs = messages within ONE round (assistant + tool, no user messages):
  role       : "assistant" | "tool"
  content    : str
  name       : str         (tool name, when role=="tool")
  tool_names : list[str]   (tools called, when role=="assistant")
  tool_args  : list[dict]  (input dicts, when role=="assistant")
  char_len   : int

Iterating:
  for tn, args in iter_tool_calls(msgs):   # yields (tool_name, args_dict)
  for name, content in iter_tool_results(msgs):  # yields (tool_name, output_str)

Tool arg keys:
  Bash:  args.get("command", "")
  Read:  args.get("file_path", "")
  Edit:  args.get("file_path", ""), args.get("old_string", ""), args.get("new_string", "")
  Write: args.get("file_path", ""), args.get("content", "")
  Glob:  args.get("pattern", "")
  Grep:  args.get("pattern", "")

Constants: EDIT_TOOLS, READ_TOOLS, SEARCH_TOOLS, BASH_TOOL, AGENT_TOOL, ERROR_KWS

=== RULES ===
  1. Use msgs directly — do NOT call get_early_pct.
  2. Return True (signal present) or False.
  3. Focus on agent BEHAVIOR patterns, not specific file names or content.

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
Below are REJECTED rounds (user explicitly said "no" or corrected the agent),
then OK rounds (user accepted or moved on).

Study the differences. What did the agent DO in rejected rounds that it
didn't do in OK rounds?

=== REJECTED ROUNDS ===
{fail_block}

=== OK ROUNDS ===
{pass_block}

Already known hypotheses (do NOT duplicate): {existing}

Propose 3 NEW hypotheses. Include at least one TOXIC (predicts rejection) and
one HEALTHY (predicts acceptance). Each should be:
- Simple: one clear condition about agent behavior
- Different from each other (don't propose variations of the same idea)
- Testable: a Python function that checks msgs and returns True/False

For each, output a JSON object:
  "id"          short snake_case name
  "description" one sentence starting with "[TOXIC] Agent ..." or "[HEALTHY] Agent ..."
  "toxic"       true if signal predicts rejection, false if it predicts acceptance
  "code"        Python function BODY (no def line). Variable `msgs` is available.
                Use iter_tool_calls(msgs) and iter_tool_results(msgs).
                Must return bool. Do NOT use get_early_pct.

Output ONLY a JSON array of 3 objects, nothing else.
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

    if not code or not code.strip():
        print(f"  [propose] empty code for hypothesis '{hid}'")
        return None

    # Normalize: strip markdown fences
    code = re.sub(r"^```(?:python)?\n?", "", code.strip())
    code = re.sub(r"\n?```$", "", code.strip())

    # If code is a bare body (no def line), wrap it
    if not code.lstrip().startswith("def "):
        # Ensure the body has a return statement
        lines = code.strip().split("\n")
        has_return = any(l.strip().startswith("return ") for l in lines)
        if not has_return:
            # Last line might be an expression — wrap as return
            last = lines[-1].strip()
            if last and not last.startswith(("#", "if ", "for ", "while ")):
                lines[-1] = f"return {last}"
        indented = textwrap.indent(textwrap.dedent("\n".join(lines)), "    ")
        src = f"def _feature(msgs):\n{indented}\n"
    else:
        src = textwrap.dedent(code)

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
        # Smoke test: must handle empty msgs without crashing
        result = fn([])
        if not isinstance(result, bool):
            result = bool(result)  # coerce to bool
    except Exception as e:
        print(f"  [propose] failed to compile hypothesis '{hid}': {e}")
        traceback.print_exc()
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
    seen_ids = set(existing_ids or [])
    for obj in objects:
        h = _build_hypothesis(obj)
        if h is None:
            continue
        # Deduplicate by ID (exact or suffix match)
        if h.id in seen_ids or any(h.id.endswith(eid) or eid.endswith(h.id) for eid in seen_ids):
            print(f"  [propose] skip '{h.id}': duplicate of existing hypothesis")
            continue
        seen_ids.add(h.id)
        hypotheses.append(h)
        direction = "toxic" if h.toxic else "healthy"
        print(f"  [propose] ok  '{h.id}' ({direction}): {h.description}")
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
