"""Tests for the skills import module."""

import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.skillsExport.importer import (
    SkillsImporter,
    MergeStrategy,
    MergeResult,
    _extract_sections,
    _merge_frontmatter,
    _merge_bodies,
    _merge_section_content,
    _extract_items,
    _normalize_item,
    _union_tools,
    _skill_diff,
    _frontmatter_diff,
)


def _write_skill(skills_dir: Path, name: str, description: str, body: str,
                  extra_fm: dict | None = None) -> Path:
    """Helper to write a SKILL.md with optional extra frontmatter."""
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = {"name": name, "description": description}
    if extra_fm:
        fm.update(extra_fm)
    import yaml
    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    content = f"---\n{fm_str}---\n\n{body}\n"
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    return skill_file


# ---------------------------------------------------------------------------
# _extract_sections (backwards compat)
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

    def test_empty_body(self):
        assert _extract_sections("") == []

    def test_no_headings(self):
        assert _extract_sections("Just some text\nMore text") == []


# ---------------------------------------------------------------------------
# Smart frontmatter merge
# ---------------------------------------------------------------------------

class TestMergeFrontmatter:

    def test_local_name_preserved(self):
        local = {"name": "my-skill", "description": "local desc"}
        retro = {"name": "my-skill", "description": "retro desc"}
        merged = _merge_frontmatter(local, retro)
        assert merged["name"] == "my-skill"

    def test_longer_description_wins(self):
        local = {"name": "s", "description": "short"}
        retro = {"name": "s", "description": "a much longer and more informative description"}
        merged = _merge_frontmatter(local, retro)
        assert "longer" in merged["description"]

    def test_local_description_kept_if_longer(self):
        local = {"name": "s", "description": "a very detailed local description here"}
        retro = {"name": "s", "description": "brief"}
        merged = _merge_frontmatter(local, retro)
        assert "detailed" in merged["description"]

    def test_allowed_tools_union(self):
        local = {"name": "s", "allowed-tools": "Read Edit Bash"}
        retro = {"name": "s", "allowed-tools": "Read Grep Glob"}
        merged = _merge_frontmatter(local, retro)
        tools = set(merged["allowed-tools"].split())
        assert tools == {"Read", "Edit", "Bash", "Grep", "Glob"}

    def test_allowed_tools_list_format(self):
        local = {"name": "s", "allowed-tools": ["Read", "Edit"]}
        retro = {"name": "s", "allowed-tools": "Grep Glob"}
        merged = _merge_frontmatter(local, retro)
        tools = set(merged["allowed-tools"].split())
        assert tools == {"Read", "Edit", "Grep", "Glob"}

    def test_new_retro_keys_added(self):
        local = {"name": "s"}
        retro = {"name": "s", "context": "fork", "agent": "Explore"}
        merged = _merge_frontmatter(local, retro)
        assert merged["context"] == "fork"
        assert merged["agent"] == "Explore"

    def test_paths_union(self):
        local = {"name": "s", "paths": "src/**/*.py"}
        retro = {"name": "s", "paths": "src/**/*.py,tests/**/*.py"}
        merged = _merge_frontmatter(local, retro)
        assert "tests/**/*.py" in merged["paths"]
        assert "src/**/*.py" in merged["paths"]


# ---------------------------------------------------------------------------
# Content-aware body merge
# ---------------------------------------------------------------------------

class TestMergeBodies:

    def test_new_sections_appended(self):
        local = "## Steps\n- Step 1\n- Step 2"
        retro = "## Steps\n- Step 1\n\n## Reference\n- Link 1"
        merged = _merge_bodies(local, retro)
        assert "## Steps" in merged
        assert "## Reference" in merged
        assert "imported from shared" in merged

    def test_same_section_items_merged(self):
        local = "## Steps\n- Do A\n- Do B"
        retro = "## Steps\n- Do B\n- Do C"
        merged = _merge_bodies(local, retro)
        assert "Do A" in merged
        assert "Do B" in merged
        assert "Do C" in merged
        # Should not duplicate "Do B"
        assert merged.count("Do B") == 1

    def test_identical_bodies_unchanged(self):
        body = "## Steps\n- Step 1\n- Step 2"
        merged = _merge_bodies(body, body)
        assert merged.strip() == body.strip()

    def test_preamble_preserved(self):
        local = "This is the intro.\n\n## Steps\n- Step 1"
        retro = "Different intro.\n\n## Steps\n- Step 1\n\n## Extra\n- Bonus"
        merged = _merge_bodies(local, retro)
        assert "This is the intro" in merged
        assert "## Extra" in merged

    def test_preamble_unique_lines_merged(self):
        local = "Line A\nLine B"
        retro = "Line B\nLine C"
        merged = _merge_bodies(local, retro)
        assert "Line A" in merged
        assert "Line B" in merged
        assert "Line C" in merged

    def test_code_blocks_as_items(self):
        local = "## Usage\n```bash\necho hello\n```"
        retro = "## Usage\n```bash\necho hello\n```\n```bash\necho world\n```"
        merged = _merge_bodies(local, retro)
        assert "echo hello" in merged
        assert "echo world" in merged

    def test_numbered_items_merged(self):
        local = "## Steps\n1. First\n2. Second"
        retro = "## Steps\n1. First\n2. Third"
        merged = _merge_bodies(local, retro)
        assert "First" in merged
        assert "Second" in merged
        assert "Third" in merged


