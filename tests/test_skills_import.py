"""Tests for the skills import module."""

import sys
import os
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.skillsExport.importer import (
    SkillsImporter,
    MergeStrategy,
    MergeResult,
    _extract_sections,
)


def _write_skill(skills_dir: Path, name: str, description: str, body: str) -> Path:
    """Helper to write a minimal SKILL.md."""
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    return skill_file


# ---------------------------------------------------------------------------
# _extract_sections
# ---------------------------------------------------------------------------

class TestExtractSections:

    def test_extracts_h2_sections(self):
        body = "## First\nContent 1\n\n## Second\nContent 2"
        sections = _extract_sections(body)
        assert len(sections) == 2
        assert sections[0] == ("## First", "Content 1")
        assert sections[1] == ("## Second", "Content 2")

    def test_extracts_h1_sections(self):
        body = "# Title\nIntro\n\n## Details\nStuff"
        sections = _extract_sections(body)
        assert len(sections) == 2
        assert sections[0][0] == "# Title"
        assert sections[1][0] == "## Details"

    def test_empty_body(self):
        assert _extract_sections("") == []

    def test_no_headings(self):
        assert _extract_sections("Just some text\nMore text") == []


# ---------------------------------------------------------------------------
# SkillsImporter — reading skills
# ---------------------------------------------------------------------------

class TestReadSkills:

    def test_reads_retro_skills(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "my-skill", "A test skill", "# My Skill\nDo stuff.")

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
        )
        skills = importer._read_skills_dir(retro_skills, "retro")

        assert "my-skill" in skills
        assert skills["my-skill"].source == "retro"
        assert skills["my-skill"].frontmatter["name"] == "my-skill"

    def test_reads_local_skills(self, tmp_path):
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "local-skill", "A local skill", "# Local\nStuff.")

        importer = SkillsImporter(working_dir=str(tmp_path))
        skills = importer._read_skills_dir(local_skills, "local")

        assert "local-skill" in skills
        assert skills["local-skill"].source == "local"

    def test_skips_non_directories(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        retro_skills.mkdir(parents=True)
        (retro_skills / "stray-file.txt").write_text("not a skill")

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
        )
        skills = importer._read_skills_dir(retro_skills, "retro")
        assert len(skills) == 0

    def test_skips_dir_without_skill_md(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        (retro_skills / "empty-skill").mkdir(parents=True)

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
        )
        skills = importer._read_skills_dir(retro_skills, "retro")
        assert len(skills) == 0

    def test_empty_dir_returns_empty(self, tmp_path):
        importer = SkillsImporter(working_dir=str(tmp_path))
        skills = importer._read_skills_dir(tmp_path / "nonexistent", "retro")
        assert skills == {}


# ---------------------------------------------------------------------------
# Import — no conflicts
# ---------------------------------------------------------------------------

class TestImportNoConflicts:

    def test_imports_all_retro_skills(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "skill-a", "Skill A", "# A\nDo A.")
        _write_skill(retro_skills, "skill-b", "Skill B", "# B\nDo B.")

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
        )
        result = importer.import_skills()

        assert sorted(result.imported) == ["skill-a", "skill-b"]
        assert result.skipped == []
        assert result.overwritten == []
        assert result.merged == []

        # Verify files exist in .claude/skills/
        assert (tmp_path / ".claude" / "skills" / "skill-a" / "SKILL.md").exists()
        assert (tmp_path / ".claude" / "skills" / "skill-b" / "SKILL.md").exists()

    def test_creates_claude_skills_dir(self, tmp_path):
        """Import creates .claude/skills/ if it doesn't exist."""
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "skill-a", "Skill A", "# A\nDo A.")

        assert not (tmp_path / ".claude" / "skills").exists()

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
        )
        importer.import_skills()

        assert (tmp_path / ".claude" / "skills").is_dir()

    def test_preserves_local_only_skills(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Shared skill", "# Shared\nStuff.")

        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "personal", "My personal skill", "# Mine\nMy stuff.")

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
        )
        result = importer.import_skills()

        assert result.imported == ["shared"]
        assert result.local_only == ["personal"]

        # Personal skill untouched
        content = (local_skills / "personal" / "SKILL.md").read_text()
        assert "My personal skill" in content

    def test_copies_supporting_files(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "with-extras", "Has extras", "# Main\nBody.")
        (retro_skills / "with-extras" / "reference.md").write_text("# Reference\nDetails.")
        scripts_dir = retro_skills / "with-extras" / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "helper.sh").write_text("#!/bin/bash\necho hi")

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
        )
        importer.import_skills()

        dest = tmp_path / ".claude" / "skills" / "with-extras"
        assert (dest / "SKILL.md").exists()
        assert (dest / "reference.md").exists()
        assert (dest / "scripts" / "helper.sh").exists()

    def test_no_retro_skills_returns_empty(self, tmp_path):
        (tmp_path / ".retro").mkdir()

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
        )
        result = importer.import_skills()

        assert result.imported == []
        assert result.skipped == []


