"""
Community hypothesis pull + verify + contribute.

retro --pull        — download community hypotheses, verify against local traces
retro --contribute  — submit local verification stats back as a PR
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
from typing import Any

TARGET_REPO = "RetroCode-Org/swe-hypotheses"
GITHUB_API = f"https://api.github.com/repos/{TARGET_REPO}"


# ---------------------------------------------------------------------------
# GitHub API helpers (public, no auth required for reading)
# ---------------------------------------------------------------------------

def _fetch_json(url: str) -> Any:
    """Fetch JSON from GitHub public API."""
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "RetroCode",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("[retro] GitHub API rate limit reached. Try again later or use `gh auth login`.")
        elif e.code == 404:
            print(f"[retro] Repository not found: {TARGET_REPO}")
        else:
            print(f"[retro] GitHub API error: {e.code} {e.reason}")
        return None
    except urllib.error.URLError as e:
        print(f"[retro] Network error: {e.reason}")
        return None


def _fetch_file_content(path: str) -> str | None:
    """Fetch a single file's content from the community repo."""
    import base64
    data = _fetch_json(f"{GITHUB_API}/contents/{path}")
    if data is None:
        return None
    try:
        return base64.b64decode(data["content"]).decode()
    except Exception:
        return None


def _list_hypotheses() -> list[str]:
    """Return list of hypothesis IDs available in the community repo."""
    data = _fetch_json(f"{GITHUB_API}/contents/hypotheses")
    if data is None:
        return []
    return sorted(
        entry["name"][:-3]
        for entry in data
        if isinstance(entry, dict) and entry.get("name", "").endswith(".md")
    )


# ---------------------------------------------------------------------------
# Feature function extraction & sandboxed execution
# ---------------------------------------------------------------------------

