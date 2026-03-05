"""
Main pipeline orchestrator for Claude Code trace hypothesis discovery.

Pipeline:
  1. Find and parse all session traces
  2. Label each session (heuristic + optional LLM)
  3. Verify seed hypotheses
  4. (Optional) LLM propose + verify + refine loop
  5. Generate reports

Usage:
  python -m src.hypoGen.run_pipeline --dir /path/to/project
  python -m src.hypoGen.run_pipeline --dir . --no-llm
  python -m src.hypoGen.run_pipeline --dir . --max-iter 2 --label-llm
"""
from __future__ import annotations

import argparse
import copy
import os
import sys
from pathlib import Path

from src.utils.ingestion.claude_reader import ClaudeReader
from src.hypoGen.trace_parser import parse_session
from src.hypoGen.labeler import label_session
from src.hypoGen.existing_hypothesis.seed_features import SEED_HYPOTHESES
from src.hypoGen.generator.hypothesis import Hypothesis
from src.hypoGen.verifier.verify import verify, report
from src.hypoGen.analyzer.report import (
    save_results_json,
    save_features_py,
    update_hypotheses_md,
)


def load_sessions(project_dir: str | Path) -> list[dict]:
    """Find and parse all session traces for a project directory.

    Returns list of dicts with: session_id, msgs, n_msgs
    """
    reader = ClaudeReader()
    trace_files = reader.find_trace_files(project_dir)

    if not trace_files:
        print(f"No trace files found for project: {project_dir}")
        print(f"  (looked in: {reader._project_dir(project_dir)})")
        return []

    print(f"Found {len(trace_files)} session trace files")

    sessions = []
    for fp in trace_files:
        msgs = parse_session(fp)
        if not msgs:
            continue
        sessions.append({
            "session_id": fp.stem,
            "msgs": msgs,
            "n_msgs": len(msgs),
        })

    print(f"  Parsed {len(sessions)} sessions with messages")
    return sessions


def label_sessions(
    sessions: list[dict], use_llm: bool = False
) -> list[dict]:
    """Add reward labels to each session. Returns rows for verification."""
    rows = []
    n_pass = 0
    n_fail = 0

    for s in sessions:
        reward = label_session(s["msgs"], use_llm=use_llm)
        s["reward"] = reward
        rows.append(s)
        if reward == 1.0:
            n_pass += 1
        else:
            n_fail += 1

    print(f"  Labeled: {n_pass} successful, {n_fail} problematic")
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Claude Code trace hypothesis discovery pipeline"
    )
    parser.add_argument(
        "--dir", required=True,
        help="Project directory to analyze (traces looked up via ClaudeReader)"
    )
    parser.add_argument("--max-iter", type=int, default=2, help="LLM propose+refine cycles")
    parser.add_argument("--no-llm", action="store_true", help="Skip all LLM calls (seed only)")
    parser.add_argument("--label-llm", action="store_true", help="Use LLM for session labeling")
    parser.add_argument(
        "--out-dir", default=None,
        help="Output directory (default: <dir>/.retro/hypoGen/)"
    )
    args = parser.parse_args()

    project_dir = Path(args.dir).resolve()
    out_dir = Path(args.out_dir) if args.out_dir else project_dir / ".retro" / "hypoGen"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -- 1. Load sessions ---------------------------------------------------
    print(f"\n{'─' * 60}")
    print(f"Loading traces for: {project_dir}")
    sessions = load_sessions(project_dir)
    if not sessions:
        print("No sessions to analyze. Exiting.")
        sys.exit(0)

    # -- 2. Label sessions --------------------------------------------------
    print(f"\n{'─' * 60}")
    print("Labeling sessions ...")
    use_label_llm = args.label_llm and not args.no_llm
    rows = label_sessions(sessions, use_llm=use_label_llm)

    if not any(r["reward"] == 0.0 for r in rows):
        print("WARNING: No problematic sessions found. All sessions labeled as successful.")
        print("  Stats will be degenerate. Consider --label-llm or more traces.")

    # -- 3. Verify seed hypotheses ------------------------------------------
    print(f"\n{'─' * 60}")
    hypotheses: list[Hypothesis] = [copy.copy(h) for h in SEED_HYPOTHESES]
    print(f"Verifying {len(hypotheses)} seed hypotheses ...")

    for h in hypotheses:
        verify(h, rows)
        status = "sig" if h.is_significant else "n/s"
        print(
            f"  [{status}]  {h.id:35s}  p={h.p_value:.4f}  "
            f"OR={h.odds_ratio:.2f}  n_pos={h.n_pos}  n_neg={h.n_neg}"
        )

    # -- 4. LLM proposal + refinement cycles --------------------------------
    if not args.no_llm:
        from src.hypoGen.generator.propose import propose_new, refine

        for iteration in range(1, args.max_iter + 1):
            print(f"\n{'=' * 60}")
            print(f"ITERATION {iteration} — proposing new hypotheses")
            print(f"{'=' * 60}")

            existing_ids = [h.id for h in hypotheses]
            sample = rows[:16]  # show up to 16 traces to LLM

            new_hyps = propose_new(
                sample_rows=sample,
                n_fail=4,
                n_pass=4,
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

            # Refine weak ones
            weak = [h for h in hypotheses if not h.is_significant]
            if weak:
                print(f"\nRefining {len(weak)} weak hypotheses ...")
                for h in weak:
                    refined = refine(h, rows[:50])
                    if refined is None:
                        continue
                    verify(refined, rows)
                    status = "sig" if refined.is_significant else "n/s"
                    print(
                        f"  [{status}]  {refined.id:35s}  p={refined.p_value:.4f}  "
                        f"OR={refined.odds_ratio:.2f}"
                    )
                    hypotheses.append(refined)

    # -- 5. Final report ----------------------------------------------------
    print(report(hypotheses))

    results_path = str(out_dir / "results.json")
    features_path = str(out_dir / "results_features.py")
    md_path = str(out_dir / "HYPOTHESES.md")

    save_results_json(hypotheses, results_path)
    save_features_py(hypotheses, features_path)
    update_hypotheses_md(hypotheses, n_sessions=len(rows), md_path=md_path)

    print(f"\nOutputs written to: {out_dir}/")


if __name__ == "__main__":
    main()
