"""Context engineering engine: orchestrates the reflect-curate loop."""

import logging
from typing import Optional

from .config import DEFAULT_MODEL, MAX_PLAYBOOK_BULLETS
from .reflector import Reflector
from .curator import Curator, load_playbook, save_playbook
from .trace_ingester import Conversation
from src.utils.modification import ClaudeMdWriter, CursorRulesWriter, AgentsMdWriter
from src.utils.modification.base import BaseMarkdownWriter

logger = logging.getLogger(__name__)

_WRITER_REGISTRY: dict[str, type[BaseMarkdownWriter]] = {
    "claude-code": ClaudeMdWriter,
    "cursor":      CursorRulesWriter,
    "codex":       AgentsMdWriter,
}


class ContextEngine:
    """Orchestrates the context engineering pipeline.

    Called from the main loop after trace ingestion confirms there are
    enough new conversation rounds to warrant a playbook update.
    """

    def __init__(
        self,
        playbook_path: str = "playbook.txt",
        model: str = DEFAULT_MODEL,
        claude_md_path: Optional[str] = None,
        max_bullets: int = MAX_PLAYBOOK_BULLETS,
        writers: Optional[list[BaseMarkdownWriter]] = None,
    ):
        self.playbook_path = playbook_path
        self.claude_md_path = claude_md_path
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

        # Step 1: Reflect on the new traces
        logger.info(f"Reflecting on {len(traces)} new conversations...")
        reflection = self.reflector.reflect(traces, playbook)

        insights = reflection.get("insights", [])
        if not insights:
            logger.info("No insights extracted, playbook unchanged")
            return playbook

        # Step 2: Curate playbook updates
        logger.info(f"Curating {len(insights)} insights into playbook...")
        updated_playbook, new_next_id = self.curator.curate(
            playbook, reflection, next_global_id
        )

        # Step 3: Save playbook
        ops = self.curator.last_operations if hasattr(self.curator, "last_operations") else []
        added = sum(1 for o in ops if o.get("type") == "ADD")
        deleted = sum(1 for o in ops if o.get("type") == "DELETE")
        save_playbook(self.playbook_path, updated_playbook)
        logger.info(f"Playbook updated: +{added} added, -{deleted} deleted")

        # Step 4: Sync to all configured output targets
        for writer in self.writers:
            writer.write(updated_playbook)
            logger.info(f"{writer.agent_name} rules updated: {writer.path}")

        return updated_playbook
