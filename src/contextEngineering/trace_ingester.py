"""Trace ingestion and state persistence for conversation traces."""

import json
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TRACE_STATE_FILE = ".trace_state.json"


@dataclass
class Conversation:
    """A single conversation session with its messages."""
    session_id: str
    timestamp: str
    messages: list[dict]

    @property
    def rounds(self) -> int:
        """Count user-assistant round trips."""
        user_msgs = sum(1 for m in self.messages if m.get("role") == "user")
        return user_msgs


@dataclass
class TraceState:
    """Persisted state tracking which traces have been processed."""
    processed_session_ids: list[str] = field(default_factory=list)
    last_run_timestamp: Optional[str] = None

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump({
                "processed_session_ids": self.processed_session_ids,
                "last_run_timestamp": self.last_run_timestamp,
            }, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "TraceState":
        if not os.path.exists(path):
            return cls()
        with open(path) as f:
            data = json.load(f)
        return cls(
            processed_session_ids=data.get("processed_session_ids", []),
            last_run_timestamp=data.get("last_run_timestamp"),
        )


class TraceIngester:
    """Ingests conversation traces from a directory and tracks state."""

    def __init__(self, traces_dir: str, state_dir: str = "."):
        self.traces_dir = traces_dir
        self.state_path = os.path.join(state_dir, TRACE_STATE_FILE)
        self.state = TraceState.load(self.state_path)

    def ingest(self) -> list[Conversation]:
        """Read all trace files from the traces directory."""
        conversations = []
        traces_path = Path(self.traces_dir)
        if not traces_path.exists():
            logger.warning(f"Traces directory does not exist: {self.traces_dir}")
            return conversations

        for trace_file in sorted(traces_path.glob("*.json")):
            try:
                with open(trace_file) as f:
                    data = json.load(f)
                conv = Conversation(
                    session_id=data.get("session_id", trace_file.stem),
                    timestamp=data.get("timestamp", ""),
                    messages=data.get("messages", []),
                )
                conversations.append(conv)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Skipping malformed trace {trace_file}: {e}")
        return conversations

    def get_new_conversations(self, conversations: list[Conversation]) -> list[Conversation]:
        """Filter to only conversations not yet processed."""
        processed = set(self.state.processed_session_ids)
        return [c for c in conversations if c.session_id not in processed]

    def count_new_rounds(self, new_conversations: list[Conversation]) -> int:
        """Count total conversation rounds across new conversations."""
        return sum(c.rounds for c in new_conversations)

    def mark_processed(self, conversations: list[Conversation], timestamp: str):
        """Mark conversations as processed and persist state."""
        new_ids = [c.session_id for c in conversations]
        self.state.processed_session_ids.extend(new_ids)
        self.state.last_run_timestamp = timestamp
        self.state.save(self.state_path)
        logger.info(f"Marked {len(new_ids)} conversations as processed")
