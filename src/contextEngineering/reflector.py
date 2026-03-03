"""Reflector agent: analyzes conversation traces to extract insights."""

import logging

from src.utils.inference import call_llm_json  # provider selected via LLM_PROVIDER env var
from .config import DEFAULT_MODEL

logger = logging.getLogger(__name__)

REFLECTOR_SYSTEM = """\
You are a Reflector agent for context engineering. Your job is to analyze \
conversation traces between a user and an AI coding assistant (Claude Code) \
and extract actionable insights about what worked well, what failed, and \
what patterns emerge.

You will receive a batch of conversation traces. For each, analyze:
1. What the user asked for
2. How the assistant approached the task
3. Whether the approach was effective or had issues
4. What strategies worked well
5. What mistakes or anti-patterns appeared
6. What communication patterns were effective

Output a JSON object with:
{
  "insights": [
    {
      "category": "CODING_PATTERNS" | "WORKFLOW_STRATEGIES" | "COMMUNICATION" | "COMMON_MISTAKES" | "TOOL_USAGE",
      "observation": "What you observed in the trace",
      "recommendation": "Actionable recommendation for the playbook",
      "evidence": "Brief quote or reference from the trace"
    }
  ],
  "summary": "Brief overall summary of patterns across all traces"
}
"""

REFLECTOR_PROMPT = """\
Analyze the following conversation traces and extract insights for improving \
an AI coding assistant's playbook (system instructions).

Current playbook:
<playbook>
{playbook}
</playbook>

Conversation traces to analyze:
<traces>
{traces}
</traces>

Focus on insights that are NOT already covered in the current playbook. \
Look for recurring patterns across conversations. Be specific and actionable.\
"""


class Reflector:
    """Analyzes conversation traces to produce structured reflections."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def reflect(
        self, traces: list[dict], current_playbook: str
    ) -> dict:
        """Analyze traces and return structured insights.

        Args:
            traces: List of conversation trace dicts (session_id, messages).
            current_playbook: The current playbook content.

        Returns:
            Dict with 'insights' list and 'summary' string.
        """
        traces_text = self._format_traces(traces)
        prompt = REFLECTOR_PROMPT.format(
            playbook=current_playbook,
            traces=traces_text,
        )

        result = call_llm_json(
            system=REFLECTOR_SYSTEM,
            prompt=prompt,
            model=self.model,
        )

        insights = result.get("insights", [])
        logger.info(f"Reflector produced {len(insights)} insights")
        return result

    def _format_traces(self, traces: list[dict]) -> str:
        """Format conversation traces into a readable text block."""
        parts = []
        for trace in traces:
            parts.append(f"--- Session: {trace.get('session_id', 'unknown')} ---")
            for msg in trace.get("messages", []):
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                # Truncate very long messages to keep within context
                if len(content) > 2000:
                    content = content[:2000] + "\n... [truncated]"
                parts.append(f"[{role}]: {content}")
            parts.append("")
        return "\n".join(parts)
