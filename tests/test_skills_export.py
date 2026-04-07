"""Tests for the skills export module."""

import json
import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.skillsExport.analyzer import CodebaseAnalyzer, CodebaseAnalysis
from src.skillsExport.generator import SkillGenerator, SkillSpec, GeneratedSkill
from src.skillsExport.exporter import SkillsExporter


# ---------------------------------------------------------------------------
# Analyzer tests
# ---------------------------------------------------------------------------

class TestCodebaseAnalyzer:

    def test_analyze_returns_analysis(self, tmp_path):
        """Analyzer produces a CodebaseAnalysis with all fields."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text(
            'import argparse\n'
            'parser = argparse.ArgumentParser()\n'
            'parser.add_argument("--test", help="A test flag")\n'
        )

        analyzer = CodebaseAnalyzer(str(tmp_path))
        result = analyzer.analyze()

        assert isinstance(result, CodebaseAnalysis)
        assert isinstance(result.abcs, list)
        assert isinstance(result.modules, list)
        assert isinstance(result.cli_commands, list)
        assert isinstance(result.file_tree, str)

    def test_find_abcs(self, tmp_path):
        """Analyzer finds ABC definitions."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "base.py").write_text(
            'from abc import ABC, abstractmethod\n'
            'class BaseWidget(ABC):\n'
            '    """A widget base class."""\n'
            '    @abstractmethod\n'
            '    def render(self): ...\n'
        )
        (src / "impl.py").write_text(
            'from .base import BaseWidget\n'
            'class FancyWidget(BaseWidget):\n'
            '    def render(self): return "fancy"\n'
        )

        analyzer = CodebaseAnalyzer(str(tmp_path))
        abcs = analyzer._find_abcs()

        assert len(abcs) == 1
        assert abcs[0].name == "BaseWidget"
        assert "render" in abcs[0].abstract_methods
        assert any("FancyWidget" in impl for impl in abcs[0].implementations)

    def test_find_cli_commands(self, tmp_path):
        """Analyzer extracts CLI flags from argparse."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text(
            'import argparse\n'
            'parser = argparse.ArgumentParser()\n'
            'parser.add_argument("--foo", help="Do foo things")\n'
            'parser.add_argument("--bar", help="Do bar things")\n'
        )

        analyzer = CodebaseAnalyzer(str(tmp_path))
        cmds = analyzer._find_cli_commands()

        assert len(cmds) == 2
        assert cmds[0].flag == "--foo"
        assert cmds[0].help_text == "Do foo things"

    def test_find_modules(self, tmp_path):
        """Analyzer finds Python modules with __init__.py."""
        src = tmp_path / "src"
        mod = src / "mymod"
        mod.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (mod / "__init__.py").write_text('"""My module does things."""\nfrom .core import run\n')
        (mod / "core.py").write_text("def run(): pass\n")

        analyzer = CodebaseAnalyzer(str(tmp_path))
        modules = analyzer._find_modules()

        assert len(modules) == 1
        assert modules[0].name == "mymod"
        assert "core.py" in modules[0].key_files
        assert "run" in modules[0].entry_points

    def test_build_file_tree(self, tmp_path):
        """Analyzer builds a readable file tree."""
        src = tmp_path / "src"
        sub = src / "sub"
        sub.mkdir(parents=True)
        (src / "main.py").write_text("")
        (sub / "helper.py").write_text("")

        analyzer = CodebaseAnalyzer(str(tmp_path))
        tree = analyzer._build_file_tree()

        assert "src/" in tree
        assert "main.py" in tree
        assert "sub/" in tree

    def test_format_for_llm(self, tmp_path):
        """format_for_llm produces non-empty string."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text("")

        analyzer = CodebaseAnalyzer(str(tmp_path))
        analysis = analyzer.analyze()
        text = analyzer.format_for_llm(analysis)

        assert isinstance(text, str)
        assert "File Structure" in text


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------