# ---------------------------------------------------------------------------
# Import — conflict resolution strategies
# ---------------------------------------------------------------------------

class TestConflictResolution:

    def _setup_conflict(self, tmp_path):
        """Create a retro and local skill with the same name."""
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro version", "## Retro Section\nRetro content.")

        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local version", "## Local Section\nLocal content.")

        return retro_skills, local_skills

    def test_local_first_keeps_local(self, tmp_path):
        _, local_skills = self._setup_conflict(tmp_path)

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
            strategy=MergeStrategy.LOCAL_FIRST,
        )
        result = importer.import_skills()

        assert result.skipped == ["shared"]
        assert result.imported == []
        assert result.overwritten == []

        # Local version preserved
        content = (local_skills / "shared" / "SKILL.md").read_text()
        assert "Local version" in content
        assert "Retro version" not in content

    def test_retro_first_overwrites_local(self, tmp_path):
        _, local_skills = self._setup_conflict(tmp_path)

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
            strategy=MergeStrategy.RETRO_FIRST,
        )
        result = importer.import_skills()

        assert result.overwritten == ["shared"]
        assert result.imported == []
        assert result.skipped == []

        # Retro version replaced local
        content = (local_skills / "shared" / "SKILL.md").read_text()
        assert "Retro version" in content

    def test_merge_combines_bodies(self, tmp_path):
        _, local_skills = self._setup_conflict(tmp_path)

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
            strategy=MergeStrategy.MERGE,
        )
        result = importer.import_skills()

        assert result.merged == ["shared"]
        assert result.imported == []

        content = (local_skills / "shared" / "SKILL.md").read_text()
        # Local content preserved
        assert "Local Section" in content
        assert "Local content" in content
        # Retro section appended
        assert "Retro Section" in content
        assert "Retro content" in content
        # Merge marker present
        assert "imported from .retro/skills/" in content

    def test_merge_keeps_local_frontmatter(self, tmp_path):
        self._setup_conflict(tmp_path)

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
            strategy=MergeStrategy.MERGE,
        )
        importer.import_skills()

        content = (tmp_path / ".claude" / "skills" / "shared" / "SKILL.md").read_text()
        # Local description should be kept as primary
        assert "Local version" in content

    def test_merge_skips_duplicate_sections(self, tmp_path):
        """If both have the same section heading, don't duplicate."""
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "overlap", "Retro", "## Steps\nRetro steps.")

        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "overlap", "Local", "## Steps\nLocal steps.")

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
            strategy=MergeStrategy.MERGE,
        )
        result = importer.import_skills()

        assert result.merged == ["overlap"]
        content = (local_skills / "overlap" / "SKILL.md").read_text()
        # Should keep local Steps, not duplicate
        assert content.count("## Steps") == 1
        assert "Local steps" in content


# ---------------------------------------------------------------------------
# Import — extra sources
# ---------------------------------------------------------------------------

class TestExtraSources:

    def test_imports_from_extra_source(self, tmp_path):
        teammate_dir = tmp_path / "teammate-skills"
        _write_skill(teammate_dir, "team-skill", "Teammate skill", "# Team\nTeam stuff.")

        (tmp_path / ".retro").mkdir()

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
            sources=[str(teammate_dir)],
        )
        result = importer.import_skills()

        assert "team-skill" in result.imported
        assert (tmp_path / ".claude" / "skills" / "team-skill" / "SKILL.md").exists()

    def test_combines_retro_and_extra_sources(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "retro-skill", "From retro", "# Retro\nR.")

        extra_dir = tmp_path / "extra"
        _write_skill(extra_dir, "extra-skill", "From extra", "# Extra\nE.")

        importer = SkillsImporter(
            working_dir=str(tmp_path),
            retro_dir=str(tmp_path / ".retro"),
            sources=[str(extra_dir)],
        )
        result = importer.import_skills()

        assert sorted(result.imported) == ["extra-skill", "retro-skill"]


# ---------------------------------------------------------------------------
# Bundle round-trip (export -o → import -i)
# ---------------------------------------------------------------------------

