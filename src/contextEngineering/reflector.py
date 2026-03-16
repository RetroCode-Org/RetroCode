"""Reflector agent: analyzes conversation traces to extract insights."""

import logging

from src.utils.inference import call_llm_json  # provider selected via LLM_PROVIDER env var
from .config import DEFAULT_MODEL

logger = logging.getLogger(__name__)

REFLECTOR_SYSTEM = """\
You are a Reflector agent for context engineering. Your job is to analyze \
a single conversation trace between a user and an AI coding assistant \
and extract structured skills — lessons learned from misunderstandings, \
corrections, or friction between the user and the AI.

Focus on moments where the AI misunderstood the user:
- User said "no", corrected the AI, or asked it to undo something
- AI made assumptions the user didn't want
- AI over-engineered, under-delivered, or missed the point
- Communication broke down (AI explained instead of acting, or acted without asking)
- AI used the wrong approach and had to be redirected

Each insight should be a SKILL: a reusable rule the AI should follow next time.

Output a JSON object with:
{
  "insights": [
    {
      "category": "CODING_PATTERNS" | "WORKFLOW_STRATEGIES" | "COMMUNICATION" | "COMMON_MISTAKES" | "TOOL_USAGE",
      "title": "Short name for this skill (3-6 words)",
      "trigger": "When does this rule apply? (situation/context)",
      "instruction": "What should the AI do? (specific action)",
      "why": "What went wrong that prompted this? (the misunderstanding)",
      "evidence": "Brief quote or reference from the trace"
    }
  ],
  "summary": "Brief summary of misunderstandings found in this conversation"
}

Rules:
- Only extract insights where there was clear friction or misunderstanding
- Each skill must have all fields: title, trigger, instruction, why
- Be specific — "when editing React components" not "when coding"
- The 'why' field must reference what actually happened in the conversation
"""

REFLECTOR_PROMPT = """\
Analyze the following conversation trace and extract insights for improving \
an AI coding assistant's playbook (system instructions).

Current playbook:
<playbook>
{playbook}
</playbook>

Conversation trace (session: {session_id}):
<trace>
{trace}
</trace>

Focus on insights that are NOT already covered in the current playbook. \
Be specific and actionable.\
"""


class Reflector:
    """Analyzes conversation traces to produce structured reflections."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def reflect(
        self, trace: dict, current_playbook: str
    ) -> dict:
        """Analyze a single trace and return structured insights.

        Args:
            trace: A conversation trace dict (session_id, messages).
            current_playbook: The current playbook content.

        Returns:
            Dict with 'insights' list and 'summary' string.
        """
        session_id = trace.get("session_id", "unknown")
        trace_text = self._format_trace(trace)
        prompt = REFLECTOR_PROMPT.format(
            playbook=current_playbook,
            session_id=session_id,
            trace=trace_text,
        )

        result = call_llm_json(
            system=REFLECTOR_SYSTEM,
            prompt=prompt,
            model=self.model,
        )

        insights = result.get("insights", [])
        logger.info(
            f"Reflector produced {len(insights)} insights for session {session_id}"
        )
        return result

    def _format_trace(self, trace: dict) -> str:
        """Format a single conversation trace into a readable text block."""
        parts = []
        for msg in trace.get("messages", []):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            # Truncate very long messages to keep within context
            if len(content) > 2000:
                content = content[:2000] + "\n... [truncated]"
            parts.append(f"[{role}]: {content}")
        return "\n".join(parts)
