"""Skills importer: combines shared .retro/skills/ with local .claude/skills/.

Reads exported skills from .retro/skills/ and merges them into the project's
.claude/skills/ directory (where Claude Code discovers them), respecting
local customizations.

Usage:
    importer = SkillsImporter(working_dir="/path/to/repo")
    importer.import_skills()  # merges into .claude/skills/
"""

import difflib
import logging
import shutil
import sys
import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class MergeStrategy(Enum):
    """How to handle skill name conflicts between retro and local."""
    LOCAL_FIRST = "local-first"       # keep local version, skip retro (default)
    RETRO_FIRST = "retro-first"       # overwrite local with retro version
    MERGE = "merge"                   # smart merge: sections + frontmatter
    INTERACTIVE = "interactive"       # per-skill prompt with diff view


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
    imported: list[str] = field(default_factory=list)     # new skills from retro
    skipped: list[str] = field(default_factory=list)      # conflicts kept local
    overwritten: list[str] = field(default_factory=list)   # conflicts replaced by retro
    merged: list[str] = field(default_factory=list)        # conflicts merged
    local_only: list[str] = field(default_factory=list)    # untouched local skills


class SkillsImporter:
    """Merges .retro/skills/ into .claude/skills/ for Claude Code discovery.

    The import is non-destructive by default (local-first strategy):
    - Skills only in retro -> copied to .claude/skills/
    - Skills only in local -> left untouched
    - Skills in both (name conflict) -> local version kept, retro skipped
    """

    def __init__(
        self,
        working_dir: str,
        retro_dir: str | None = None,
        strategy: MergeStrategy = MergeStrategy.LOCAL_FIRST,
        sources: list[str] | None = None,
        dry_run: bool = False,
    ):
        self.working_dir = Path(working_dir)
        self.retro_dir = Path(retro_dir) if retro_dir else self.working_dir / ".retro"
        self.retro_skills_dir = self.retro_dir / "skills"
        self.local_skills_dir = self.working_dir / ".claude" / "skills"
        self.strategy = strategy
        self.dry_run = dry_run
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

            if self.dry_run:
                print("[retro] DRY RUN — no files will be written\n")

            # Track local-only skills
            for name in local_skills:
                if name not in retro_skills:
                    result.local_only.append(name)

            # Ensure .claude/skills/ exists (unless dry run)
            if not self.dry_run:
                self.local_skills_dir.mkdir(parents=True, exist_ok=True)

            # Process each retro skill
            for name, retro_skill in sorted(retro_skills.items()):
                if name in local_skills:
                    self._handle_conflict(
                        retro_skill, local_skills[name], result
                    )
                else:
                    if self.dry_run:
                        result.imported.append(retro_skill.name)
                    else:
                        self._copy_skill(retro_skill, result)

            # Print summary
            self._print_summary(result)
            return result
        finally:
            if _cleanup_dir and _cleanup_dir.exists():
                shutil.rmtree(_cleanup_dir)

    # ------------------------------------------------------------------
    # Bundle unpacking
    # ------------------------------------------------------------------

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

        print(f"[retro] Bundle doesn't contain valid skills (expected <name>/SKILL.md)")
        shutil.rmtree(tmp)
        return None, None

    # ------------------------------------------------------------------
    # Reading skills
    # ------------------------------------------------------------------

    def _read_skills_dir(self, skills_dir: Path, source: str) -> dict[str, SkillEntry]:
        """Read all skills from a directory into a name->SkillEntry map."""
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

    # ------------------------------------------------------------------
    # Copying (no conflict)
    # ------------------------------------------------------------------

    def _copy_skill(self, retro_skill: SkillEntry, result: MergeResult) -> None:
        """Copy a retro skill to .claude/skills/ (no conflict)."""
        dest_dir = self.local_skills_dir / retro_skill.name
        dest_dir.mkdir(parents=True, exist_ok=True)

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

    # ------------------------------------------------------------------
    # Conflict handling
    # ------------------------------------------------------------------

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
            if self.dry_run:
                result.overwritten.append(retro_skill.name)
            else:
                self._copy_skill(retro_skill, result)
                result.imported.pop()
                result.overwritten.append(retro_skill.name)

        elif self.strategy == MergeStrategy.MERGE:
            self._merge_skill(retro_skill, local_skill, result)

        elif self.strategy == MergeStrategy.INTERACTIVE:
            self._interactive_resolve(retro_skill, local_skill, result)

    # ------------------------------------------------------------------
    # Smart merge
    # ------------------------------------------------------------------

    def _merge_skill(
        self,
        retro_skill: SkillEntry,
        local_skill: SkillEntry,
        result: MergeResult,
    ) -> None:
        """Smart merge: frontmatter union + content-aware section merge."""
        # Smart frontmatter merge
        merged_fm = _merge_frontmatter(local_skill.frontmatter, retro_skill.frontmatter)

        # Content-aware body merge
        merged_body = _merge_bodies(local_skill.body, retro_skill.body)

        if not self.dry_run:
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

    # ------------------------------------------------------------------
    # Interactive merge
    # ------------------------------------------------------------------

    def _interactive_resolve(
        self,
        retro_skill: SkillEntry,
        local_skill: SkillEntry,
        result: MergeResult,
    ) -> None:
        """Show diff and let user pick resolution per skill."""
        print(f"\n{'=' * 60}")
        print(f"  CONFLICT: {retro_skill.name}")
        print(f"  Local source:  .claude/skills/{local_skill.name}/")
        print(f"  Shared source: {retro_skill.source}")
        print(f"{'=' * 60}")

        # Show diff
        diff = _skill_diff(local_skill, retro_skill)
        if diff:
            print(diff)
        else:
            print("  (bodies are identical)")

        # Show frontmatter differences
        fm_diff = _frontmatter_diff(local_skill.frontmatter, retro_skill.frontmatter)
        if fm_diff:
            print(f"\n  Frontmatter differences:")
            for line in fm_diff:
                print(f"    {line}")

        print(f"\n  Options:")
        print(f"    [l] Keep local version (skip shared)")
        print(f"    [s] Take shared version (overwrite local)")
        print(f"    [m] Smart merge (combine both)")
        print(f"    [d] Show full diff again")

        while True:
            try:
                choice = input("  > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "l"

            if choice == "l":
                result.skipped.append(retro_skill.name)
                return
            elif choice == "s":
                if self.dry_run:
                    result.overwritten.append(retro_skill.name)
                else:
                    self._copy_skill(retro_skill, result)
                    result.imported.pop()
                    result.overwritten.append(retro_skill.name)
                return
            elif choice == "m":
                self._merge_skill(retro_skill, local_skill, result)
                return
            elif choice == "d":
                diff = _skill_diff(local_skill, retro_skill)
                print(diff if diff else "  (identical)")
            else:
                print("  Choose: l (local), s (shared), m (merge), d (diff)")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _print_summary(self, result: MergeResult) -> None:
        """Print a human-readable summary of the import."""
        total_retro = (
            len(result.imported) + len(result.skipped)
            + len(result.overwritten) + len(result.merged)
        )
        mode = " (dry run)" if self.dry_run else ""
        print(f"\n[retro] Import summary{mode} ({total_retro} shared skills -> .claude/skills/)")

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
            print(f"  Skipped -- local kept ({len(result.skipped)}):")
            for name in result.skipped:
                print(f"    - {name}")

        if result.local_only:
            print(f"  Local-only -- untouched ({len(result.local_only)}):")
            for name in result.local_only:
                print(f"    . {name}")

        dest_count = len(result.imported) + len(result.merged) + len(result.overwritten)
        if dest_count and not self.dry_run:
            print(f"\n[retro] {dest_count} skills now available in .claude/skills/")


# ======================================================================
# Merge helpers (module-level, testable independently)
# ======================================================================

def _merge_frontmatter(local_fm: dict, retro_fm: dict) -> dict:
    """Smart frontmatter merge.

    Rules:
    - 'name': keep local
    - 'description': keep whichever is longer (more informative)
    - 'allowed-tools': union of both (space-separated string or list)
    - 'paths': union of both
    - Other keys: local wins if present, else retro fills in
    """
    merged = dict(local_fm)

    for key, retro_val in retro_fm.items():
        if key not in merged:
            # New key from retro -- add it
            merged[key] = retro_val
            continue

        local_val = merged[key]

        if key == "name":
            pass  # always keep local

        elif key == "description":
            # Keep the longer (more informative) description
            if isinstance(retro_val, str) and isinstance(local_val, str):
                if len(retro_val) > len(local_val):
                    merged[key] = retro_val

        elif key == "allowed-tools":
            merged[key] = _union_tools(local_val, retro_val)

        elif key == "paths":
            merged[key] = _union_csv(local_val, retro_val)

        # Other keys: local wins (already in merged)

    return merged


def _union_tools(a, b) -> str:
    """Union two allowed-tools values (str or list) into a sorted string."""
    def _to_set(v):
        if isinstance(v, list):
            return set(v)
        if isinstance(v, str):
            return set(v.split())
        return set()
    combined = sorted(_to_set(a) | _to_set(b))
    return " ".join(combined) if combined else ""


def _union_csv(a, b) -> str:
    """Union two comma-separated path specs."""
    def _to_set(v):
        if isinstance(v, list):
            return set(v)
        if isinstance(v, str):
            return set(p.strip() for p in v.split(",") if p.strip())
        return set()
    combined = sorted(_to_set(a) | _to_set(b))
    return ",".join(combined) if combined else ""


def _merge_bodies(local_body: str, retro_body: str) -> str:
    """Content-aware body merge.

    Strategy:
    1. Parse both bodies into sections (heading + content).
    2. For sections only in local: keep as-is.
    3. For sections only in retro: append after local sections.
    4. For sections in both (same heading): merge unique items.
       - Extract bullet points/list items from each.
       - Keep all local items, append retro items not in local.
    5. Non-section preamble text (before first heading): keep local,
       append any retro preamble lines not already present.
    """
    local_pre, local_sections = _parse_body(local_body)
    retro_pre, retro_sections = _parse_body(retro_body)

    # Merge preambles
    merged_pre = _merge_preambles(local_pre, retro_pre)

    # Index local sections by normalized heading
    local_by_heading = {}
    for heading, content in local_sections:
        key = heading.lower().strip()
        local_by_heading[key] = (heading, content)

    retro_by_heading = {}
    for heading, content in retro_sections:
        key = heading.lower().strip()
        retro_by_heading[key] = (heading, content)

    # Build merged sections
    merged_sections = []
    seen_headings = set()

    # First: all local sections (possibly enriched)
    for heading, content in local_sections:
        key = heading.lower().strip()
        seen_headings.add(key)
        if key in retro_by_heading:
            _, retro_content = retro_by_heading[key]
            merged_content = _merge_section_content(content, retro_content)
            merged_sections.append((heading, merged_content))
        else:
            merged_sections.append((heading, content))

    # Then: retro-only sections
    new_sections = []
    for heading, content in retro_sections:
        key = heading.lower().strip()
        if key not in seen_headings:
            new_sections.append((heading, content))

    # Assemble
    parts = []
    if merged_pre:
        parts.append(merged_pre)

    for heading, content in merged_sections:
        parts.append(f"{heading}\n{content}")

    if new_sections:
        parts.append("<!-- imported from shared skills -->")
        for heading, content in new_sections:
            parts.append(f"{heading}\n{content}")

    return "\n\n".join(parts)


def _parse_body(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Parse body into (preamble, [(heading, content), ...]).

    Preamble is any text before the first heading.
    """
    lines = body.split("\n")
    preamble_lines = []
    sections = []
    current_heading = None
    current_content: list[str] = []

    for line in lines:
        if line.startswith("## ") or line.startswith("# "):
            if current_heading is not None:
                sections.append((current_heading, "\n".join(current_content).strip()))
            elif preamble_lines or current_content:
                preamble_lines = preamble_lines + current_content
            current_heading = line
            current_content = []
        else:
            if current_heading is None:
                preamble_lines.append(line)
            else:
                current_content.append(line)

    if current_heading is not None:
        sections.append((current_heading, "\n".join(current_content).strip()))

    return "\n".join(preamble_lines).strip(), sections


def _merge_preambles(local_pre: str, retro_pre: str) -> str:
    """Merge preamble text: keep local, append unique retro lines."""
    if not retro_pre:
        return local_pre
    if not local_pre:
        return retro_pre

    local_lines = set(l.strip() for l in local_pre.splitlines() if l.strip())
    new_lines = []
    for line in retro_pre.splitlines():
        if line.strip() and line.strip() not in local_lines:
            new_lines.append(line)

    if new_lines:
        return local_pre.rstrip() + "\n" + "\n".join(new_lines)
    return local_pre


def _merge_section_content(local_content: str, retro_content: str) -> str:
    """Merge content within a section that exists in both.

    Extracts items (lines starting with -, *, 1., or non-empty lines in
    code blocks) and appends unique retro items after local items.
    """
    local_items = _extract_items(local_content)
    retro_items = _extract_items(retro_content)

    if not local_items and not retro_items:
        # No structured items; keep local as-is
        return local_content

    # Normalize for comparison
    local_normalized = set(_normalize_item(i) for i in local_items)

    new_items = []
    for item in retro_items:
        if _normalize_item(item) not in local_normalized:
            new_items.append(item)

    if not new_items:
        return local_content

    return local_content.rstrip() + "\n" + "\n".join(new_items)


def _extract_items(content: str) -> list[str]:
    """Extract individual items from section content.

    Items are:
    - Lines starting with - or * (list items)
    - Lines starting with digits followed by . (numbered items)
    - Entire code blocks (``` ... ```) as single items
    """
    items = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Code block: capture as single item
        if stripped.startswith("```"):
            block = [line]
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            if i < len(lines):
                block.append(lines[i])
            items.append("\n".join(block))
            i += 1
            continue

        # List items (may have continuation lines)
        if stripped and (stripped[0] in "-*" or (stripped[0].isdigit() and "." in stripped[:4])):
            item_lines = [line]
            i += 1
            # Continuation: indented non-empty lines that aren't new items
            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.strip()
                if not next_stripped:
                    break
                if next_stripped[0] in "-*" or (next_stripped[0].isdigit() and "." in next_stripped[:4]):
                    break
                if next_line.startswith("  ") or next_line.startswith("\t"):
                    item_lines.append(next_line)
                    i += 1
                else:
                    break
            items.append("\n".join(item_lines))
            continue

        i += 1

    return items


def _normalize_item(item: str) -> str:
    """Normalize an item for deduplication (lowercase, strip bullets/numbers).

    For multi-line items (code blocks, continuation lines), uses the full
    content so that code blocks with different bodies aren't treated as dupes.
    """
    import re
    text = item.strip()
    if not text:
        return ""
    # Code blocks: use full content for comparison
    if text.startswith("```"):
        return text.lower()
    lines = text.splitlines()
    first = lines[0].strip()
    # Strip leading bullet/number
    for prefix in ["-", "*", "•"]:
        if first.startswith(prefix):
            first = first[len(prefix):].strip()
            break
    else:
        first = re.sub(r"^\d+\.\s*", "", first)
    # For multi-line items, include continuation for better dedup
    if len(lines) > 1:
        rest = " ".join(l.strip() for l in lines[1:] if l.strip())
        return (first + " " + rest).lower()
    return first.lower()


# ======================================================================
# Diff helpers
# ======================================================================

def _skill_diff(local_skill: SkillEntry, retro_skill: SkillEntry) -> str:
    """Generate a unified diff between two skill bodies."""
    local_lines = local_skill.body.splitlines(keepends=True)
    retro_lines = retro_skill.body.splitlines(keepends=True)

    diff = difflib.unified_diff(
        local_lines, retro_lines,
        fromfile=f"local/{local_skill.name}/SKILL.md",
        tofile=f"shared/{retro_skill.name}/SKILL.md",
        lineterm="",
    )
    return "\n".join(diff)


def _frontmatter_diff(local_fm: dict, retro_fm: dict) -> list[str]:
    """Show frontmatter differences as human-readable lines."""
    lines = []
    all_keys = sorted(set(local_fm) | set(retro_fm))
    for key in all_keys:
        local_val = local_fm.get(key)
        retro_val = retro_fm.get(key)
        if local_val == retro_val:
            continue
        if local_val is None:
            lines.append(f"  + {key}: {retro_val}  (from shared)")
        elif retro_val is None:
            lines.append(f"    {key}: {local_val}  (local only)")
        else:
            lines.append(f"  ~ {key}: {local_val} -> {retro_val}")
    return lines


# Keep for backwards compatibility
def _extract_sections(body: str) -> list[tuple[str, str]]:
    """Extract markdown sections from a skill body."""
    _, sections = _parse_body(body)
    return sections
