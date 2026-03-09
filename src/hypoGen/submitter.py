"""
Interactive hypothesis reviewer and PR submitter.

Usage:
    retro --submit --dir .

Flow:
  1. Load results.json from .retro/hypoGen/ — only significant hypotheses shown
  2. User picks which to submit (comma-separated numbers, or 'a' for all)
  3. Clone/fork RetroCode-Org/swe-hypotheses, write files, open PR

Files written per submission:
  hypotheses/<id>.md          — stats + feature function
  hypotheses/<id>.py          — standalone runnable Python program
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path


TARGET_REPO = "RetroCode-Org/swe-hypotheses"
TARGET_REPO_URL = f"https://github.com/{TARGET_REPO}"

_HELPERS = """\
import json, re
from typing import Iterator


EDIT_TOOLS   = ("Edit", "Write", "NotebookEdit")
READ_TOOLS   = ("Read",)
SEARCH_TOOLS = ("Glob", "Grep")
BASH_TOOL    = "Bash"
AGENT_TOOL   = "Agent"
ERROR_KWS    = ["error:", "traceback", "exception", "failed", "errno",
                "no such file", "command not found", "syntax error"]


def iter_tool_calls(msgs: list[dict]) -> Iterator[tuple[str, dict]]:
    for m in msgs:
        if m.get("role") == "assistant":
            for tn, ta in zip(m.get("tool_names", []), m.get("tool_args", [])):
                yield tn, (ta if isinstance(ta, dict) else (json.loads(ta) if ta else {}))


def iter_tool_results(msgs: list[dict]) -> Iterator[tuple[str, str]]:
    for m in msgs:
        if m.get("role") == "tool":
            yield m.get("name", ""), m.get("content", "")
