"""
Main pipeline orchestrator for Claude Code trace hypothesis discovery.

Unit of analysis: a ROUND = one user request + all assistant/tool messages
that follow until the next user message.  A round is labeled "rejected"
when the NEXT user message explicitly corrects or pushes back.

Pipeline:
  1. Find and parse all session traces into rounds
  2. Label each round (regex heuristic + optional LLM)
  3. Verify seed hypotheses
  4. (Optional) LLM propose + verify + refine loop
  5. Generate reports

Usage:
  python -m src.hypoGen.run_pipeline --dir /path/to/project
  python -m src.hypoGen.run_pipeline --dir . --no-llm
  python -m src.hypoGen.run_pipeline --dir . --max-iter 3 --label-llm
"""
from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

from src.utils.ingestion.claude_reader import ClaudeReader
from src.hypoGen.trace_parser import parse_session, parse_rounds
from src.hypoGen.labeler import label_round, LabelStore
from src.hypoGen.existing_hypothesis.seed_features import SEED_HYPOTHESES
from src.hypoGen.generator.hypothesis import Hypothesis
from src.hypoGen.verifier.verify import verify, report
from src.hypoGen.analyzer.report import (
    save_results_json,
    save_features_py,
    update_hypotheses_md,
)


def load_rounds(project_dir: str | Path) -> list[dict]:
    """Find all session traces and parse them into labeled rounds.

    Returns list of round dicts with keys:
      session_id, round_id, round_num, user_msg, msgs, next_user_msg, n_msgs
    """
    reader = ClaudeReader()
    trace_files = reader.find_trace_files(project_dir)

    if not trace_files:
        print(f"No trace files found for project: {project_dir}")
        print(f"  (looked in: {reader._project_dir(project_dir)})")
        return []

    print(f"Found {len(trace_files)} session trace files")

    all_rounds: list[dict] = []
    n_sessions = 0
    for fp in trace_files:
        rounds = parse_rounds(fp)
        if rounds:
            n_sessions += 1
            all_rounds.extend(rounds)

    print(f"  Parsed {n_sessions} sessions → {len(all_rounds)} rounds")
    return all_rounds


def label_rounds(
    rounds: list[dict],
    label_store: LabelStore | None = None,
) -> list[dict]:
    """Label each round based on the next user message.

    Returns the same round dicts with an added 'reward' key.
    """
    n_ok = 0
    n_rej = 0

    for r in rounds:
        # Check label store for cached label
        if label_store:
            cached = label_store.get(r["round_id"])
            if cached is not None:
                r["reward"] = cached
                if cached == 1.0:
                    n_ok += 1
                else:
                    n_rej += 1
                continue

        reward, reason = label_round(r["user_msg"], r["next_user_msg"])
        r["reward"] = reward

        if label_store:
            label_store.set(
                r["round_id"], reward, reason,
                user_msg=r["user_msg"],
                next_user_msg=r.get("next_user_msg"),
            )

        if reward == 1.0:
            n_ok += 1
        else:
            n_rej += 1

    if label_store:
        label_store.save()

    print(f"  Labeled: {n_ok} accepted, {n_rej} rejected")
    return rounds


