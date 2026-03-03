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

from src.utils.ingestion import ClaudeReader
from src.contextEngineering.trace_ingester import (
    Conversation,
    TraceState,
    TRACE_STATE_FILE,
)
from src.contextEngineering.engine import ContextEngine
from src.retro_config import load_config, RetroConfig

logger = logging.getLogger(__name__)


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

    reader = ClaudeReader()
    engine = ContextEngine(
        playbook_path=playbook_path,
        model=cfg.default_model,
        claude_md_path=claude_md_path or None,
        max_bullets=cfg.max_bullets,
    )
    state_path = str(Path(retro_dir) / TRACE_STATE_FILE)
    state = TraceState.load(state_path)

    logger.info(f"[retro] daemon watching: {working_dir}")
    logger.info(f"[retro] playbook output: {playbook_path}")

    while True:
        try:
            _poll(working_dir, reader, engine, state, state_path, cfg.min_rounds)
        except Exception as e:
            logger.error(f"Poll error: {e}", exc_info=True)
        time.sleep(cfg.poll_interval)


def _poll(
    working_dir: str,
    reader: ClaudeReader,
    engine: ContextEngine,
    state: TraceState,
    state_path: str,
    min_rounds: int,
) -> None:
    trace_files = reader.find_trace_files(working_dir)
    if not trace_files:
        return

    processed = set(state.processed_session_ids)
    new_conversations: list[Conversation] = []

    for tf in trace_files:
        if tf.stem in processed:
            continue
        try:
            data = reader.parse_session(tf)
            conv = Conversation(
                session_id=data["session_id"],
                timestamp=data["timestamp"],
                messages=data["messages"],
            )
            if conv.rounds > 0:
                new_conversations.append(conv)
        except Exception as e:
            logger.warning(f"Failed to parse {tf.name}: {e}")

    new_round_count = sum(c.rounds for c in new_conversations)
    if new_round_count == 0:
        return

    logger.info(f"Found {len(new_conversations)} new sessions, {new_round_count} rounds")

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

    args = parser.parse_args()
    working_dir = str(Path(args.dir).resolve())

    # Load config from the user's project dir (falls back to built-in defaults)
    cfg = load_config(working_dir)

    retro_dir = Path(working_dir) / cfg.retro_dir
    retro_dir.mkdir(exist_ok=True)
    playbook_path = args.playbook or str(retro_dir / "playbook.txt")
    claude_md_path = args.claude_md or str(Path(working_dir) / "CLAUDE.md")

    if args.up:
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
