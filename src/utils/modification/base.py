"""Base class for agent markdown writers."""

from abc import ABC, abstractmethod
from pathlib import Path

RETRO_START = "<!-- retro:start -->"
RETRO_END = "<!-- retro:end -->"


class BaseMarkdownWriter(ABC):
    """Writes/updates a playbook block inside a coding agent's markdown file."""

    def __init__(self, path: str):
        self.path = Path(path)

    def write(self, playbook: str) -> None:
        """Insert or replace the retro block in the markdown file."""
        existing = self.path.read_text() if self.path.exists() else ""
        block = f"{RETRO_START}\n# Playbook\n{playbook.strip()}\n{RETRO_END}"

        if RETRO_START in existing and RETRO_END in existing:
            before = existing[: existing.index(RETRO_START)]
            after = existing[existing.index(RETRO_END) + len(RETRO_END):]
            updated = before + block + after
        else:
            sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
            updated = existing + sep + block + "\n"

        self.path.write_text(updated)

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Human-readable name of the coding agent."""
        ...