def _extract_feature_from_md(md_content: str) -> str | None:
    """Extract the Python feature function from a hypothesis .md file."""
    m = re.search(r'## Feature function\s*```python\s*\n(.*?)```', md_content, re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_frontmatter(md_content: str) -> dict:
    """Extract YAML frontmatter as a simple dict (no pyyaml dependency)."""
    m = re.match(r'^---\n(.*?)\n---', md_content, re.DOTALL)
    if not m:
        return {}
    result = {}
    for line in m.group(1).split('\n'):
        if ':' in line:
            key, _, val = line.partition(':')
            val = val.strip().strip('"').strip("'")
            result[key.strip()] = val
    return result


def _compile_feature(code: str, hyp_id: str):
    """Compile a feature function in a sandbox namespace. Returns callable or None."""
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    # Inject standard helpers
    exec("""
import json, re
from typing import Iterator

EDIT_TOOLS   = ("Edit", "Write", "NotebookEdit")
READ_TOOLS   = ("Read",)
SEARCH_TOOLS = ("Glob", "Grep")
BASH_TOOL    = "Bash"
AGENT_TOOL   = "Agent"
ERROR_KWS    = ["error:", "traceback", "exception", "failed", "errno",
                "no such file", "command not found", "syntax error"]

def _parse_args(ta):
    if isinstance(ta, dict): return ta
    try: return json.loads(ta) if ta else {}
    except: return {}

def iter_tool_calls(msgs):
    for m in msgs:
        if m.get("role") == "assistant":
            for tn, ta in zip(m.get("tool_names", []), m.get("tool_args", [])):
                yield tn, (ta if isinstance(ta, dict) else (_parse_args(ta)))

def iter_tool_results(msgs):
    for m in msgs:
        if m.get("role") == "tool":
            yield m.get("name", ""), m.get("content", "")
""", ns)
    try:
        exec(code, ns)
        fn_name = f"feat_{hyp_id}"
        return ns.get(fn_name)
    except Exception as e:
        print(f"  [warn] Failed to compile {hyp_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Verification logic (mirrors verifier/verify.py but standalone)
# ---------------------------------------------------------------------------

def _verify_against_rounds(feat_fn, rounds: list[dict]) -> dict | None:
    """Run a feature function against round rows. Returns stats dict."""
    tp = fp = tn = fn = 0
    for row in rounds:
        try:
            signal = feat_fn(row["msgs"])
        except Exception:
            signal = False
        rejected = row.get("reward", 1.0) == 0.0
        if signal and rejected:      tp += 1
        elif signal and not rejected: fp += 1
        elif not signal and rejected: fn += 1
        else:                         tn += 1

    n_signal = tp + fp
    n_no_signal = tn + fn
    total = tp + fp + tn + fn

    if total == 0:
        return None

    # Haldane-Anscombe correction
    a, b, c, d = tp + 0.5, fp + 0.5, fn + 0.5, tn + 0.5
    or_val = (a * d) / (b * c)
    se = math.sqrt(1/a + 1/b + 1/c + 1/d)
    or_lo = math.exp(math.log(or_val) - 1.96 * se)
    or_hi = math.exp(math.log(or_val) + 1.96 * se)

    try:
        from scipy.stats import chi2_contingency
        import numpy as np
        table = np.array([[tp, fp], [fn, tn]])
        if table.sum() > 0 and 0 not in table.sum(axis=0) and 0 not in table.sum(axis=1):
            _, p, _, _ = chi2_contingency(table, correction=False)
        else:
            p = 1.0
    except ImportError:
        p = float("nan")

    return {
        "n_rounds_signal": n_signal,
        "n_rejected_signal": tp,
        "n_rounds_no_signal": n_no_signal,
        "n_rejected_no_signal": fn,
        "odds_ratio": round(or_val, 4),
        "or_ci": [round(or_lo, 4), round(or_hi, 4)],
        "p_value": round(float(p), 6),
        "significant": float(p) < 0.05,
        "total_rounds": total,
    }


# ---------------------------------------------------------------------------
# retro --pull
# ---------------------------------------------------------------------------

def run_pull(working_dir: str, retro_dir: Path, all_rounds: list[dict]) -> None:
    """Download community hypotheses and verify against local traces."""
    out_dir = retro_dir / "hypoGen"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n[retro] Fetching community hypotheses from RetroCode-Org/swe-hypotheses ...")
    hyp_ids = _list_hypotheses()

    if not hyp_ids:
        print("[retro] No community hypotheses found yet.")
        print("[retro] Be the first to contribute: retro --hypogen && retro --submit")
        return

    print(f"[retro] Found {len(hyp_ids)} community hypothesis(es)")

    if not all_rounds:
        print("[retro] No local trace rounds to verify against.")
        print("[retro] Run some sessions first, then try again.")
        return

    n_rejected = sum(1 for r in all_rounds if r.get("reward", 1.0) == 0.0)
    print(f"[retro] Local data: {len(all_rounds)} rounds ({n_rejected} rejected)\n")

    results = []
    print("=" * 70)
    print(f"  {'ID':<30s}  {'Community':>12s}  {'Local OR':>10s}  {'Local p':>10s}  {'Replicates?':>12s}")
    print("=" * 70)

    for hyp_id in hyp_ids:
        md_content = _fetch_file_content(f"hypotheses/{hyp_id}.md")
        if md_content is None:
            continue

        frontmatter = _extract_frontmatter(md_content)
        code = _extract_feature_from_md(md_content)
        if not code:
            print(f"  {hyp_id:<30s}  (no feature function found)")
            continue

        feat_fn = _compile_feature(code, hyp_id)
        if feat_fn is None:
            continue

        community_or = frontmatter.get("odds_ratio", "?")
        community_p = frontmatter.get("p_value", "?")

        stats = _verify_against_rounds(feat_fn, all_rounds)
        if stats is None:
            print(f"  {hyp_id:<30s}  OR={community_or:>7s}  (no data)")
            continue

        replicates = stats["significant"]
        tag = "YES" if replicates else "no"

        print(f"  {hyp_id:<30s}  OR={str(community_or):>7s}  "
              f"OR={stats['odds_ratio']:>8.2f}  p={stats['p_value']:>8.4f}  "
              f"{'  YES' if replicates else '   no':>12s}")

        results.append({
            "hypothesis_id": hyp_id,
            "description": frontmatter.get("description", ""),
            "community_or": community_or,
            "community_p": community_p,
            "feature_code": code,
            **stats,
        })

    print("=" * 70)

    # Save for --contribute
    results_path = out_dir / "community_results.json"
    results_path.write_text(json.dumps(results, indent=2))

    sig_count = sum(1 for r in results if r["significant"])
    print(f"\n[retro] {sig_count}/{len(results)} community hypotheses replicate locally")
    print(f"[retro] Results saved to {results_path}")
    if results:
        print(f"[retro] To contribute your stats back: retro --contribute --dir {working_dir}")


# ---------------------------------------------------------------------------
# retro --contribute
# ---------------------------------------------------------------------------

def run_contribute(working_dir: str, retro_dir: Path) -> None:
    """Submit local verification stats back to the community repo."""
    results_path = retro_dir / "hypoGen" / "community_results.json"
    if not results_path.exists():
        print("[retro] No community verification results found.")
        print("[retro] Run `retro --pull --dir .` first to verify community hypotheses locally.")
        return

    results = json.loads(results_path.read_text())
    if not results:
        print("[retro] No hypotheses to contribute stats for.")
        return

    print("\n" + "=" * 60)
    print("  CONTRIBUTE VERIFICATION — your local stats")
    print("=" * 60)

    for idx, r in enumerate(results, 1):
        sig = "sig" if r["significant"] else "n/s"
        print(f"\n  [{idx}] {r['hypothesis_id']}")
        if r.get("description"):
            print(f"      {r['description']}")
        print(f"      signal=T: {r['n_rounds_signal']} rounds, {r['n_rejected_signal']} rejected")
        print(f"      signal=F: {r['n_rounds_no_signal']} rounds, {r['n_rejected_no_signal']} rejected")
        print(f"      OR={r['odds_ratio']:.2f}  p={r['p_value']:.4f}  [{sig}]")

    print("\n" + "-" * 60)
    print("Enter numbers to contribute (e.g. 1,3), 'a' for all, or 'q' to quit:")
    try:
        raw = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n[retro] Aborted.")
        return

    if raw.lower() == "q":
        print("[retro] Aborted.")
        return

    if raw.lower() == "a":
        selected = results
    else:
        try:
            indices = [int(x.strip()) - 1 for x in raw.split(",")]
            selected = [results[i] for i in indices if 0 <= i < len(results)]
        except ValueError:
            print("[retro] Invalid input.")
            return

    if not selected:
        print("[retro] Nothing selected.")
        return

    if not shutil.which("gh"):
        print("\n[retro] `gh` CLI not found. Install from https://cli.github.com/")
        return

    result = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if result.returncode != 0:
        print("\n[retro] Not authenticated. Run: gh auth login")
        return

    _open_contribute_pr(selected)


def _open_contribute_pr(selected: list[dict]) -> None:
    """Fork, write verification files, open PR."""
    whoami = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                            capture_output=True, text=True)
    gh_user = whoami.stdout.strip()
    if not gh_user:
        print("[retro] Could not determine GitHub username.")
        return

    # Unique anonymous ID for this verification batch
    anon_id = hashlib.sha256(f"{gh_user}-{date.today().isoformat()}".encode()).hexdigest()[:8]
    branch = f"verify-{anon_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        # Fork (idempotent)
        print(f"\n[retro] Forking {TARGET_REPO} ...")
        subprocess.run(
            ["gh", "repo", "fork", TARGET_REPO, "--clone=false"],
            cwd=tmpdir, capture_output=True, text=True
        )

        fork_slug = f"{gh_user}/{TARGET_REPO.split('/')[1]}"
        print(f"[retro] Cloning fork {fork_slug} ...")
        r = subprocess.run(
            ["gh", "repo", "clone", fork_slug],
            cwd=tmpdir, capture_output=True, text=True
        )
        repo_name = TARGET_REPO.split("/")[1]
        repo_dir = Path(tmpdir) / repo_name
        if not repo_dir.exists():
            dirs = [d for d in Path(tmpdir).iterdir() if d.is_dir()]
            repo_dir = dirs[0] if dirs else None
        if not repo_dir or not repo_dir.exists():
            print(f"[retro] Clone failed:\n{r.stderr}")
            return

        # Write verification files
        for r_data in selected:
            hyp_id = r_data["hypothesis_id"]
            ver_dir = repo_dir / "verifications" / hyp_id
            ver_dir.mkdir(parents=True, exist_ok=True)
            ver_file = ver_dir / f"{anon_id}.json"
            ver_file.write_text(json.dumps({
                "hypothesis_id": hyp_id,
                "n_rounds_signal": r_data["n_rounds_signal"],
                "n_rejected_signal": r_data["n_rejected_signal"],
                "n_rounds_no_signal": r_data["n_rounds_no_signal"],
                "n_rejected_no_signal": r_data["n_rejected_no_signal"],
                "odds_ratio": r_data["odds_ratio"],
                "or_ci": r_data["or_ci"],
                "p_value": r_data["p_value"],
                "significant": r_data["significant"],
                "total_rounds": r_data["total_rounds"],
                "verified_at": date.today().isoformat(),
            }, indent=2) + "\n")
            print(f"[retro] Wrote verifications/{hyp_id}/{anon_id}.json")

        # Commit + push
        subprocess.run(["git", "checkout", "-b", branch],
                       cwd=repo_dir, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)

        names = ", ".join(r["hypothesis_id"] for r in selected)
        diff = subprocess.run(["git", "diff", "--cached", "--quiet"],
                              cwd=repo_dir, capture_output=True)
        if diff.returncode == 0:
            print("[retro] No new verification data to commit.")
            return

        subprocess.run(
            ["git", "commit", "-m", f"Add verification stats: {names}"],
            cwd=repo_dir, check=True
        )

        print(f"[retro] Pushing branch {branch} ...")
        r = subprocess.run(
            ["git", "push", "origin", branch, "--force-with-lease"],
            cwd=repo_dir, capture_output=True, text=True
        )
        if r.returncode != 0:
            r = subprocess.run(
                ["git", "push", "origin", branch],
                cwd=repo_dir, capture_output=True, text=True
            )
        if r.returncode != 0:
            print(f"[retro] Push failed:\n{r.stderr}")
            return

        # Open PR
        head_flag = f"{gh_user}:{branch}"
        n_hyps = len(selected)
        r = subprocess.run(
            ["gh", "pr", "create",
             "--repo", TARGET_REPO,
             "--head", head_flag,
             "--base", "main",
             "--title", f"Add verification data ({n_hyps} hypothesis(es))",
             "--body", _contribute_pr_body(selected)],
            cwd=repo_dir, capture_output=True, text=True
        )
        if r.returncode == 0:
            print(f"\n[retro] PR created: {r.stdout.strip()}")
        elif "already exists" in (r.stderr + r.stdout):
            print(f"\n[retro] PR already exists for this branch.")
        else:
            print(f"[retro] PR creation failed:\n{r.stderr}")
            print(f"[retro] Branch pushed. Open PR manually at https://github.com/{TARGET_REPO}")


def _contribute_pr_body(selected: list[dict]) -> str:
    lines = [
        f"Adding independent verification data for {len(selected)} hypothesis(es).",
        "",
        "## Verification Results",
        "",
    ]
    for r in selected:
        sig = "significant" if r["significant"] else "not significant"
        lines.append(f"- **`{r['hypothesis_id']}`** — OR={r['odds_ratio']:.2f} p={r['p_value']:.4f} ({sig})")
        lines.append(f"  {r['total_rounds']} rounds analyzed")
        lines.append("")
    lines += [
        "---",
        "_Submitted via [RetroCode](https://github.com/RetroCode-Org/RetroCode) `retro --contribute`_",
    ]
    return "\n".join(lines)
