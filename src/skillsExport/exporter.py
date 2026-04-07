"""Skills exporter: orchestrates codebase analysis -> skill generation -> file output.

Usage:
    exporter = SkillsExporter(working_dir="/path/to/repo")
    exporter.export()  # writes to .retro/skills/
"""

import logging
import re
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.contextEngineering.config import DEFAULT_MODEL
from src.contextEngineering.curator import load_playbook
from src.contextEngineering.trace_ingester import Conversation, TraceState, TRACE_STATE_FILE
from .analyzer import CodebaseAnalyzer
from .generator import SkillGenerator, SkillSpec, GeneratedSkill

logger = logging.getLogger(__name__)

SKILLS_DIR = "skills"

# Skills that are always generated from codebase structure alone (no LLM needed)
# These serve as a fallback when no traces/playbook exist yet.
STATIC_SKILL_CATEGORIES = {
    "plugin": "Extension points and how to add new implementations",
    "workflow": "Common development workflows and processes",
    "debug": "Debugging, troubleshooting, and operational knowledge",
    "reference": "Architecture and codebase reference for new contributors",
    "review": "Code review patterns specific to this repo",
}


class SkillsExporter:
    """Orchestrates the full skills export pipeline.

    Pipeline:
        1. Analyze codebase structure (ABCs, modules, CLI, tests)
        2. Load playbook bullets (learned from traces)
        3. Optionally summarize trace insights
        4. Plan which skills to generate (LLM)
        5. Generate SKILL.md content for each (LLM)
        6. Write to .retro/skills/
    """

    def __init__(
        self,
        working_dir: str,
        retro_dir: str | None = None,
        playbook_path: str | None = None,
        model: str = DEFAULT_MODEL,
        no_llm: bool = False,
    ):
        self.working_dir = Path(working_dir)
        self.retro_dir = Path(retro_dir) if retro_dir else self.working_dir / ".retro"
        self.playbook_path = playbook_path or str(self.retro_dir / "playbook.txt")
        self.skills_dir = self.retro_dir / SKILLS_DIR
        self.model = model
        self.no_llm = no_llm
        self.analyzer = CodebaseAnalyzer(working_dir)
        self.generator = SkillGenerator(model=model)

    def export(self, bundle_path: str | None = None) -> list[str]:
        """Run the full export pipeline. Returns list of generated skill paths.

        Args:
            bundle_path: If provided, also package skills into a portable
                         .tar.gz or .zip bundle for sharing with teammates.
        """
        print(f"[retro] Analyzing codebase at {self.working_dir}")
        analysis = self.analyzer.analyze()
        codebase_context = self.analyzer.format_for_llm(analysis)

        # Load playbook
        playbook = ""
        try:
            playbook, _ = load_playbook(self.playbook_path)
            if playbook.strip():
                print(f"[retro] Loaded playbook from {self.playbook_path}")
        except Exception:
            print("[retro] No existing playbook found, generating skills from codebase analysis only")

        # Summarize trace insights if available
        trace_summary = self._summarize_traces()

        # Plan skills
        if self.no_llm:
            print("[retro] --no-llm mode: generating skills from static templates")
            specs = self._static_skill_specs(analysis, playbook)
        else:
            print(f"[retro] Planning skills with {self.model}...")
            specs = self.generator.plan_skills(codebase_context, playbook, trace_summary)

        if not specs:
            print("[retro] No skills identified to generate")
            return []

        print(f"[retro] Generating {len(specs)} skills:")
        for spec in specs:
            print(f"  - {spec.name}: {spec.description[:80]}")

        # Generate skill content
        if self.no_llm:
            skills = self._generate_static_skills(specs, analysis)
        else:
            skills = self.generator.generate_all(specs, codebase_context)

        # Write to disk
        paths = self._write_skills(skills)

        print(f"\n[retro] Exported {len(paths)} skills to {self.skills_dir}/")
        for p in paths:
            print(f"  - {p}")

        # Bundle for sharing
        if bundle_path:
            self.bundle(bundle_path)

        return paths

    def bundle(self, output_path: str) -> str:
        """Package .retro/skills/ into a portable archive for sharing.

        Supports .tar.gz (default) and .zip based on file extension.
        Returns the resolved output path.
        """
        import tarfile
        import zipfile

        output = Path(output_path).resolve()
        if not self.skills_dir.is_dir() or not any(self.skills_dir.iterdir()):
            print("[retro] No skills to bundle")
            return ""

        if output.suffix == ".zip" or str(output).endswith(".zip"):
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in self.skills_dir.rglob("*"):
                    if file.is_file():
                        arcname = file.relative_to(self.skills_dir)
                        zf.write(file, arcname)
        else:
            # Default to tar.gz
            if not str(output).endswith((".tar.gz", ".tgz")):
                output = Path(str(output) + ".tar.gz")
            with tarfile.open(output, "w:gz") as tf:
                for file in self.skills_dir.rglob("*"):
                    if file.is_file():
                        arcname = file.relative_to(self.skills_dir)
                        tf.add(file, arcname)

        print(f"[retro] Bundled skills -> {output}")
        return str(output)

    def _summarize_traces(self) -> str:
        """Build a brief summary of trace patterns if traces exist."""
        state_path = str(self.retro_dir / TRACE_STATE_FILE)
        try:
            state = TraceState.load(state_path)
            n = len(state.processed_session_ids)
            if n > 0:
                return (
                    f"The team has processed {n} conversation sessions. "
                    f"Last run: {state.last_run_timestamp or 'unknown'}."
                )
        except Exception:
            pass
        return ""

    def _static_skill_specs(self, analysis, playbook: str) -> list[SkillSpec]:
        """Generate skill specs without LLM, based on codebase structure."""
        specs = []

        # One skill per ABC (plugin extension points)
        for abc in analysis.abcs:
            name = f"add-{abc.name.lower().replace('base', '').replace('abc', '').strip()}"
            if not name or name == "add-":
                name = f"extend-{abc.name.lower()}"
            specs.append(SkillSpec(
                name=name,
                description=f"How to implement a new {abc.name} subclass",
                category="plugin",
                related_files=[abc.file_path] + [
                    impl.split("(")[1].rstrip(")") for impl in abc.implementations
                    if "(" in impl
                ],
            ))

        # Codebase guide
        specs.append(SkillSpec(
            name="codebase-guide",
            description="Architecture reference and orientation for new contributors",
            category="reference",
            user_invocable=False,
        ))

        # Debug/ops skill if daemon-related code exists
        if any("daemon" in cmd.help_text.lower() or "up" in cmd.flag
               for cmd in analysis.cli_commands):
            specs.append(SkillSpec(
                name="debug-daemon",
                description="Debugging and troubleshooting the background daemon",
                category="debug",
            ))

        # Extract bullet IDs for association
        if playbook:
            bullet_ids = re.findall(r"\[[\w]+-\d+\]", playbook)
            for spec in specs:
                # Associate bullets mentioning related keywords
                for bid in bullet_ids:
                    bid_line = ""
                    for line in playbook.splitlines():
                        if bid in line:
                            bid_line = line
                            break
                    if any(kw in bid_line.lower() for kw in [spec.category, spec.name.replace("-", " ")]):
                        spec.related_bullets.append(bid)

        return specs

    def _generate_static_skills(
        self, specs: list[SkillSpec], analysis
    ) -> list[GeneratedSkill]:
        """Generate skills without LLM using templates."""
        skills = []
        for spec in specs:
            body = f"# {spec.name}\n\n{spec.description}\n\n"
            body += "## Related Files\n\n"
            for f in spec.related_files:
                body += f"- `{f}`\n"
            if spec.related_bullets:
                body += "\n## Related Playbook Rules\n\n"
                for b in spec.related_bullets:
                    body += f"- {b}\n"

            frontmatter = {
                "name": spec.name,
                "description": spec.description,
            }
            if not spec.user_invocable:
                frontmatter["user-invocable"] = False

            skills.append(GeneratedSkill(
                name=spec.name,
                frontmatter=frontmatter,
                body=body,
            ))
        return skills

    def _write_skills(self, skills: list[GeneratedSkill]) -> list[str]:
        """Write generated skills to .retro/skills/<name>/SKILL.md."""
        paths = []
        for skill in skills:
            skill_dir = self.skills_dir / skill.name
            skill_dir.mkdir(parents=True, exist_ok=True)

            # Build SKILL.md
            content = self._render_skill_md(skill)
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(content)
            paths.append(str(skill_path.relative_to(self.retro_dir.parent)))

            # Write any supporting files
            for filename, file_content in skill.supporting_files.items():
                (skill_dir / filename).write_text(file_content)

        return paths

    def _render_skill_md(self, skill: GeneratedSkill) -> str:
        """Render a GeneratedSkill into a SKILL.md file with frontmatter."""
        fm = yaml.dump(skill.frontmatter, default_flow_style=False, sort_keys=False)
        return f"---\n{fm}---\n\n{skill.body}\n"
