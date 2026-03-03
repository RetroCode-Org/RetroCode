"""Writer for Claude Code's CLAUDE.md."""

from .base import BaseMarkdownWriter


class ClaudeMdWriter(BaseMarkdownWriter):
    agent_name = "claude-code"