class TestBundleRoundTrip:

    def test_tar_gz_round_trip(self, tmp_path):
        """Export to tar.gz, import from tar.gz."""
        from src.skillsExport.exporter import SkillsExporter

        # Setup: create a project with retro skills
        src = tmp_path / "project" / "src"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text("")
        retro_dir = tmp_path / "project" / ".retro"
        retro_dir.mkdir()
        playbook_path = str(retro_dir / "playbook.txt")

        # Export skills (no-llm mode for testing)
        exporter = SkillsExporter(
            working_dir=str(tmp_path / "project"),
            retro_dir=str(retro_dir),
            playbook_path=playbook_path,
            no_llm=True,
        )
        exporter.export()

        # Bundle into tar.gz
        bundle = str(tmp_path / "skills.tar.gz")
        exporter.bundle(bundle)
        assert Path(bundle).exists()
        assert Path(bundle).stat().st_size > 0

        # Import into a fresh project
        fresh = tmp_path / "fresh-project"
        fresh.mkdir()
        (fresh / ".retro").mkdir()

        importer = SkillsImporter(
            working_dir=str(fresh),
            retro_dir=str(fresh / ".retro"),
        )
        result = importer.import_skills(bundle_path=bundle)

        assert len(result.imported) > 0
        # Verify skills landed in .claude/skills/
        claude_skills = fresh / ".claude" / "skills"
        assert claude_skills.is_dir()
        skill_dirs = [d for d in claude_skills.iterdir() if d.is_dir()]
        assert len(skill_dirs) == len(result.imported)

    def test_zip_round_trip(self, tmp_path):
        """Export to zip, import from zip."""
        from src.skillsExport.exporter import SkillsExporter

        src = tmp_path / "project" / "src"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text("")
        retro_dir = tmp_path / "project" / ".retro"
        retro_dir.mkdir()
        playbook_path = str(retro_dir / "playbook.txt")

        exporter = SkillsExporter(
            working_dir=str(tmp_path / "project"),
            retro_dir=str(retro_dir),
            playbook_path=playbook_path,
            no_llm=True,
        )
        exporter.export()

        bundle = str(tmp_path / "skills.zip")
        exporter.bundle(bundle)
        assert Path(bundle).exists()

        fresh = tmp_path / "fresh-project"
        fresh.mkdir()
        (fresh / ".retro").mkdir()

        importer = SkillsImporter(
            working_dir=str(fresh),
            retro_dir=str(fresh / ".retro"),
        )
        result = importer.import_skills(bundle_path=bundle)

        assert len(result.imported) > 0

    def test_bundle_with_local_merge(self, tmp_path):
        """Import from bundle respects merge strategy."""
        # Create a bundle with one skill
        skills_src = tmp_path / "src-skills"
        _write_skill(skills_src, "shared", "From bundle", "## Bundle Section\nBundle content.")

        import tarfile
        bundle = tmp_path / "teammate.tar.gz"
        with tarfile.open(bundle, "w:gz") as tf:
            for f in skills_src.rglob("*"):
                if f.is_file():
                    tf.add(f, f.relative_to(skills_src))

        # Setup target project with existing local skill
        project = tmp_path / "project"
        project.mkdir()
        (project / ".retro").mkdir()
        local_skills = project / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local version", "## Local Section\nLocal content.")

        importer = SkillsImporter(
            working_dir=str(project),
            retro_dir=str(project / ".retro"),
            strategy=MergeStrategy.MERGE,
        )
        result = importer.import_skills(bundle_path=str(bundle))

        assert result.merged == ["shared"]
        content = (local_skills / "shared" / "SKILL.md").read_text()
        assert "Local Section" in content
        assert "Bundle Section" in content

    def test_nonexistent_bundle(self, tmp_path):
        """Gracefully handles missing bundle file."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".retro").mkdir()

        importer = SkillsImporter(
            working_dir=str(project),
            retro_dir=str(project / ".retro"),
        )
        result = importer.import_skills(bundle_path="/nonexistent/skills.tar.gz")

        assert result.imported == []

    def test_invalid_bundle(self, tmp_path):
        """Gracefully handles corrupt bundle."""
        project = tmp_path / "project"
        project.mkdir()
        (project / ".retro").mkdir()

        bad_bundle = tmp_path / "bad.tar.gz"
        bad_bundle.write_text("this is not a tarball")

        importer = SkillsImporter(
            working_dir=str(project),
            retro_dir=str(project / ".retro"),
        )
        result = importer.import_skills(bundle_path=str(bad_bundle))

        assert result.imported == []

    def test_bundle_combined_with_retro(self, tmp_path):
        """Bundle skills merge with .retro/skills/ (not replace)."""
        project = tmp_path / "project"
        project.mkdir()
        retro_skills = project / ".retro" / "skills"
        _write_skill(retro_skills, "retro-skill", "From retro", "# Retro\nR.")

        # Create bundle with a different skill
        bundle_src = tmp_path / "bundle-src"
        _write_skill(bundle_src, "bundle-skill", "From bundle", "# Bundle\nB.")

        import tarfile
        bundle = tmp_path / "teammate.tar.gz"
        with tarfile.open(bundle, "w:gz") as tf:
            for f in bundle_src.rglob("*"):
                if f.is_file():
                    tf.add(f, f.relative_to(bundle_src))

        importer = SkillsImporter(
            working_dir=str(project),
            retro_dir=str(project / ".retro"),
        )
        result = importer.import_skills(bundle_path=str(bundle))

        assert sorted(result.imported) == ["bundle-skill", "retro-skill"]


# ---------------------------------------------------------------------------
# MergeResult
# ---------------------------------------------------------------------------

class TestMergeResult:

    def test_default_empty(self):
        r = MergeResult()
        assert r.imported == []
        assert r.skipped == []
        assert r.overwritten == []
        assert r.merged == []
        assert r.local_only == []
