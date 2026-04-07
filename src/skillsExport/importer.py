"""Skills importer: combines shared .retro/skills/ with local .claude/skills/.

Reads exported skills from .retro/skills/ and merges them into the project's
.claude/skills/ directory (where Claude Code discovers them), respecting
local customizations.

Usage:
    importer = SkillsImporter(working_dir="/path/to/repo")
    importer.import_skills()  # merges into .claude/skills/
"""

import logging
import shutil
import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class MergeStrategy(Enum):
    """How to handle skill name conflicts between retro and local."""
    LOCAL_FIRST = "local-first"   # keep local version, skip retro (default)
    RETRO_FIRST = "retro-first"  # overwrite local with retro version
    MERGE = "merge"              # append retro body after local body


@dataclass
class SkillEntry:
    """A single skill read from disk."""
    name: str
    path: Path
    frontmatter: dict
    body: str
    source: str  # "retro" or "local"


@dataclass
class MergeResult:
    """Summary of a skill import operation."""
    imported: list[str] = field(default_factory=list)    # new skills from retro
    skipped: list[str] = field(default_factory=list)     # conflicts kept local
    overwritten: list[str] = field(default_factory=list)  # conflicts replaced by retro
    merged: list[str] = field(default_factory=list)       # conflicts merged
    local_only: list[str] = field(default_factory=list)   # untouched local skills