class TestSkillGenerator:

    @patch("src.skillsExport.generator.call_llm_json")
    def test_plan_skills(self, mock_llm):
        """Planner returns SkillSpec list from LLM output."""
        mock_llm.return_value = {
            "skills": [
                {
                    "name": "add-widget",
                    "description": "Add a new widget to the system",
                    "category": "plugin",
                    "related_bullets": ["[coding-00001]"],
                    "related_files": ["src/widgets/base.py"],
                    "user_invocable": True,
                    "reasoning": "There are 3 widget ABCs",
                },
                {
                    "name": "debug-service",
                    "description": "Debug the background service",
                    "category": "debug",
                },
            ]
        }

        gen = SkillGenerator(model="test-model")
        specs = gen.plan_skills("codebase analysis", "playbook text")

        assert len(specs) == 2
        assert specs[0].name == "add-widget"
        assert specs[0].category == "plugin"
        assert "[coding-00001]" in specs[0].related_bullets
        assert specs[1].name == "debug-service"

    @patch("src.skillsExport.generator.call_llm")
    def test_generate_skill(self, mock_llm):
        """Generator produces a GeneratedSkill with frontmatter and body."""
        mock_llm.return_value = "# Add Widget\n\nFollow these steps to add a new widget.\n\n## Step 1\nDo the thing."

        gen = SkillGenerator(model="test-model")
        spec = SkillSpec(
            name="add-widget",
            description="Add a new widget",
            category="plugin",
            related_files=["src/base.py"],
        )

        skill = gen.generate_skill(spec, "codebase context")

        assert skill.name == "add-widget"
        assert skill.frontmatter["name"] == "add-widget"
        assert skill.frontmatter["description"] == "Add a new widget"
        assert "Add Widget" in skill.body
        assert "Step 1" in skill.body

    @patch("src.skillsExport.generator.call_llm")
    def test_generate_skill_strips_accidental_frontmatter(self, mock_llm):
        """If LLM includes frontmatter, it's stripped."""
        mock_llm.return_value = "---\nname: oops\n---\n\n# Real content\nBody text."

        gen = SkillGenerator(model="test-model")
        spec = SkillSpec(name="test", description="test", category="reference")

        skill = gen.generate_skill(spec, "context")

        assert "---" not in skill.body
        assert "Real content" in skill.body


# ---------------------------------------------------------------------------
# Exporter tests
# ---------------------------------------------------------------------------

class TestSkillsExporter:

    @patch("src.skillsExport.generator.call_llm_json")
    @patch("src.skillsExport.generator.call_llm")
    def test_export_creates_skill_files(self, mock_gen_llm, mock_plan_llm, tmp_path):
        """Full export pipeline creates SKILL.md files."""
        # Setup minimal project structure
        src = tmp_path / "src"
        src.mkdir()
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text(
            'import argparse\nparser = argparse.ArgumentParser()\n'
            'parser.add_argument("--run", help="Run it")\n'
        )

        retro_dir = tmp_path / ".retro"
        retro_dir.mkdir()
        playbook_path = str(retro_dir / "playbook.txt")
        Path(playbook_path).write_text("## CODING_PATTERNS\n[coding-00001] Test rule.\n")

        mock_plan_llm.return_value = {
            "skills": [
                {
                    "name": "my-skill",
                    "description": "A test skill",
                    "category": "reference",
                    "related_bullets": [],
                    "related_files": [],
                    "user_invocable": True,
                    "reasoning": "test",
                }
            ]
        }
        mock_gen_llm.return_value = "# My Skill\n\nDo the thing.\n"

        exporter = SkillsExporter(
            working_dir=str(tmp_path),
            retro_dir=str(retro_dir),
            playbook_path=playbook_path,
            model="test-model",
        )
        paths = exporter.export()

        assert len(paths) == 1
        skill_file = retro_dir / "skills" / "my-skill" / "SKILL.md"
        assert skill_file.exists()

        content = skill_file.read_text()
        assert "name: my-skill" in content
        assert "My Skill" in content

    def test_export_no_llm_mode(self, tmp_path):
        """--no-llm mode generates skills from codebase structure."""
        src = tmp_path / "src"
        utils = src / "utils"
        utils.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        (src / "main.py").write_text(
            'import argparse\nparser = argparse.ArgumentParser()\n'
            'parser.add_argument("--up", help="Start daemon")\n'
        )
        (utils / "__init__.py").write_text("")
        (utils / "base.py").write_text(
            'from abc import ABC, abstractmethod\n'
            'class BaseReader(ABC):\n'
            '    @abstractmethod\n'
            '    def read(self): ...\n'
        )

        retro_dir = tmp_path / ".retro"
        retro_dir.mkdir()
        playbook_path = str(retro_dir / "playbook.txt")

        exporter = SkillsExporter(
            working_dir=str(tmp_path),
            retro_dir=str(retro_dir),
            playbook_path=playbook_path,
            no_llm=True,
        )
        paths = exporter.export()

        # Should generate at least codebase-guide + reader extension skill + debug-daemon
        assert len(paths) >= 2
        # All should be SKILL.md files
        for p in paths:
            full_path = tmp_path / p
            assert full_path.exists()
            content = full_path.read_text()
            assert "---" in content  # has frontmatter

    def test_render_skill_md(self, tmp_path):
        """_render_skill_md produces valid YAML frontmatter + body."""
        retro_dir = tmp_path / ".retro"
        retro_dir.mkdir()

        exporter = SkillsExporter(
            working_dir=str(tmp_path),
            retro_dir=str(retro_dir),
            no_llm=True,
        )

        skill = GeneratedSkill(
            name="test-skill",
            frontmatter={"name": "test-skill", "description": "A test"},
            body="# Test\n\nBody content.",
        )

        result = exporter._render_skill_md(skill)

        assert result.startswith("---\n")
        assert "name: test-skill" in result
        assert "---\n\n# Test" in result
        assert "Body content." in result