"""


def run_submit(working_dir: str, retro_dir: Path) -> None:
    hypo_dir = retro_dir / "hypoGen"
    results_path = hypo_dir / "results.json"
    features_path = hypo_dir / "results_features.py"

    if not results_path.exists():
        print("[retro] No results found. Run `retro --hypogen --dir .` first.")
        return

    hypotheses = json.loads(results_path.read_text())
    feature_src = features_path.read_text() if features_path.exists() else ""

    sig = [h for h in hypotheses if h["significant"]]

    print("\n" + "=" * 60)
    print("  HYPOTHESIS REVIEW — significant only")
    print("=" * 60)

    if not sig:
        print("\n  No significant hypotheses yet.")
        print("  Run `retro --hypogen --dir .` with more trace data.\n")
        return

    print(f"\n{len(sig)} significant hypothesis(es):\n")
    for idx, h in enumerate(sig, 1):
        n_rej_T = round(h["n_pos"] * (1 - h["pass_rate_pos"]))
        n_rej_F = round(h["n_neg"] * (1 - h["pass_rate_neg"]))
        desc = re.sub(r"^\[(TOXIC|HEALTHY)\] ", "", h["description"]).strip()
        print(f"  [{idx}] {h['id']}")
        print(f"      {desc}")
        print(f"      signal=T: {h['n_pos']} rounds, {n_rej_T} rejected")
        print(f"      signal=F: {h['n_neg']} rounds, {n_rej_F} rejected")
        print(f"      OR={h['odds_ratio']:.2f}  p={h['p_value']:.4f}\n")

    print("-" * 60)
    print("Enter numbers to submit (e.g. 1,3), 'a' for all, or 'q' to quit:")
    try:
        raw = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[retro] Aborted.")
        return

    if raw.lower() == "q":
        print("[retro] Aborted.")
        return

    if raw.lower() == "a":
        selected = sig
    else:
        try:
            indices = [int(x.strip()) - 1 for x in raw.split(",")]
            selected = [sig[i] for i in indices if 0 <= i < len(sig)]
        except ValueError:
            print("[retro] Invalid input.")
            return

    if not selected:
        print("[retro] Nothing selected.")
        return

    print(f"\n[retro] Selected: {', '.join(h['id'] for h in selected)}")

    if not shutil.which("gh"):
        print("\n[retro] `gh` CLI not found. Install from https://cli.github.com/")
        _print_manual_instructions(selected, feature_src)
        return

    result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if result.returncode != 0:
        print("\n[retro] Not authenticated. Run: gh auth login")
        _print_manual_instructions(selected, feature_src)
        return

    _open_pr(selected, feature_src)


def _check_existing_hypotheses(selected: list[dict]) -> list[str]:
    """Check which hypothesis IDs already exist in the community repo."""
    import urllib.request, urllib.error
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{TARGET_REPO}/contents/hypotheses",
            headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "RetroCode"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            entries = json.loads(resp.read())
        existing = {e["name"][:-3] for e in entries if e["name"].endswith(".md")}
        return [h["id"] for h in selected if h["id"] in existing]
    except Exception:
        return []  # can't check, proceed anyway


def _open_pr(selected: list[dict], feature_src: str) -> None:
    # Get authenticated username early
    whoami = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                            capture_output=True, text=True)
    gh_user = whoami.stdout.strip()
    if not gh_user:
        print("[retro] Could not determine GitHub username. Run: gh auth login")
        _print_manual_instructions(selected, feature_src)
        return

    # Check for duplicates in the community repo
    duplicates = _check_existing_hypotheses(selected)
    if duplicates:
        print(f"\n[retro] These hypotheses already exist in the community repo: {', '.join(duplicates)}")
        print(f"[retro] Use `retro --pull` + `retro --contribute` to add your verification stats instead.")
        selected = [h for h in selected if h["id"] not in duplicates]
        if not selected:
            return

    # Unique branch name: username + hypothesis IDs + short hash
    ids_str = "--".join(h["id"][:20] for h in selected[:3])
    short_hash = hashlib.sha256(f"{gh_user}-{ids_str}-{date.today().isoformat()}".encode()).hexdigest()[:6]
    branch = f"hypo-{gh_user}-{ids_str}-{short_hash}"
    branch = re.sub(r"[^a-zA-Z0-9_-]", "-", branch)[:72]

    with tempfile.TemporaryDirectory() as tmpdir:
        # --- Fork (idempotent: already-forked is fine) ---
        print(f"\n[retro] Forking {TARGET_REPO} ...")
        subprocess.run(
            ["gh", "repo", "fork", TARGET_REPO, "--clone=false"],
            cwd=tmpdir, capture_output=True, text=True
        )  # ignore return code — already-forked is not an error

        fork_slug = f"{gh_user}/{TARGET_REPO.split('/')[1]}"

        # --- Clone the fork ---
        print(f"[retro] Cloning fork {fork_slug} ...")
        r = subprocess.run(
            ["gh", "repo", "clone", fork_slug],
            cwd=tmpdir, capture_output=True, text=True
        )
        repo_name = TARGET_REPO.split("/")[1]
        repo_dir = Path(tmpdir) / repo_name
        if not repo_dir.exists():
            # gh clones into the repo name; try alternate dir listing
            dirs = [d for d in Path(tmpdir).iterdir() if d.is_dir()]
            repo_dir = dirs[0] if dirs else None
        if not repo_dir or not repo_dir.exists():
            print(f"[retro] Clone failed:\n{r.stderr}\n{r.stdout}")
            _print_manual_instructions(selected, feature_src)
            return

        # Ensure upstream remote exists for PR base
        subprocess.run(
            ["git", "remote", "add", "upstream", f"https://github.com/{TARGET_REPO}.git"],
            cwd=repo_dir, capture_output=True, text=True
        )  # ignore if already exists

        # --- Write files ---
        readme = repo_dir / "README.md"
        if not readme.exists():
            readme.write_text(_repo_readme())

        hyp_dir = repo_dir / "hypotheses"
        hyp_dir.mkdir(exist_ok=True)

        for h in selected:
            code = _extract_feature_fn(h["id"], feature_src)
            (hyp_dir / f"{h['id']}.md").write_text(_format_md(h, code))
            (hyp_dir / f"{h['id']}.py").write_text(_format_py(h, code))
            print(f"[retro] Wrote hypotheses/{h['id']}.md + .py")

        # --- Commit ---
        # Check out branch (delete existing remote branch if needed)
        subprocess.run(["git", "checkout", "-b", branch],
                       cwd=repo_dir, capture_output=True, text=True)
        # If branch already existed locally, just switch
        if subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                          cwd=repo_dir, capture_output=True, text=True).stdout.strip() != branch:
            subprocess.run(["git", "checkout", branch], cwd=repo_dir, check=True)

        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        names = ", ".join(h["id"] for h in selected)

        # Only commit if there are staged changes
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"],
                              cwd=repo_dir, capture_output=True)
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-m", f"Add hypothesis: {names}"],
                           cwd=repo_dir, check=True)
        else:
            print("[retro] No changes to commit (files already exist in fork).")

        # --- Push ---
        print(f"[retro] Pushing branch {branch} to fork ...")
        r = subprocess.run(
            ["git", "push", "origin", branch, "--force-with-lease"],
            cwd=repo_dir, capture_output=True, text=True
        )
        if r.returncode != 0:
            # Force push if --force-with-lease fails (new branch)
            r = subprocess.run(
                ["git", "push", "origin", branch, "--force"],
                cwd=repo_dir, capture_output=True, text=True
            )
        if r.returncode != 0:
            print(f"[retro] Push failed:\n{r.stderr}")
            _print_manual_instructions(selected, feature_src)
            return

        # --- Open PR ---
        head_flag = f"{gh_user}:{branch}"
        r = subprocess.run(
            ["gh", "pr", "create",
             "--repo", TARGET_REPO,
             "--head", head_flag,
             "--base", "main",
             "--title", f"Add hypothesis: {names}",
             "--body", _pr_body(selected)],
            cwd=repo_dir, capture_output=True, text=True
        )
        if r.returncode == 0:
            print(f"\n[retro] PR created: {r.stdout.strip()}")
        else:
            # PR may already exist
            if "already exists" in r.stderr or "already exists" in r.stdout:
                print(f"\n[retro] PR already exists for this branch.")
                existing = subprocess.run(
                    ["gh", "pr", "view", "--repo", TARGET_REPO, "--head", head_flag, "--json", "url", "--jq", ".url"],
                    cwd=repo_dir, capture_output=True, text=True
                )
                if existing.stdout.strip():
                    print(f"[retro] Existing PR: {existing.stdout.strip()}")
            else:
                print(f"[retro] PR creation failed:\n{r.stderr}")
                print(f"[retro] Branch pushed. Open PR manually at {TARGET_REPO_URL}")


def _format_md(h: dict, code: str) -> str:
    n_rej_T = round(h["n_pos"] * (1 - h["pass_rate_pos"]))
    n_rej_F = round(h["n_neg"] * (1 - h["pass_rate_neg"]))
    desc = re.sub(r"^\[(TOXIC|HEALTHY)\] ", "", h["description"]).strip()
    return f"""\