class SkillsImporter:
    """Merges .retro/skills/ into .claude/skills/ for Claude Code discovery.

    The import is non-destructive by default (local-first strategy):
    - Skills only in retro → copied to .claude/skills/
    - Skills only in local → left untouched
    - Skills in both (name conflict) → local version kept, retro skipped
    """

    def __init__(
        self,
        working_dir: str,
        retro_dir: str | None = None,
        strategy: MergeStrategy = MergeStrategy.LOCAL_FIRST,
        sources: list[str] | None = None,
    ):
        self.working_dir = Path(working_dir)
        self.retro_dir = Path(retro_dir) if retro_dir else self.working_dir / ".retro"
        self.retro_skills_dir = self.retro_dir / "skills"
        self.local_skills_dir = self.working_dir / ".claude" / "skills"
        self.strategy = strategy
        # Additional source directories to import from (e.g., teammate paths)
        self.extra_sources = [Path(s) for s in (sources or [])]

    def import_skills(self, bundle_path: str | None = None) -> MergeResult:
        """Run the import. Returns a MergeResult summarizing what happened.

        Args:
            bundle_path: If provided, extract skills from a .tar.gz or .zip
                         bundle instead of (in addition to) .retro/skills/.
        """
        result = MergeResult()

        # Read skills from all sources
        retro_skills = self._read_skills_dir(self.retro_skills_dir, "retro")
        for src_dir in self.extra_sources:
            retro_skills.update(self._read_skills_dir(src_dir, str(src_dir)))

        # Unpack bundle if provided
        _cleanup_dir = None
        if bundle_path:
            bundle_dir, _cleanup_dir = self._unpack_bundle(bundle_path)
            if bundle_dir:
                bundle_skills = self._read_skills_dir(bundle_dir, f"bundle:{bundle_path}")
                print(f"[retro] Loaded {len(bundle_skills)} skills from {bundle_path}")
                retro_skills.update(bundle_skills)

        local_skills = self._read_skills_dir(self.local_skills_dir, "local")

        try:
            if not retro_skills:
                print("[retro] No shared skills found")
                if not bundle_path:
                    print("[retro] Hint: use -i <file> to import from a bundle")
                return result

            # Track local-only skills
            for name in local_skills:
                if name not in retro_skills:
                    result.local_only.append(name)

            # Ensure .claude/skills/ exists
            self.local_skills_dir.mkdir(parents=True, exist_ok=True)

            # Process each retro skill
            for name, retro_skill in sorted(retro_skills.items()):
                if name in local_skills:
                    self._handle_conflict(
                        retro_skill, local_skills[name], result
                    )
                else:
                    self._copy_skill(retro_skill, result)

            # Print summary
            self._print_summary(result)
            return result
        finally:
            if _cleanup_dir and _cleanup_dir.exists():
                shutil.rmtree(_cleanup_dir)

    def _unpack_bundle(self, bundle_path: str) -> tuple[Path | None, Path | None]:
        """Extract a .tar.gz or .zip bundle into a temp directory.

        Returns (skills_dir, cleanup_dir) where skills_dir is the path
        containing skill subdirectories, and cleanup_dir is the temp root
        to delete afterwards. Returns (None, None) on failure.
        """
        import tarfile
        import tempfile
        import zipfile

        bp = Path(bundle_path)
        if not bp.exists():
            print(f"[retro] Bundle not found: {bundle_path}")
            return None, None

        tmp = Path(tempfile.mkdtemp(prefix="retro-skills-"))

        try:
            if tarfile.is_tarfile(bp):
                with tarfile.open(bp, "r:*") as tf:
                    tf.extractall(tmp, filter="data")
            elif zipfile.is_zipfile(bp):
                with zipfile.ZipFile(bp, "r") as zf:
                    zf.extractall(tmp)
            else:
                print(f"[retro] Unsupported bundle format: {bundle_path}")
                shutil.rmtree(tmp)
                return None, None
        except Exception as e:
            print(f"[retro] Failed to extract bundle: {e}")
            shutil.rmtree(tmp)
            return None, None

        # The bundle may contain skill dirs directly or under a single
        # wrapper directory. Detect and normalize.
        children = [c for c in tmp.iterdir() if c.is_dir()]
        has_skill_md = any((c / "SKILL.md").exists() for c in children)

        if has_skill_md:
            return tmp, tmp

        # Check one level deeper (e.g., bundle extracted as skills/<name>/SKILL.md)
        if len(children) == 1:
            nested = [c for c in children[0].iterdir() if c.is_dir()]
            if any((c / "SKILL.md").exists() for c in nested):
                return children[0], tmp

        # Couldn't find skill structure
        print(f"[retro] Bundle doesn't contain valid skills (expected <name>/SKILL.md)")
        shutil.rmtree(tmp)
        return None, None

    def _read_skills_dir(self, skills_dir: Path, source: str) -> dict[str, SkillEntry]:
        """Read all skills from a directory into a name→SkillEntry map."""
        skills = {}
        if not skills_dir.is_dir():
            return skills

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                entry = self._parse_skill_file(skill_file, source)
                skills[entry.name] = entry
            except Exception as e:
                logger.warning(f"Failed to parse {skill_file}: {e}")

        return skills

    def _parse_skill_file(self, path: Path, source: str) -> SkillEntry:
        """Parse a SKILL.md into a SkillEntry."""
        content = path.read_text()
        frontmatter = {}
        body = content

        if content.startswith("---"):
            end = content.index("---", 3)
            frontmatter = yaml.safe_load(content[3:end]) or {}
            body = content[end + 3:].strip()

        name = frontmatter.get("name", path.parent.name)

        return SkillEntry(
            name=name,
            path=path,
            frontmatter=frontmatter,
            body=body,
            source=source,
        )

    def _copy_skill(self, retro_skill: SkillEntry, result: MergeResult) -> None:
        """Copy a retro skill to .claude/skills/ (no conflict)."""
        dest_dir = self.local_skills_dir / retro_skill.name
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Copy SKILL.md
        src_skill_dir = retro_skill.path.parent
        shutil.copy2(retro_skill.path, dest_dir / "SKILL.md")

        # Copy any supporting files (reference.md, scripts/, etc.)
        for item in src_skill_dir.iterdir():
            if item.name == "SKILL.md":
                continue
            dest = dest_dir / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
            else:
                shutil.copy2(item, dest)

        result.imported.append(retro_skill.name)

    def _handle_conflict(
        self,
        retro_skill: SkillEntry,
        local_skill: SkillEntry,
        result: MergeResult,
    ) -> None:
        """Handle a name conflict between retro and local skill."""
        if self.strategy == MergeStrategy.LOCAL_FIRST:
            result.skipped.append(retro_skill.name)

        elif self.strategy == MergeStrategy.RETRO_FIRST:
            self._copy_skill(retro_skill, result)
            # Move from imported to overwritten
            result.imported.pop()
            result.overwritten.append(retro_skill.name)

        elif self.strategy == MergeStrategy.MERGE:
            self._merge_skill(retro_skill, local_skill, result)

    def _merge_skill(
        self,
        retro_skill: SkillEntry,
        local_skill: SkillEntry,
        result: MergeResult,
    ) -> None:
        """Merge retro skill content into an existing local skill.

        Strategy: keep local frontmatter, append retro body sections that
        aren't already present in the local body.
        """
        # Use local frontmatter as base, overlay retro-only keys
        merged_fm = dict(local_skill.frontmatter)
        for key, val in retro_skill.frontmatter.items():
            if key not in merged_fm:
                merged_fm[key] = val

        # Merge bodies: keep local, append retro sections not in local
        local_sections = _extract_sections(local_skill.body)
        retro_sections = _extract_sections(retro_skill.body)

        new_sections = []
        for heading, content in retro_sections:
            # Check if this section heading already exists in local
            if not any(lh.lower() == heading.lower() for lh, _ in local_sections):
                new_sections.append((heading, content))

        if new_sections:
            merged_body = local_skill.body.rstrip()
            merged_body += "\n\n<!-- imported from .retro/skills/ -->\n"
            for heading, content in new_sections:
                merged_body += f"\n{heading}\n{content}\n"
        else:
            merged_body = local_skill.body

        # Write merged result
        dest_dir = self.local_skills_dir / local_skill.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        fm_str = yaml.dump(merged_fm, default_flow_style=False, sort_keys=False)
        merged_content = f"---\n{fm_str}---\n\n{merged_body.strip()}\n"
        (dest_dir / "SKILL.md").write_text(merged_content)

        # Copy any new supporting files from retro that don't exist locally
        retro_dir = retro_skill.path.parent
        for item in retro_dir.iterdir():
            if item.name == "SKILL.md":
                continue
            dest = dest_dir / item.name
            if not dest.exists():
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

        result.merged.append(retro_skill.name)

    def _print_summary(self, result: MergeResult) -> None:
        """Print a human-readable summary of the import."""
        total_retro = (
            len(result.imported) + len(result.skipped)
            + len(result.overwritten) + len(result.merged)
        )
        print(f"\n[retro] Import summary ({total_retro} shared skills → .claude/skills/)")

        if result.imported:
            print(f"  Imported ({len(result.imported)}):")
            for name in result.imported:
                print(f"    + {name}")

        if result.merged:
            print(f"  Merged ({len(result.merged)}):")
            for name in result.merged:
                print(f"    ~ {name}")

        if result.overwritten:
            print(f"  Overwritten ({len(result.overwritten)}):")
            for name in result.overwritten:
                print(f"    ! {name}")

        if result.skipped:
            print(f"  Skipped — local version kept ({len(result.skipped)}):")
            for name in result.skipped:
                print(f"    - {name}")

        if result.local_only:
            print(f"  Local-only — untouched ({len(result.local_only)}):")
            for name in result.local_only:
                print(f"    . {name}")

        dest_count = len(result.imported) + len(result.merged) + len(result.overwritten)
        if dest_count:
            print(f"\n[retro] {dest_count} skills now available in .claude/skills/")


def _extract_sections(body: str) -> list[tuple[str, str]]:
    """Extract markdown sections (## headings) from a skill body.

    Returns list of (heading_line, section_content) tuples.
    """
    sections = []
    lines = body.split("\n")
    current_heading = None
    current_content: list[str] = []

    for line in lines:
        if line.startswith("## ") or line.startswith("# "):
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_content).strip()))
            current_heading = line
            current_content = []
        else:
            current_content.append(line)

    if current_heading is not None:
        sections.append((current_heading, "\n".join(current_content).strip()))

    return sections