def print_stats(rows: list[dict]) -> None:
    """Print dataset statistics without running full verification."""
    n_total = len(rows)
    n_rej = sum(1 for r in rows if r["reward"] == 0.0)
    n_ok = n_total - n_rej

    sessions: set[str] = set()
    for r in rows:
        sessions.add(r.get("session_id", ""))

    print(f"\n{'=' * 60}")
    print("  DATASET STATISTICS")
    print(f"{'=' * 60}")
    print(f"\n  Sessions:  {len(sessions)}")
    print(f"  Rounds:    {n_total}")
    print(f"  Accepted:  {n_ok}  ({n_ok / n_total * 100:.1f}%)" if n_total else "")
    print(f"  Rejected:  {n_rej}  ({n_rej / n_total * 100:.1f}%)" if n_total else "")
    print(f"  Rejection rate: {n_rej / n_total * 100:.1f}%" if n_total else "")

    # Rounds per session distribution
    from collections import Counter
    sess_rounds = Counter(r.get("session_id", "") for r in rows)
    sess_rej = Counter(r.get("session_id", "") for r in rows if r["reward"] == 0.0)
    if sess_rounds:
        sizes = sorted(sess_rounds.values())
        print(f"\n  Rounds/session: min={sizes[0]}  median={sizes[len(sizes)//2]}  max={sizes[-1]}")

    # Tool usage across rejected vs accepted
    from src.hypoGen.generator.hypothesis import iter_tool_calls
    tool_counts_rej: dict[str, int] = {}
    tool_counts_ok: dict[str, int] = {}
    for r in rows:
        target = tool_counts_rej if r["reward"] == 0.0 else tool_counts_ok
        for tn, _ in iter_tool_calls(r["msgs"]):
            target[tn] = target.get(tn, 0) + 1

    if tool_counts_rej or tool_counts_ok:
        all_tools = sorted(set(tool_counts_rej) | set(tool_counts_ok))
        print(f"\n  Tool usage (rejected / accepted rounds):")
        for t in all_tools:
            rej_ct = tool_counts_rej.get(t, 0)
            ok_ct = tool_counts_ok.get(t, 0)
            # Per-round averages
            rej_avg = rej_ct / n_rej if n_rej else 0
            ok_avg = ok_ct / n_ok if n_ok else 0
            marker = " <<<" if rej_avg > ok_avg * 1.5 and rej_avg > 0.5 else ""
            print(f"    {t:20s}  rej={rej_avg:.1f}/round  ok={ok_avg:.1f}/round{marker}")

    # Sample rejected round user messages
    if n_rej:
        print(f"\n  Sample rejected rounds (next user messages):")
        shown = 0
        for r in rows:
            if r["reward"] == 0.0:
                if shown >= 5:
                    remaining = n_rej - 5
                    if remaining > 0:
                        print(f"    ... and {remaining} more")
                    break
                next_msg = (r.get("next_user_msg") or "")[:120].replace("\n", " ")
                print(f"    [{r['round_id']}] {next_msg!r}")
                shown += 1

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code trace hypothesis discovery pipeline"
    )
    parser.add_argument(
        "--dir", required=True,
        help="Project directory to analyze (traces looked up via ClaudeReader)"
    )
    parser.add_argument("--max-iter", type=int, default=3, help="LLM propose+refine cycles")
    parser.add_argument("--no-llm", action="store_true", help="Skip all LLM calls (seed only)")
    parser.add_argument("--stats", action="store_true",
                        help="Show dataset statistics only (no hypothesis testing)")
    parser.add_argument("--refine-passes", type=int, default=2,
                        help="Max refinement passes per weak hypothesis (default: 2)")
    parser.add_argument(
        "--out-dir", default=None,
        help="Output directory (default: <dir>/.retro/hypoGen/)"
    )
    args = parser.parse_args()

    project_dir = Path(args.dir).resolve()
    out_dir = Path(args.out_dir) if args.out_dir else project_dir / ".retro" / "hypoGen"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -- 1. Load rounds -----------------------------------------------------
    print(f"\n{'─' * 60}")
    print(f"Loading traces for: {project_dir}")
    rounds = load_rounds(project_dir)
    if not rounds:
        print("No rounds to analyze. Exiting.")
        sys.exit(0)

    # -- 2. Label rounds ----------------------------------------------------
    print(f"\n{'─' * 60}")
    print("Labeling rounds (detecting user rejections) ...")
    label_store = LabelStore(str(out_dir / "labeled_traces.json"))
    rows = label_rounds(rounds, label_store=label_store)

    n_rej = sum(1 for r in rows if r["reward"] == 0.0)
    if n_rej == 0:
        print("WARNING: No rejected rounds found. Every round was accepted.")
        print("  This may mean the rejection detector needs tuning, or")
        print("  the user genuinely accepted every AI response.")
        print("  Consider gathering more traces for better signal.")

    # -- stats-only mode ----------------------------------------------------
    if args.stats:
        print_stats(rows)
        return

    # -- 3. Verify seed hypotheses ------------------------------------------
    print(f"\n{'─' * 60}")
    hypotheses: list[Hypothesis] = [copy.copy(h) for h in SEED_HYPOTHESES]
    print(f"Verifying {len(hypotheses)} seed hypotheses against {len(rows)} rounds ...")

    for h in hypotheses:
        verify(h, rows)
        direction = "toxic" if h.toxic else "healthy"
        status = "sig" if h.is_significant else "n/s"
        print(
            f"  [{status}]  {h.id:35s}  p={h.p_value:.4f}  "
            f"OR={h.odds_ratio:.2f}  n+={h.n_pos}  n-={h.n_neg}  ({direction})"
        )

    # -- 4. LLM proposal + refinement cycles --------------------------------
    if not args.no_llm:
        from src.hypoGen.generator.propose import propose_new, refine

        for iteration in range(1, args.max_iter + 1):
            print(f"\n{'=' * 60}")
            print(f"ITERATION {iteration} — proposing new hypotheses")
            print(f"{'=' * 60}")

            existing_ids = [h.id for h in hypotheses]

            # Balance sample: show both rejected and accepted rounds
            fails = [r for r in rows if r["reward"] == 0.0]
            passes = [r for r in rows if r["reward"] == 1.0]
            sample = (fails[:8] + passes[:8])

            new_hyps = propose_new(
                sample_rows=sample,
                n_fail=min(6, len(fails)),
                n_pass=min(6, len(passes)),
                existing_ids=existing_ids,
            )

            print(f"\nVerifying {len(new_hyps)} proposed hypotheses ...")
            for h in new_hyps:
                verify(h, rows)
                status = "sig" if h.is_significant else "n/s"
                print(
                    f"  [{status}]  {h.id:35s}  p={h.p_value:.4f}  "
                    f"OR={h.odds_ratio:.2f}"
                )
            hypotheses.extend(new_hyps)

            # Multi-pass refinement: refine weak hypotheses, iterate if improved
            new_weak = [h for h in new_hyps if not h.is_significant]
            if new_weak:
                print(f"\nRefining {len(new_weak)} weak hypotheses "
                      f"(up to {args.refine_passes} passes) ...")
                for h in new_weak:
                    current = h
                    for pass_num in range(1, args.refine_passes + 1):
                        refined = refine(current, rows[:80])
                        if refined is None:
                            break
                        verify(refined, rows)
                        status = "sig" if refined.is_significant else "n/s"
                        improved = refined.p_value < current.p_value
                        marker = " (improved)" if improved else " (no improvement)"
                        print(
                            f"  [{status}]  {refined.id:35s}  p={refined.p_value:.4f}  "
                            f"OR={refined.odds_ratio:.2f}{marker}"
                        )
                        hypotheses.append(refined)
                        # Stop refining if significant or not improving
                        if refined.is_significant or not improved:
                            break
                        current = refined

    # -- 5. Final report ----------------------------------------------------
    print(report(hypotheses))

    results_path = str(out_dir / "results.json")
    features_path = str(out_dir / "results_features.py")
    md_path = str(out_dir / "HYPOTHESES.md")

    save_results_json(hypotheses, results_path)
    save_features_py(hypotheses, features_path)
    update_hypotheses_md(hypotheses, n_rounds=len(rows), md_path=md_path)

    print(f"\nOutputs written to: {out_dir}/")


if __name__ == "__main__":
    main()