---
id: {h['id']}
description: "{desc}"
toxic: {str(h['toxic']).lower()}
n_rounds_signal: {h['n_pos']}
n_rejected_signal: {n_rej_T}
n_rounds_no_signal: {h['n_neg']}
n_rejected_no_signal: {n_rej_F}
odds_ratio: {h['odds_ratio']}
or_ci: {h['or_ci']}
p_value: {h['p_value']}
---

## Description

{desc}

**Signal predicts:** {"problematic round (user rejection)" if h['toxic'] else "successful round"}

## Statistics

| Metric | Value |
|---|---|
| Rounds with signal | {h['n_pos']} |
| Rejected (signal=T) | {n_rej_T} |
| Rounds without signal | {h['n_neg']} |
| Rejected (signal=F) | {n_rej_F} |
| Odds ratio | {h['odds_ratio']:.4f} [{h['or_ci'][0]:.4f}, {h['or_ci'][1]:.4f}] |
| p-value | {h['p_value']:.6f} |

## Feature function

```python
{code.strip()}
```
"""


def _format_py(h: dict, code: str) -> str:
    desc = re.sub(r"^\[(TOXIC|HEALTHY)\] ", "", h["description"]).strip()
    n_rej_T = round(h["n_pos"] * (1 - h["pass_rate_pos"]))
    n_rej_F = round(h["n_neg"] * (1 - h["pass_rate_neg"]))
    return f'''\
"""
Hypothesis: {h['id']}
{desc}

