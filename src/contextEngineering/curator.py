"""Curator agent: updates the playbook based on reflector insights."""

import re
import logging

from src.utils.inference import call_llm_json  # provider selected via LLM_PROVIDER env var
from .config import MAX_PLAYBOOK_BULLETS, DEFAULT_PLAYBOOK, SECTION_PREFIXES, DEFAULT_MODEL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

CURATOR_SYSTEM = """\
You are a Curator agent for context engineering. Your job is to update a \
playbook (system instructions document) based on insights extracted from \
conversation trace analysis.

The playbook is a structured document with sections containing numbered \
bullet points. Each bullet has a unique ID like [pat-00001].

You must output a JSON object with:
{
  "reasoning": "Your reasoning about what to add/modify/remove",
  "operations": [
    {
      "type": "ADD",
      "section": "SECTION_NAME",
      "content": "The new bullet point content"
    },
    {
      "type": "MODIFY",
      "id": "[pat-00001]",
      "content": "Replacement content for this bullet"
    },
    {
      "type": "DELETE",
      "id": "[pat-00001]"
    }
  ]
}

Valid sections: CODING_PATTERNS, WORKFLOW_STRATEGIES, COMMUNICATION, \
COMMON_MISTAKES, TOOL_USAGE, OTHERS

Rules:
- ADD new insights not already covered. Each bullet should be specific, \
actionable, and concise (1-2 sentences). Only add insights well-supported by evidence.
- MODIFY bullets that are partially correct but need updating or sharpening.
- DELETE bullets that are proven wrong, directly contradicted by a newer insight, \
or too vague to be useful. Be conservative — only delete when clearly warranted.
- Prefer quality over quantity. The playbook has a maximum bullet limit; \
if it is near capacity, prefer MODIFY or DELETE over ADD.
- If the playbook has EXCEEDED the cap, you MUST reduce the count: consolidate overlapping \
bullets (MODIFY to merge, DELETE the redundant), remove lowest-value bullets, or combine \
related insights. Do not add new bullets until under the cap. The curator updates the playbook; \
we do not auto-prune.
"""

CURATOR_PROMPT = """\
Update the playbook based on reflections from {num_reflections} conversation traces.

Current playbook:
<playbook>
{playbook}
</playbook>

Reflections:
<reflections>
{reflections}
</reflections>

Current playbook stats:
- Total bullets: {total_bullets} / {max_bullets} max{exceeded_note}
- Sections: {sections}

Look for patterns that recur across multiple reflections — these are higher-confidence. \
Add genuinely new insights, modify stale ones, and delete contradicted ones. Be selective.\
"""

class Curator:
    """Updates the playbook based on reflector insights."""

    def __init__(self, model: str = DEFAULT_MODEL, max_bullets: int = MAX_PLAYBOOK_BULLETS):
        self.model = model
        self.max_bullets = max_bullets
        self.last_operations: list[dict] = []

    def curate(
        self,
        current_playbook: str,
        reflections: list[dict],
        next_global_id: int,
    ) -> tuple[str, int]:
        """Update the playbook based on multiple per-trace reflections.

        Args:
            current_playbook: The current playbook text.
            reflections: List of Reflector outputs (each has 'insights' + 'summary').
            next_global_id: Next available global bullet ID counter.

        Returns:
            Tuple of (updated_playbook, new_next_global_id).
        """
        stats = get_playbook_stats(current_playbook)
        reflections_text = self._format_reflections(reflections)
        exceeded = stats["total_bullets"] > self.max_bullets
        exceeded_note = (
            " — CAP EXCEEDED: you must reduce the count (consolidate, merge, or delete) before adding new bullets"
            if exceeded
            else ""
        )

        prompt = CURATOR_PROMPT.format(
            playbook=current_playbook,
            reflections=reflections_text,
            num_reflections=len(reflections),
            total_bullets=stats["total_bullets"],
            max_bullets=self.max_bullets,
            exceeded_note=exceeded_note,
            sections=", ".join(stats["sections"]),
        )

        result = call_llm_json(
            system=CURATOR_SYSTEM,
            prompt=prompt,
            model=self.model,
        )

        operations = result.get("operations", [])
        logger.info(f"Curator reasoning: {result.get('reasoning', '')[:200]}")
        logger.info(f"Curator produced {len(operations)} operations")

        self.last_operations = operations
        updated_playbook, next_global_id = apply_operations(
            current_playbook, operations, next_global_id
        )
        # No auto-pruning: curator is responsible for keeping under cap
        return updated_playbook, next_global_id

    def _format_reflections(self, reflections: list[dict]) -> str:
        """Format multiple reflections into a single text block for the curator."""
        parts = []
        for idx, reflection in enumerate(reflections, 1):
            parts.append(f"=== Reflection {idx} ===")
            summary = reflection.get("summary", "")
            if summary:
                parts.append(f"Summary: {summary}")
            for i, insight in enumerate(reflection.get("insights", []), 1):
                parts.append(
                    f"  {i}. [{insight.get('category', 'UNKNOWN')}] "
                    f"{insight.get('recommendation', '')}\n"
                    f"     Evidence: {insight.get('evidence', 'N/A')}"
                )
            parts.append("")
        return "\n".join(parts)