# ---------------------------------------------------------------------------
# Item extraction
# ---------------------------------------------------------------------------

class TestExtractItems:

    def test_bullet_items(self):
        items = _extract_items("- Item A\n- Item B\n- Item C")
        assert len(items) == 3
        assert "Item A" in items[0]

    def test_numbered_items(self):
        items = _extract_items("1. First\n2. Second")
        assert len(items) == 2

    def test_code_block_as_single_item(self):
        items = _extract_items("```python\ndef foo():\n    pass\n```")
        assert len(items) == 1
        assert "def foo" in items[0]

    def test_continuation_lines(self):
        text = "- Item A\n  continuation of A\n- Item B"
        items = _extract_items(text)
        assert len(items) == 2
        assert "continuation" in items[0]

    def test_empty_content(self):
        assert _extract_items("") == []

    def test_no_items(self):
        assert _extract_items("Just plain text\nMore text") == []


class TestNormalizeItem:

    def test_strips_bullet(self):
        assert _normalize_item("- Do the thing") == "do the thing"

    def test_strips_asterisk(self):
        assert _normalize_item("* Do the thing") == "do the thing"

    def test_strips_number(self):
        assert _normalize_item("1. Do the thing") == "do the thing"

    def test_lowercase(self):
        assert _normalize_item("- DO THE THING") == "do the thing"


class TestUnionTools:

    def test_string_union(self):
        assert set(_union_tools("Read Edit", "Grep Glob").split()) == {"Read", "Edit", "Grep", "Glob"}

    def test_list_union(self):
        assert set(_union_tools(["Read"], ["Grep"]).split()) == {"Read", "Grep"}

    def test_mixed(self):
        assert set(_union_tools(["Read", "Edit"], "Grep Glob").split()) == {"Read", "Edit", "Grep", "Glob"}


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

class TestDiffHelpers:

    def test_skill_diff_shows_changes(self):
        from src.skillsExport.importer import SkillEntry
        local = SkillEntry("s", Path("/a"), {}, "Line A\nLine B", "local")
        retro = SkillEntry("s", Path("/b"), {}, "Line A\nLine C", "retro")
        diff = _skill_diff(local, retro)
        assert "-Line B" in diff
        assert "+Line C" in diff

    def test_frontmatter_diff_new_key(self):
        lines = _frontmatter_diff({"name": "s"}, {"name": "s", "context": "fork"})
        assert any("context" in l and "fork" in l for l in lines)

    def test_frontmatter_diff_changed_key(self):
        lines = _frontmatter_diff(
            {"name": "s", "description": "old"},
            {"name": "s", "description": "new"},
        )
        assert any("description" in l for l in lines)

    def test_frontmatter_diff_identical(self):
        lines = _frontmatter_diff({"name": "s"}, {"name": "s"})
        assert lines == []


# ---------------------------------------------------------------------------
# SkillsImporter — reading
# ---------------------------------------------------------------------------

