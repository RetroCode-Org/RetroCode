"""
retro -- main entry point

Usage:
    python src/main.py --up                   # monitor current directory
    python src/main.py --up --dir /some/path  # monitor another project
    python src/main.py --up --playbook /path/to/CLAUDE.md  # write to CLAUDE.md

Every poll_interval seconds the daemon:
  1. Reads all .jsonl session files from ~/.claude/projects/<project-key>/
  2. Parses them into Conversation objects
  3. Finds sessions not yet processed
  4. If new rounds >= min_rounds, runs the context engineering pipeline
  5. Writes the updated playbook to --playbook (default: <dir>/.retro/playbook.txt)

Config is loaded from <dir>/retro_config.yaml (falls back to built-in defaults).
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.ingestion import ClaudeReader, CursorReader, CodexReader
from src.contextEngineering.trace_ingester import (
    Conversation,
    TraceState,
    TRACE_STATE_FILE,
)
from src.contextEngineering.engine import ContextEngine
from src.retro_config import load_config, RetroConfig

logger = logging.getLogger(__name__)


def _build_readers(cfg_inputs: list[str]):
    """Instantiate readers for the configured input sources."""
    all_readers = {
        "claude-code": ClaudeReader,
        "cursor":      CursorReader,
        "codex":       CodexReader,
    }
    return [all_readers[name]() for name in cfg_inputs if name in all_readers]


def _build_writers(cfg_outputs: list[str], working_dir: str, claude_md_path: str):
    """Instantiate writers for the configured output targets."""
    from src.utils.modification import ClaudeMdWriter, CursorRulesWriter, AgentsMdWriter
    all_writers = {
        "claude-code": lambda: ClaudeMdWriter(claude_md_path),
        "cursor":      lambda: CursorRulesWriter(working_dir),
        "codex":       lambda: AgentsMdWriter(working_dir),
    }
    return [all_writers[name]() for name in cfg_outputs if name in all_writers]


def setup_logging(working_dir: str, retro_dir: str) -> None:
    """Configure logging to both stderr and .retro/daemon.log."""
    Path(retro_dir).mkdir(exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = logging.FileHandler(Path(retro_dir) / "daemon.log")
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


# ---------------------------------------------------------------------------
# Daemon loop
# ---------------------------------------------------------------------------

def run_daemon(working_dir: str, playbook_path: str, claude_md_path: str, cfg: RetroConfig) -> None:
    """Infinite polling loop. Runs as a detached background process."""
    retro_dir = str(Path(working_dir) / cfg.retro_dir)
    setup_logging(working_dir, retro_dir)

    readers = _build_readers(cfg.inputs)
    writers = _build_writers(cfg.outputs, working_dir, claude_md_path)
    engine = ContextEngine(
        playbook_path=playbook_path,
        model=cfg.default_model,
        max_bullets=cfg.max_bullets,
        writers=writers,
    )
    state_path = str(Path(retro_dir) / TRACE_STATE_FILE)
    state = TraceState.load(state_path)

    logger.info(f"[retro] daemon watching: {working_dir}")
    logger.info(f"[retro] inputs:  {cfg.inputs}")
    logger.info(f"[retro] outputs: {cfg.outputs}")
    logger.info(f"[retro] playbook output: {playbook_path}")

    while True:
        try:
            _poll(working_dir, readers, engine, state, state_path, cfg.min_rounds)
        except Exception as e:
            logger.error(f"Poll error: {e}", exc_info=True)
        time.sleep(cfg.poll_interval)


def _poll(
    working_dir: str,
    readers: list,
    engine: ContextEngine,
    state: TraceState,
    state_path: str,
    min_rounds: int,
) -> None:
    processed = set(state.processed_session_ids)
    new_conversations: list[Conversation] = []

    source_counts: dict[str, int] = {}
    for reader in readers:
        for tf in reader.find_trace_files(working_dir):
            try:
                data = reader.parse_session(tf)
            except Exception as e:
                logger.warning(f"Failed to parse {tf.name}: {e}")
                continue
            if data["session_id"] in processed:
                continue
            conv = Conversation(
                session_id=data["session_id"],
                timestamp=data["timestamp"],
                messages=data["messages"],
            )
            if conv.rounds > 0:
                new_conversations.append(conv)
                source_counts[reader.tool_name] = source_counts.get(reader.tool_name, 0) + 1

    new_round_count = sum(c.rounds for c in new_conversations)
    if new_round_count == 0:
        return

    source_str = "  ".join(f"{k}:{v}" for k, v in source_counts.items())
    logger.info(f"Found {len(new_conversations)} new sessions [{source_str}], {new_round_count} rounds")

    if new_round_count < min_rounds:
        logger.info(f"Only {new_round_count} new rounds (< {min_rounds}), waiting for more")
        return

    engine.run(new_conversations)

    now = datetime.now(timezone.utc).isoformat()
    state.processed_session_ids.extend(c.session_id for c in new_conversations)
    state.last_run_timestamp = now
    state.save(state_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def spawn_daemon(working_dir: str, playbook_path: str, claude_md_path: str, cfg: RetroConfig) -> None:
    """Fork a detached child process running the daemon loop."""
    pid_path = Path(working_dir) / cfg.pid_file

    if pid_path.exists():
        existing_pid = int(pid_path.read_text().strip())
        try:
            os.kill(existing_pid, 0)
            print(f"[retro] daemon already running (pid {existing_pid})")
            return
        except ProcessLookupError:
            pass  # stale PID — overwrite

    pid = os.fork()
    if pid > 0:
        pid_path.write_text(str(pid))
        print(f"[retro] daemon started (pid {pid})")
        print(f"[retro] watching:  {working_dir}")
        print(f"[retro] playbook:  {playbook_path}")
        print(f"[retro] poll every {cfg.poll_interval}s, min rounds: {cfg.min_rounds}")
        return

    # Child: detach and run
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (sys.stdin.fileno(), sys.stdout.fileno(), sys.stderr.fileno()):
        os.dup2(devnull, fd)
    os.close(devnull)

    run_daemon(working_dir, playbook_path, claude_md_path, cfg)


def stop_daemon(working_dir: str, pid_file: str) -> None:
    """Kill all running retro daemon processes and clean up PID file."""
    import signal
    import subprocess

    killed = []

    try:
        result = subprocess.run(
            ["pgrep", "-f", "RetroCode.*main.py --up"],
            capture_output=True, text=True,
        )
        for pid_str in result.stdout.splitlines():
            pid = int(pid_str.strip())
            if pid == os.getpid():
                continue
            try:
                os.kill(pid, signal.SIGTERM)
                killed.append(pid)
            except ProcessLookupError:
                pass
    except FileNotFoundError:
        pass  # pgrep not available

    pid_path = Path(working_dir) / pid_file
    if pid_path.exists():
        pid_path.unlink()

    if killed:
        print(f"[retro] stopped {len(killed)} process(es): {killed}")
    else:
        print("[retro] no retro processes found")


def run_hypogen(working_dir: str, retro_dir: Path, args) -> None:
    """Run the round-level hypothesis generation pipeline."""
    import copy
    from src.hypoGen.trace_parser import parse_rounds, parse_rounds_from_messages
    from src.hypoGen.labeler import label_round, LabelStore
    from src.hypoGen.existing_hypothesis.seed_features import SEED_HYPOTHESES
    from src.hypoGen.verifier.verify import verify, report
    from src.hypoGen.analyzer.report import (
        save_results_json, save_features_py, update_hypotheses_md,
    )

    out_dir = retro_dir / "hypoGen"
    out_dir.mkdir(parents=True, exist_ok=True)

    readers = [ClaudeReader(), CursorReader(), CodexReader()]
    all_trace_files = []
    for reader in readers:
        all_trace_files.extend(reader.find_trace_files(working_dir))
    if not all_trace_files:
        print(f"[retro] No trace files found for: {working_dir}")
        return

    print(f"[retro] Found {len(all_trace_files)} session traces")

    # Parse sessions into rounds via each reader
    all_rounds: list[dict] = []
    for reader in readers:
        for fp in reader.find_trace_files(working_dir):
            data = reader.parse_session(fp)
            all_rounds.extend(
                parse_rounds_from_messages(data["session_id"], data["messages"])
            )

    if not all_rounds:
        print("[retro] No rounds found.")
        return

    print(f"[retro] Parsed {len(all_rounds)} rounds across {len(all_trace_files)} sessions")

    # Label rounds (only explicit user rejections count)
    store = LabelStore(str(out_dir / "labeled_traces.json"))
    n_new = 0
    for r in all_rounds:
        existing = store.get(r["round_id"])
        if existing is not None:
            r["reward"] = existing
        else:
            r["reward"], reason = label_round(r["user_msg"], r["next_user_msg"])
            store.set(r["round_id"], r["reward"], reason,
                      user_msg=r["user_msg"], next_user_msg=r["next_user_msg"])
            n_new += 1
    store.save()

    # Build round rows: each round is an independent data point
    rows: list[dict] = []
    for r in all_rounds:
        rows.append({
            "session_id": r["round_id"],   # use round_id as the unique key
            "msgs": r["msgs"],
            "n_msgs": r["n_msgs"],
            "reward": r["reward"],
        })

    n_rejected = sum(1 for r in rows if r["reward"] == 0.0)
    print(f"[retro] {store.summary()} ({n_new} newly labeled)")
    print(f"[retro] Rounds: {len(rows)} total, {n_rejected} rejected")

    # Verify seed hypotheses (features look at early msgs, label = session rejection)
    hypotheses = [copy.copy(h) for h in SEED_HYPOTHESES]
    print(f"\n[retro] Verifying {len(hypotheses)} seed hypotheses ...")
    for h in hypotheses:
        verify(h, rows)
        status = "sig" if h.is_significant else "n/s"
        print(f"  [{status}]  {h.id:35s}  p={h.p_value:.4f}  OR={h.odds_ratio:.2f}"
              f"  n_pos={h.n_pos}  n_neg={h.n_neg}")

    # LLM proposal + refinement
    if not args.no_llm:
        from src.hypoGen.generator.propose import propose_new, refine

        for iteration in range(1, args.max_iter + 1):
            print(f"\n[retro] Iteration {iteration} — proposing new hypotheses")
            existing_ids = [h.id for h in hypotheses]
            new_hyps = propose_new(
                sample_rows=rows, n_fail=4, n_pass=4,
                existing_ids=existing_ids,
            )
            for h in new_hyps:
                verify(h, rows)
                status = "sig" if h.is_significant else "n/s"
                print(f"  [{status}]  {h.id:35s}  p={h.p_value:.4f}  OR={h.odds_ratio:.2f}")
            hypotheses.extend(new_hyps)

            weak = [h for h in hypotheses if not h.is_significant]
            for h in weak:
                refined = refine(h, rows)
                if refined:
                    verify(refined, rows)
                    hypotheses.append(refined)

    # Generate reports
    print(report(hypotheses))
    save_results_json(hypotheses, str(out_dir / "results.json"))
    save_features_py(hypotheses, str(out_dir / "results_features.py"))
    update_hypotheses_md(hypotheses, n_sessions=len(rows), label="rounds",
                         md_path=str(out_dir / "HYPOTHESES.md"))
    print(f"\n[retro] Outputs written to: {out_dir}/")



def run_offline(working_dir: str, playbook_path: str, claude_md_path: str, cfg: RetroConfig) -> None:
    """Run one playbook update pass using all available sessions, then exit."""
    retro_dir = str(Path(working_dir) / cfg.retro_dir)
    setup_logging(working_dir, retro_dir)

    readers = _build_readers(cfg.inputs)
    writers = _build_writers(cfg.outputs, working_dir, claude_md_path)
    engine = ContextEngine(
        playbook_path=playbook_path,
        model=cfg.default_model,
        max_bullets=cfg.max_bullets,
        writers=writers,
    )
    state_path = str(Path(retro_dir) / TRACE_STATE_FILE)
    state = TraceState.load(state_path)

    processed = set(state.processed_session_ids)
    new_conversations: list[Conversation] = []
    source_counts: dict[str, int] = {}

    for reader in readers:
        for tf in reader.find_trace_files(working_dir):
            try:
                data = reader.parse_session(tf)
            except Exception as e:
                logger.warning(f"Failed to parse {tf.name}: {e}")
                continue
            if data["session_id"] in processed:
                continue
            conv = Conversation(
                session_id=data["session_id"],
                timestamp=data["timestamp"],
                messages=data["messages"],
            )
            if conv.rounds > 0:
                new_conversations.append(conv)
                source_counts[reader.tool_name] = source_counts.get(reader.tool_name, 0) + 1

    if not new_conversations:
        print("[retro] No new sessions found.")
        return

    new_round_count = sum(c.rounds for c in new_conversations)
    source_str = "  ".join(f"{k}:{v}" for k, v in source_counts.items())
    print(f"[retro] {len(new_conversations)} new sessions [{source_str}], {new_round_count} rounds")

    engine.run(new_conversations)

    now = datetime.now(timezone.utc).isoformat()
    state.processed_session_ids.extend(c.session_id for c in new_conversations)
    state.last_run_timestamp = now
    state.save(state_path)
    print(f"[retro] Playbook updated -> {playbook_path}")
    for w in writers:
        print(f"[retro] {w.agent_name} rules updated -> {w.path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="retro",
        description="RetroCode: update your Claude playbook from real conversations",
    )
    parser.add_argument("--up", action="store_true", help="Start the background daemon")
    parser.add_argument("--down", action="store_true", help="Stop the background daemon")
    parser.add_argument("--dir", default=".", metavar="DIR",
                        help="Project directory to monitor (default: .)")
    parser.add_argument("--playbook", default=None, metavar="FILE",
                        help="Playbook output file (default: <dir>/.retro/playbook.txt)")
    parser.add_argument("--claude-md", default=None, metavar="FILE",
                        help="CLAUDE.md to sync playbook into (default: <dir>/CLAUDE.md)")
    parser.add_argument("--foreground", action="store_true",
                        help="Run in foreground instead of forking (useful for debugging)")
    parser.add_argument("--offline", action="store_true",
                        help="Run one update pass using all new sessions, then exit")

    # Hypothesis generation
    parser.add_argument("--hypogen", action="store_true",
                        help="Generate hypotheses about session patterns")
    parser.add_argument("--no-llm", action="store_true",
                        help="(hypogen) Skip LLM calls, seed hypotheses only")
    parser.add_argument("--label-llm", action="store_true",
                        help="(hypogen) Use LLM for session labeling")
    parser.add_argument("--max-iter", type=int, default=2,
                        help="(hypogen) LLM propose+refine cycles (default: 2)")

    args = parser.parse_args()
    working_dir = str(Path(args.dir).resolve())

    # Load config from the user's project dir (falls back to built-in defaults)
    cfg = load_config(working_dir)

    retro_dir = Path(working_dir) / cfg.retro_dir
    retro_dir.mkdir(exist_ok=True)
    playbook_path = args.playbook or str(retro_dir / "playbook.txt")
    claude_md_path = args.claude_md or str(Path(working_dir) / "CLAUDE.md")

    if args.hypogen:
        run_hypogen(working_dir, retro_dir, args)
    elif args.offline:
        run_offline(working_dir, playbook_path, claude_md_path, cfg)
    elif args.up:
        if args.foreground:
            run_daemon(working_dir, playbook_path, claude_md_path, cfg)
        else:
            spawn_daemon(working_dir, playbook_path, claude_md_path, cfg)
    elif args.down:
        stop_daemon(working_dir, cfg.pid_file)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
