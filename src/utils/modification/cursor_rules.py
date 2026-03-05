"""Writer for Cursor's project rules (.cursor/rules/retro.mdc).

Cursor uses .cursor/rules/*.mdc files (since v0.45). Each .mdc file has
optional YAML frontmatter followed by markdown content. We write a single
dedicated file: .cursor/rules/retro.mdc

Reference: https://cursor.com/docs/context/rules
"""

from pathlib import Path
from .base import BaseMarkdownWriter, RETRO_START, RETRO_END

_FRONTMATTER = """\
---
description: RetroCode auto-generated playbook from real session traces
alwaysApply: true
---
"""


class CursorRulesWriter(BaseMarkdownWriter):
    agent_name = "cursor"

    def __init__(self, project_dir: str):
        # Always writes to <project_dir>/.cursor/rules/retro.mdc
        path = Path(project_dir) / ".cursor" / "rules" / "retro.mdc"
        super().__init__(str(path))

    def write(self, playbook: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        block = f"{RETRO_START}\n# Playbook\n{playbook.strip()}\n{RETRO_END}"

        if self.path.exists():
            existing = self.path.read_text()
            # Preserve frontmatter if present; only replace retro block
            if RETRO_START in existing and RETRO_END in existing:
                before = existing[: existing.index(RETRO_START)]
                after = existing[existing.index(RETRO_END) + len(RETRO_END):]
                self.path.write_text(before + block + after)
                return
            # File exists but has no retro block — append after existing content
            sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
            self.path.write_text(existing + sep + block + "\n")
        else:
            # New file: write frontmatter + retro block
            self.path.write_text(_FRONTMATTER + "\n" + block + "\n")
