"""LLM-based skill content generator.

Takes codebase analysis + playbook insights and produces structured
SKILL.md content for each identified skill theme.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from src.utils.inference import call_llm_json, call_llm
from src.contextEngineering.config import DEFAULT_MODEL

logger = logging.getLogger(__name__)


@dataclass
class SkillSpec:
    """Specification for a single skill to generate."""
    name: str
    description: str
    category: str  # "workflow", "plugin", "debug", "reference", "review"
    related_bullets: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    user_invocable: bool = True
    disable_model_invocation: bool = False
    allowed_tools: str = ""
    context: str = ""  # "fork" for subagent, "" for inline


@dataclass
class GeneratedSkill:
    """A fully generated skill ready to write to disk."""
    name: str
    frontmatter: dict
    body: str
    supporting_files: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

PLANNER_SYSTEM = """\
You are a skill architect for AI coding agents. Given a codebase analysis \
and a playbook of learned rules, you identify the most valuable shareable \
skills to generate for team collaboration.

A "skill" is a structured instruction file (SKILL.md) that encodes \
non-obvious repo knowledge — things a new contributor or AI agent cannot \
easily discover from reading the code alone.

Good skills:
- Encode institutional knowledge (why decisions were made, not just what)
- Cover common workflows that have non-obvious steps
- Document extension points with concrete examples
- Prevent known mistakes with clear guardrails
- Are specific to THIS repo, not generic coding advice

Bad skills:
- Restate what linters/formatters enforce
- Duplicate what's obvious from reading the code
- Are too vague to be actionable
- Cover one-time operations that won't recur

Output a JSON object:
{
  "skills": [
    {
      "name": "kebab-case-name",
      "description": "What this skill does (< 200 chars, third person)",
      "category": "workflow|plugin|debug|reference|review",
      "related_bullets": ["[coding-00001]", ...],
      "related_files": ["src/path/to/file.py", ...],
      "user_invocable": true,
      "reasoning": "Why this skill is valuable for the team"
    }
  ]
}

Generate 6-12 skills covering the most important knowledge for collaborators.\
"""

PLANNER_PROMPT = """\
Analyze this codebase and playbook to identify valuable shareable skills.

<codebase_analysis>
{codebase_analysis}
</codebase_analysis>

<playbook>
{playbook}
</playbook>

{trace_summary}

Identify skills that would most help someone new to this repo be productive \
quickly, AND help an AI agent working on this repo avoid common mistakes.\
"""

GENERATOR_SYSTEM = """\
You are a skill author for AI coding agents. You write SKILL.md files that \
encode actionable, repo-specific knowledge.

Your output must be the BODY of a SKILL.md file (markdown, no frontmatter — \
that is added separately). The body should:

1. Start with a clear one-sentence purpose
2. Include step-by-step instructions where applicable
3. Reference specific files, classes, and functions in the repo
4. Include code snippets or templates when they save time
5. Mention common pitfalls and how to avoid them
6. Be concise — under 300 lines, ideally under 150

Write in imperative mood ("Do X", "Run Y", not "You should do X").

Do NOT include YAML frontmatter — only the markdown body.\
"""

GENERATOR_PROMPT = """\
Write the SKILL.md body for this skill:

Name: {name}
Description: {description}
Category: {category}

Related playbook rules:
{related_bullets}

Key files in this repo:
{related_files}

Codebase context:
{codebase_context}

Write a skill that encodes non-obvious knowledge specific to this repo. \
Be concrete — reference real file paths, class names, and patterns.\
"""


class SkillGenerator:
    """Generates skill files from codebase analysis and playbook."""

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def plan_skills(
        self,
        codebase_analysis: str,
        playbook: str,
        trace_summary: str = "",
    ) -> list[SkillSpec]:
        """Use LLM to identify which skills to generate."""
        trace_section = ""
        if trace_summary:
            trace_section = f"<trace_insights>\n{trace_summary}\n</trace_insights>"

        prompt = PLANNER_PROMPT.format(
            codebase_analysis=codebase_analysis,
            playbook=playbook,
            trace_summary=trace_section,
        )

        result = call_llm_json(
            system=PLANNER_SYSTEM,
            prompt=prompt,
            model=self.model,
        )

        specs = []
        for skill_data in result.get("skills", []):
            specs.append(SkillSpec(
                name=skill_data["name"],
                description=skill_data["description"],
                category=skill_data.get("category", "reference"),
                related_bullets=skill_data.get("related_bullets", []),
                related_files=skill_data.get("related_files", []),
                user_invocable=skill_data.get("user_invocable", True),
            ))

        logger.info(f"Planner identified {len(specs)} skills to generate")
        return specs

    def generate_skill(
        self,
        spec: SkillSpec,
        codebase_context: str,
    ) -> GeneratedSkill:
        """Generate the full content for a single skill."""
        related_bullets_text = "\n".join(
            f"  - {b}" for b in spec.related_bullets
        ) or "  (none)"
        related_files_text = "\n".join(
            f"  - {f}" for f in spec.related_files
        ) or "  (none)"

        prompt = GENERATOR_PROMPT.format(
            name=spec.name,
            description=spec.description,
            category=spec.category,
            related_bullets=related_bullets_text,
            related_files=related_files_text,
            codebase_context=codebase_context,
        )

        body = call_llm(
            system=GENERATOR_SYSTEM,
            prompt=prompt,
            model=self.model,
        )

        # Clean up: remove any accidental frontmatter
        body = body.strip()
        if body.startswith("---"):
            # Strip frontmatter if the LLM added it anyway
            end = body.find("---", 3)
            if end > 0:
                body = body[end + 3:].strip()

        # Build frontmatter
        frontmatter = {
            "name": spec.name,
            "description": spec.description,
        }
        if not spec.user_invocable:
            frontmatter["user-invocable"] = False
        if spec.disable_model_invocation:
            frontmatter["disable-model-invocation"] = True
        if spec.allowed_tools:
            frontmatter["allowed-tools"] = spec.allowed_tools
        if spec.context:
            frontmatter["context"] = spec.context

        return GeneratedSkill(
            name=spec.name,
            frontmatter=frontmatter,
            body=body,
        )

    def generate_all(
        self,
        specs: list[SkillSpec],
        codebase_context: str,
    ) -> list[GeneratedSkill]:
        """Generate all skills from specs. Sequential to avoid rate limits."""
        skills = []
        for i, spec in enumerate(specs, 1):
            logger.info(f"Generating skill {i}/{len(specs)}: {spec.name}")
            try:
                skill = self.generate_skill(spec, codebase_context)
                skills.append(skill)
            except Exception as e:
                logger.error(f"Failed to generate skill {spec.name}: {e}")
        return skills