class TestReadSkills:

    def test_reads_retro_skills(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "my-skill", "A test skill", "# My Skill\nDo stuff.")
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"))
        skills = importer._read_skills_dir(retro_skills, "retro")
        assert "my-skill" in skills

    def test_skips_non_directories(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        retro_skills.mkdir(parents=True)
        (retro_skills / "stray-file.txt").write_text("not a skill")
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"))
        assert len(importer._read_skills_dir(retro_skills, "retro")) == 0

    def test_empty_dir_returns_empty(self, tmp_path):
        importer = SkillsImporter(working_dir=str(tmp_path))
        assert importer._read_skills_dir(tmp_path / "nonexistent", "retro") == {}


# ---------------------------------------------------------------------------
# Import — no conflicts
# ---------------------------------------------------------------------------

class TestImportNoConflicts:

    def test_imports_all_retro_skills(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "skill-a", "Skill A", "# A\nDo A.")
        _write_skill(retro_skills, "skill-b", "Skill B", "# B\nDo B.")
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"))
        result = importer.import_skills()
        assert sorted(result.imported) == ["skill-a", "skill-b"]
        assert (tmp_path / ".claude" / "skills" / "skill-a" / "SKILL.md").exists()

    def test_preserves_local_only_skills(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Shared", "# Shared\nStuff.")
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "personal", "Personal", "# Mine\nMy stuff.")
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"))
        result = importer.import_skills()
        assert result.imported == ["shared"]
        assert result.local_only == ["personal"]

    def test_copies_supporting_files(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "with-extras", "Has extras", "# Main\nBody.")
        (retro_skills / "with-extras" / "reference.md").write_text("# Ref\nDetails.")
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"))
        importer.import_skills()
        assert (tmp_path / ".claude" / "skills" / "with-extras" / "reference.md").exists()


# ---------------------------------------------------------------------------
# Conflict resolution strategies
# ---------------------------------------------------------------------------

class TestConflictResolution:

    def _setup_conflict(self, tmp_path, local_body="## Local\nLocal content.",
                        retro_body="## Retro\nRetro content."):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro version", retro_body)
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local version", local_body)
        return retro_skills, local_skills

    def test_local_first_keeps_local(self, tmp_path):
        _, local_skills = self._setup_conflict(tmp_path)
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.LOCAL_FIRST)
        result = importer.import_skills()
        assert result.skipped == ["shared"]
        content = (local_skills / "shared" / "SKILL.md").read_text()
        assert "Local version" in content

    def test_retro_first_overwrites_local(self, tmp_path):
        _, local_skills = self._setup_conflict(tmp_path)
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.RETRO_FIRST)
        result = importer.import_skills()
        assert result.overwritten == ["shared"]
        content = (local_skills / "shared" / "SKILL.md").read_text()
        assert "Retro version" in content

    def test_merge_combines_new_sections(self, tmp_path):
        self._setup_conflict(tmp_path)
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.MERGE)
        result = importer.import_skills()
        assert result.merged == ["shared"]
        content = (tmp_path / ".claude" / "skills" / "shared" / "SKILL.md").read_text()
        assert "Local" in content
        assert "Retro" in content

    def test_merge_deduplicates_items_in_same_section(self, tmp_path):
        """When both have the same section, merge unique items."""
        self._setup_conflict(
            tmp_path,
            local_body="## Steps\n- Do A\n- Do B",
            retro_body="## Steps\n- Do B\n- Do C",
        )
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.MERGE)
        result = importer.import_skills()
        content = (tmp_path / ".claude" / "skills" / "shared" / "SKILL.md").read_text()
        assert "Do A" in content
        assert "Do B" in content
        assert "Do C" in content
        assert content.count("Do B") == 1  # not duplicated

    def test_merge_frontmatter_unions_tools(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro", "## Body\nText.",
                      extra_fm={"allowed-tools": "Read Grep"})
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local", "## Body\nText.",
                      extra_fm={"allowed-tools": "Read Edit Bash"})
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.MERGE)
        importer.import_skills()
        content = (local_skills / "shared" / "SKILL.md").read_text()
        for tool in ["Read", "Edit", "Bash", "Grep"]:
            assert tool in content

    def test_merge_picks_longer_description(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared",
                      "A much more detailed and informative description of the skill",
                      "## Body\nText.")
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Short", "## Body\nText.")
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.MERGE)
        importer.import_skills()
        content = (local_skills / "shared" / "SKILL.md").read_text()
        assert "detailed and informative" in content


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