def get_playbook_stats(playbook: str) -> dict:
    """Extract statistics from the current playbook."""
    sections = re.findall(r"^## (\w+)", playbook, re.MULTILINE)
    bullets = re.findall(r"\[[\w]+-\d+\]", playbook)
    return {
        "total_bullets": len(bullets),
        "sections": sections,
    }


def apply_operations(
    playbook: str, operations: list[dict], next_global_id: int
) -> tuple[str, int]:
    """Apply ADD / MODIFY / DELETE operations to the playbook."""
    for op in operations:
        op_type = op.get("type")

        if op_type == "ADD":
            section = op.get("section", "OTHERS")
            content = op.get("content", "").strip()
            if not content:
                continue

            prefix = SECTION_PREFIXES.get(section, "oth")
            bullet_id = f"[{prefix}-{next_global_id:05d}]"
            next_global_id += 1
            bullet_line = f"{bullet_id} {content}"

            section_pattern = rf"(## {re.escape(section)})"
            match = re.search(section_pattern, playbook)
            if match:
                insert_pos = match.end()
                playbook = (
                    playbook[:insert_pos] + f"\n{bullet_line}" + playbook[insert_pos:]
                )
            else:
                playbook = playbook.rstrip() + f"\n\n## {section}\n{bullet_line}\n"

        elif op_type == "MODIFY":
            bullet_id = op.get("id", "").strip()
            content = op.get("content", "").strip()
            if not bullet_id or not content:
                continue
            lines = playbook.splitlines(keepends=True)
            new_lines = []
            found = False
            for line in lines:
                if bullet_id in line:
                    new_lines.append(f"{bullet_id} {content}\n")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                logger.warning(f"MODIFY: bullet {bullet_id} not found in playbook")
            else:
                logger.info(f"Modified bullet {bullet_id}")
                playbook = "".join(new_lines)

        elif op_type == "DELETE":
            bullet_id = op.get("id", "").strip()
            if not bullet_id:
                continue
            lines = playbook.splitlines(keepends=True)
            new_lines = [l for l in lines if bullet_id not in l]
            if len(new_lines) == len(lines):
                logger.warning(f"DELETE: bullet {bullet_id} not found in playbook")
            else:
                logger.info(f"Deleted bullet {bullet_id}")
                playbook = "".join(new_lines)

        else:
            logger.warning(f"Unsupported operation type: {op_type}")

    return playbook, next_global_id


def load_playbook(path: str) -> tuple[str, int]:
    """Load a playbook from file, returning content and next global ID."""
    try:
        with open(path) as f:
            content = f.read()
    except FileNotFoundError:
        content = DEFAULT_PLAYBOOK

    ids = re.findall(r"\[\w+-(\d+)\]", content)
    next_id = max(int(i) for i in ids) + 1 if ids else 1
    return content, next_id


def save_playbook(path: str, content: str):
    """Save the playbook to file."""
    with open(path, "w") as f:
        f.write(content)
