"""Fallback defaults for the context engineering pipeline.

At runtime these are overridden by values from retro_config.yaml in the
user's project directory, loaded via src.retro_config.load_config().
"""

MAX_PLAYBOOK_BULLETS: int = 40
DEFAULT_MODEL: str = "gpt-5.2"
SECTION_PREFIXES: dict[str, str] = {
    "CODING_PATTERNS": "coding",
    "WORKFLOW_STRATEGIES": "workflow",
    "COMMUNICATION": "communication",
    "COMMON_MISTAKES": "mistake",
    "TOOL_USAGE": "tool",
    "OTHERS": "other",
}
DEFAULT_PLAYBOOK: str = """\
## CODING_PATTERNS

## WORKFLOW_STRATEGIES

## COMMUNICATION

## COMMON_MISTAKES

## TOOL_USAGE
"""