Verified statistics:
  Rounds with signal:    {h['n_pos']} ({n_rej_T} rejected)
  Rounds without signal: {h['n_neg']} ({n_rej_F} rejected)
  Odds ratio: {h['odds_ratio']:.4f} [{h['or_ci'][0]:.4f}, {h['or_ci'][1]:.4f}]
  p-value: {h['p_value']:.6f}

Usage:
  python {h['id']}.py --traces ~/.claude/projects/<key>
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Rejection detector (same regex as RetroCode labeler)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------

{_HELPERS}

def parse_rounds(filepath: Path) -> list[dict]:
    """Parse a Claude Code .jsonl trace into rounds."""
    import json as _json
    tool_id_to_name: dict[str, str] = {{}}
    messages: list[dict] = []

    with open(filepath, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
            except Exception:
                continue
            if obj.get("type") not in ("user", "assistant"):
                continue
            msg = obj.get("message", {{}})
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "assistant":
                text_parts, tool_names, tool_args = [], [], []
                if isinstance(content, list):
                    for b in content:
                        if b.get("type") == "text":
                            text_parts.append(b.get("text", ""))
                        elif b.get("type") == "tool_use":
                            tool_names.append(b.get("name", ""))
                            tool_args.append(b.get("input", {{}}))
                            if b.get("id"):
                                tool_id_to_name[b["id"]] = b.get("name", "")
                else:
                    text_parts = [str(content)]
                messages.append({{"role": "assistant", "content": " ".join(text_parts),
                                  "tool_names": tool_names, "tool_args": tool_args, "name": ""}})
            elif role == "user":
                tool_results, text_parts = [], []
                if isinstance(content, list):
                    for b in content:
                        if b.get("type") == "text":
                            text_parts.append(b.get("text", ""))
                        elif b.get("type") == "tool_result":
                            tname = tool_id_to_name.get(b.get("tool_use_id", ""), "unknown")
                            raw = b.get("content", "")
                            if isinstance(raw, list):
                                raw = "\n".join(s.get("text","") for s in raw if isinstance(s,dict))
                            tool_results.append((tname, str(raw)))
                else:
                    text_parts = [str(content)]
                for tname, tcontent in tool_results:
                    messages.append({{"role": "tool", "content": tcontent,
                                      "tool_names": [], "tool_args": [], "name": tname}})
                text = " ".join(text_parts).strip()
                if text:
                    messages.append({{"role": "user", "content": text,
                                      "tool_names": [], "tool_args": [], "name": ""}})

    user_idx = [i for i, m in enumerate(messages) if m["role"] == "user"]
    rounds = []
    for rn, start in enumerate(user_idx):
        end = user_idx[rn + 1] if rn + 1 < len(user_idx) else len(messages)
        next_msg = messages[user_idx[rn + 1]]["content"] if rn + 1 < len(user_idx) else None
        rejected = next_msg is not None and bool(_REJECTION_RE.search(next_msg))
        rounds.append({{
            "round_id": f"{{filepath.stem}}:{{rn}}",
            "msgs": messages[start + 1 : end],
            "reward": 0.0 if rejected else 1.0,
        }})
    return rounds


# ---------------------------------------------------------------------------
# Feature function
# ---------------------------------------------------------------------------

{code.strip()}


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify(rows: list[dict]) -> None:
    tp = fp = tn = fn = 0
    for row in rows:
        try:
            signal = feat_{h['id']}(row["msgs"])
        except Exception:
            signal = False
        rejected = row["reward"] == 0.0
        if signal and rejected:     tp += 1
        elif signal and not rejected: fp += 1
        elif not signal and rejected: fn += 1
        else:                         tn += 1

    n_signal = tp + fp
    n_no_signal = tn + fn
    total = tp + fp + tn + fn
    if total == 0:
        print("No rounds found.")
        return

    # Haldane-Anscombe correction
    a, b, c, d = tp + 0.5, fp + 0.5, fn + 0.5, tn + 0.5
    try:
        from scipy.stats import chi2_contingency
        chi2, p, _, _ = chi2_contingency([[tp, fp], [fn, tn]], correction=False)
    except ImportError:
        p = float("nan")
    or_val = (a * d) / (b * c)
    se = math.sqrt(1/a + 1/b + 1/c + 1/d)
    or_lo = math.exp(math.log(or_val) - 1.96 * se)
    or_hi = math.exp(math.log(or_val) + 1.96 * se)

    print(f"\nHypothesis: {h['id']}")
    print(f"  {desc}")
    print(f"\n  Rounds analyzed: {{total}}")
    print(f"  signal=T: {{n_signal}} rounds, {{tp}} rejected  ({{tp/n_signal*100:.1f}}% rejection rate)" if n_signal else "  signal=T: 0 rounds")
    print(f"  signal=F: {{n_no_signal}} rounds, {{fn}} rejected  ({{fn/n_no_signal*100:.1f}}% rejection rate)" if n_no_signal else "  signal=F: 0 rounds")
    print(f"\n  OR = {{or_val:.4f}} [{{or_lo:.4f}}, {{or_hi:.4f}}]")
    print(f"  p  = {{p:.4f}}  {{'(significant)' if p < 0.05 else '(not significant)'}}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify hypothesis: {h['id']}")
    parser.add_argument("--traces", required=True,
                        help="Path to Claude Code project traces directory")
    args = parser.parse_args()

    traces_dir = Path(args.traces)
    all_rounds = []
    for jsonl in sorted(traces_dir.glob("*.jsonl")):
        all_rounds.extend(parse_rounds(jsonl))

    if not all_rounds:
        print(f"No traces found in {{traces_dir}}")
    else:
        print(f"Loaded {{len(all_rounds)}} rounds from {{traces_dir}}")
        verify(all_rounds)
'''


def _extract_feature_fn(hyp_id: str, feature_src: str) -> str:
    pattern = re.compile(
        rf"(def feat_{re.escape(hyp_id)}\(.*?)(?=\ndef feat_|\Z)",
        re.DOTALL,
    )
    m = pattern.search(feature_src)
    if m:
        return m.group(1).strip()
    return f"def feat_{hyp_id}(msgs: list[dict]) -> bool:\n    raise NotImplementedError"


def _pr_body(selected: list[dict]) -> str:
    lines = [
        f"Submitting {len(selected)} significant hypothesis(es).",
        "",
        "## Hypotheses",
        "",
    ]
    for h in selected:
        desc = re.sub(r"^\[(TOXIC|HEALTHY)\] ", "", h["description"]).strip()
        lines.append(f"- **`{h['id']}`** — {desc}  ")
        lines.append(f"  OR={h['odds_ratio']:.2f}  p={h['p_value']:.4f}")
        lines.append("")
    lines += [
        "---",
        "_Submitted via [RetroCode](https://github.com/Hanchenli/RetroCode)_",
    ]
    return "\n".join(lines)


def _repo_readme() -> str:
    return """\
# swe-hypotheses

A community collection of statistically-verified hypotheses about AI coding agent behavior.

Each hypothesis predicts whether a pattern within a conversation round is associated with
explicit user rejection ("No, that's wrong", "undo this", etc.).

## Contributing

Use [RetroCode](https://github.com/Hanchenli/RetroCode) to generate and verify hypotheses
from your own sessions, then submit significant ones here via `retro --submit`.

## Format

Each hypothesis has two files in `hypotheses/`:
- `<id>.md` — description, stats (OR, p-value, round counts), and feature function
- `<id>.py` — standalone runnable Python program with helpers included
"""


def _print_manual_instructions(selected: list[dict], feature_src: str) -> None:
    print(f"\n[retro] Manual steps:")
    print(f"  1. Fork {TARGET_REPO_URL}")
    print(f"  2. Add hypotheses/<id>.md and hypotheses/<id>.py for each hypothesis")
    print(f"  3. Open a PR\n")
    for h in selected[:1]:
        code = _extract_feature_fn(h["id"], feature_src)
        print(f"  --- hypotheses/{h['id']}.md ---")
        print(_format_md(h, code)[:500])
        print("  ...\n")
        print(f"  --- hypotheses/{h['id']}.py ---")
        print(_format_py(h, code)[:400])
        print("  ...\n")
