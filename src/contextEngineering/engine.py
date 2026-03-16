"""Context engineering engine: orchestrates the reflect-curate loop."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .config import DEFAULT_MODEL, MAX_PLAYBOOK_BULLETS
from .reflector import Reflector
from .curator import Curator, load_playbook, save_playbook
from .trace_ingester import Conversation
from src.utils.modification import ClaudeMdWriter, CursorRulesWriter, AgentsMdWriter
from src.utils.modification.base import BaseMarkdownWriter

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 4

_WRITER_REGISTRY: dict[str, type[BaseMarkdownWriter]] = {
    "claude-code": ClaudeMdWriter,
    "cursor":      CursorRulesWriter,
    "codex":       AgentsMdWriter,
}


class ContextEngine:
    """Orchestrates the context engineering pipeline.

    Called from the main loop after trace ingestion confirms there are
    enough new conversation rounds to warrant a playbook update.

    Modes:
        verbose=True:  Interactive mode — show candidates for user approval
        verbose=False: Silent mode — auto-apply all curator decisions (default)
    """

    def __init__(
        self,
        playbook_path: str = "playbook.txt",
        model: str = DEFAULT_MODEL,
        claude_md_path: Optional[str] = None,
        max_bullets: int = MAX_PLAYBOOK_BULLETS,
        writers: Optional[list[BaseMarkdownWriter]] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        verbose: bool = False,
    ):
        self.playbook_path = playbook_path
        self.claude_md_path = claude_md_path
        self.batch_size = batch_size
        self.verbose = verbose
        self.writers: list[BaseMarkdownWriter] = writers or []
        # Legacy: if claude_md_path given but no writers, default to CLAUDE.md only
        if not self.writers and claude_md_path:
            self.writers = [ClaudeMdWriter(claude_md_path)]
        self.reflector = Reflector(model=model)
        self.curator = Curator(model=model, max_bullets=max_bullets)

    def run(self, new_conversations: list[Conversation]) -> str:
        """Run the context engineering pipeline on new conversations.

        Args:
            new_conversations: New conversation traces to process.

        Returns:
            The updated playbook text.
        """
        playbook, next_global_id = load_playbook(self.playbook_path)

        # Convert Conversation objects to dicts for the reflector
        traces = [
            {"session_id": c.session_id, "messages": c.messages}
            for c in new_conversations
        ]

        # Step 1: Reflect on each trace individually (parallel, in batches)
        logger.info(
            f"Reflecting on {len(traces)} new conversations "
            f"(batch_size={self.batch_size})..."
        )
        reflections = self._reflect_parallel(traces, playbook)

        if not reflections:
            logger.info("No insights extracted from any trace, playbook unchanged")
            return playbook

        total_insights = sum(len(r.get("insights", [])) for r in reflections)

        # Step 2: Curate playbook updates from all reflections
        logger.info(
            f"Curating {total_insights} insights from {len(reflections)} "
            f"reflections into playbook..."
        )
        updated_playbook, new_next_id = self.curator.curate(
            playbook, reflections, next_global_id
        )

        ops = self.curator.last_operations if hasattr(self.curator, "last_operations") else []

        # Step 3: Interactive or silent application
        if self.verbose and ops:
            from .interactive import interactive_curate
            # In verbose mode, curator proposes but user decides
            # Re-apply from scratch with user selection
            updated_playbook, new_next_id, selected_ops = interactive_curate(
                playbook, ops, next_global_id
            )
            if not selected_ops:
                return playbook
            ops = selected_ops

        # Step 4: Save playbook
        added = sum(1 for o in ops if o.get("type") == "ADD")
        deleted = sum(1 for o in ops if o.get("type") == "DELETE")
        save_playbook(self.playbook_path, updated_playbook)
        logger.info(f"Playbook updated: +{added} added, -{deleted} deleted")

        # Step 5: Sync to all configured output targets
        for writer in self.writers:
            writer.write(updated_playbook)
            logger.info(f"{writer.agent_name} rules updated: {writer.path}")

        return updated_playbook

    def _reflect_parallel(
        self, traces: list[dict], playbook: str
    ) -> list[dict]:
        """Reflect on traces in parallel, processing batch_size at a time."""
        reflections: list[dict] = []
        for batch_start in range(0, len(traces), self.batch_size):
            batch = traces[batch_start : batch_start + self.batch_size]
            batch_num = batch_start // self.batch_size + 1
            logger.info(
                f"Reflection batch {batch_num}: "
                f"{len(batch)} traces (offset {batch_start})"
            )
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                futures = {
                    pool.submit(self.reflector.reflect, trace, playbook): trace
                    for trace in batch
                }
                for future in as_completed(futures):
                    trace = futures[future]
                    try:
                        result = future.result()
                        if result.get("insights"):
                            reflections.append(result)
                    except Exception:
                        sid = trace.get("session_id", "unknown")
                        logger.error(
                            f"Reflection failed for session {sid}",
                            exc_info=True,
                        )
        return reflections