class TestInteractive:

    def test_interactive_keep_local(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro", "## R\nR content.")
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local", "## L\nL content.")

        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.INTERACTIVE)
        with patch("builtins.input", return_value="l"):
            result = importer.import_skills()
        assert result.skipped == ["shared"]

    def test_interactive_take_shared(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro", "## R\nR content.")
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local", "## L\nL content.")

        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.INTERACTIVE)
        with patch("builtins.input", return_value="s"):
            result = importer.import_skills()
        assert result.overwritten == ["shared"]
        content = (local_skills / "shared" / "SKILL.md").read_text()
        assert "Retro" in content

    def test_interactive_merge(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro", "## Extra\nNew stuff.")
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local", "## Local\nOld stuff.")

        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.INTERACTIVE)
        with patch("builtins.input", return_value="m"):
            result = importer.import_skills()
        assert result.merged == ["shared"]
        content = (local_skills / "shared" / "SKILL.md").read_text()
        assert "Local" in content
        assert "Extra" in content

    def test_interactive_eof_defaults_to_local(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro", "## R\nR.")
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local", "## L\nL.")

        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.INTERACTIVE)
        with patch("builtins.input", side_effect=EOFError):
            result = importer.import_skills()
        assert result.skipped == ["shared"]


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------

class TestDryRun:

    def test_dry_run_no_files_written(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "skill-a", "A", "# A\nDo A.")
        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   dry_run=True)
        result = importer.import_skills()
        assert result.imported == ["skill-a"]
        assert not (tmp_path / ".claude" / "skills").exists()

    def test_dry_run_merge_no_files_written(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro", "## New\nNew stuff.")
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local", "## Old\nOld stuff.")

        original = (local_skills / "shared" / "SKILL.md").read_text()

        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.MERGE, dry_run=True)
        result = importer.import_skills()
        assert result.merged == ["shared"]
        # File unchanged
        assert (local_skills / "shared" / "SKILL.md").read_text() == original

    def test_dry_run_retro_first_no_overwrite(self, tmp_path):
        retro_skills = tmp_path / ".retro" / "skills"
        _write_skill(retro_skills, "shared", "Retro", "## R\nR.")
        local_skills = tmp_path / ".claude" / "skills"
        _write_skill(local_skills, "shared", "Local", "## L\nL.")

        original = (local_skills / "shared" / "SKILL.md").read_text()

        importer = SkillsImporter(working_dir=str(tmp_path), retro_dir=str(tmp_path / ".retro"),
                                   strategy=MergeStrategy.RETRO_FIRST, dry_run=True)
        result = importer.import_skills()
        assert result.overwritten == ["shared"]
        assert (local_skills / "shared" / "SKILL.md").read_text() == original


# ---------------------------------------------------------------------------
# Bundle round-trip
# ---------------------------------------------------------------------------

class TestBundleRoundTrip:

    def test_tar_gz_round_trip(self, tmp_path):
        from src.skillsExport.exporter import SkillsExporter
        src = tmp_path / "project" / "src"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text("")
        retro_dir = tmp_path / "project" / ".retro"
        retro_dir.mkdir()
        exporter = SkillsExporter(working_dir=str(tmp_path / "project"),
                                   retro_dir=str(retro_dir),
                                   playbook_path=str(retro_dir / "playbook.txt"), no_llm=True)
        exporter.export()
        bundle = str(tmp_path / "skills.tar.gz")
        exporter.bundle(bundle)
        assert Path(bundle).exists()

        fresh = tmp_path / "fresh"
        fresh.mkdir()
        (fresh / ".retro").mkdir()
        importer = SkillsImporter(working_dir=str(fresh), retro_dir=str(fresh / ".retro"))
        result = importer.import_skills(bundle_path=bundle)
        assert len(result.imported) > 0

    def test_bundle_combined_with_retro(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        retro_skills = project / ".retro" / "skills"
        _write_skill(retro_skills, "retro-skill", "From retro", "# R\nR.")

        bundle_src = tmp_path / "bundle-src"
        _write_skill(bundle_src, "bundle-skill", "From bundle", "# B\nB.")

        import tarfile
        bundle = tmp_path / "team.tar.gz"
        with tarfile.open(bundle, "w:gz") as tf:
            for f in bundle_src.rglob("*"):
                if f.is_file():
                    tf.add(f, f.relative_to(bundle_src))

        importer = SkillsImporter(working_dir=str(project), retro_dir=str(project / ".retro"))
        result = importer.import_skills(bundle_path=str(bundle))
        assert sorted(result.imported) == ["bundle-skill", "retro-skill"]

    def test_nonexistent_bundle(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / ".retro").mkdir()
        importer = SkillsImporter(working_dir=str(project), retro_dir=str(project / ".retro"))
        result = importer.import_skills(bundle_path="/nonexistent/skills.tar.gz")
        assert result.imported == []


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
