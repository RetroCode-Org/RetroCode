"""
Entry point for retro --analyzeme.

Loads all traces, computes stats, renders output.
"""
from __future__ import annotations

from pathlib import Path

from src.utils.ingestion import ClaudeReader, CursorReader, CodexReader
from src.hypoGen.trace_parser import parse_rounds_from_messages
from src.hypoGen.labeler import label_round
from .stats import compute_stats
from .renderer import render_terminal, render_html


def run_analyzeme(working_dir: str, retro_dir: Path, save_html: bool = False) -> None:
    """Run the analyzeme analysis and print results."""
    import sys
    import time

    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def _spin(msg: str, steps: int = 8):
        for i in range(steps):
            sys.stdout.write(f"\r  {_SPINNER[i % len(_SPINNER)]} {msg}")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(msg) + 10) + "\r")

    print()
    _spin("Loading your AI coding history...")

    # ── Load all sessions ─────────────────────────────────────────
    readers = [ClaudeReader(), CursorReader(), CodexReader()]
    sessions: list[dict] = []
    all_rounds: list[dict] = []
    source_names: list[str] = []

    for reader in readers:
        traces = reader.find_trace_files(working_dir)
        if traces:
            source_names.append(reader.tool_name)
        for fp in traces:
            try:
                data = reader.parse_session(fp)
                sessions.append(data)
                rounds = parse_rounds_from_messages(
                    data["session_id"], data["messages"]
                )
                all_rounds.extend(rounds)
            except Exception:
                continue

    if not sessions:
        print("  No AI coding sessions found!\n")
        print("  Supported sources: Claude Code, Cursor, Codex")
        print("  Use one of these tools for a while, then try again.")
        print(f"  (Looked for traces linked to: {working_dir})\n")
        return

    # ── Label rounds ──────────────────────────────────────────────
    _spin("Labeling rounds...")
    for r in all_rounds:
        reward, _ = label_round(r.get("user_msg", ""), r.get("next_user_msg"))
        r["reward"] = reward

    sources_str = " + ".join(source_names) if source_names else "unknown"
    print(f"  Found {len(sessions)} sessions, {len(all_rounds)} rounds")
    print(f"  Sources: {sources_str}")
    _spin("Crunching the numbers...")

    # ── Compute stats ─────────────────────────────────────────────
    stats = compute_stats(sessions, all_rounds)

    # ── Render ────────────────────────────────────────────────────
    print(render_terminal(stats))

    # ── Optional HTML export ──────────────────────────────────────
    if save_html:
        html_path = retro_dir / "wrapped.html"
        html_path.write_text(render_html(stats))
        print(f"  \033[32mHTML report saved to:\033[0m {html_path}")
        print(f"  Open in a browser to see your full Wrapped report!\n")
