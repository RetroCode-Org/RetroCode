"""Writer for OpenAI Codex CLI's AGENTS.md.

Codex reads AGENTS.md from the project root (and hierarchical overrides via
AGENTS.override.md). We write into the project-root AGENTS.md using the same
retro marker block used for CLAUDE.md.

Reference: https://developers.openai.com/codex/guides/agents-md/
"""

from pathlib import Path
from .base import BaseMarkdownWriter


class AgentsMdWriter(BaseMarkdownWriter):
    agent_name = "codex"

    def __init__(self, project_dir: str):
        # Always writes to <project_dir>/AGENTS.md
        path = Path(project_dir) / "AGENTS.md"
        super().__init__(str(path))
