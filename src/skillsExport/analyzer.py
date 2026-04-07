"""Codebase analyzer: extracts structural information for skill generation.

Scans the repo to find ABCs, plugin patterns, key modules, conventions,
and other structural signals that inform what skills to generate.
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ABCInfo:
    """An abstract base class found in the codebase."""
    name: str
    file_path: str
    abstract_methods: list[str]
    implementations: list[str] = field(default_factory=list)
    docstring: str = ""


@dataclass
class ModuleInfo:
    """A significant module/directory in the codebase."""
    name: str
    path: str
    description: str
    key_files: list[str]
    entry_points: list[str] = field(default_factory=list)


@dataclass
class CLICommand:
    """A CLI command/flag found in the entry point."""
    flag: str
    help_text: str
    handler: str  # function or dispatch target


@dataclass
class CodebaseAnalysis:
    """Complete structural analysis of the codebase."""
    abcs: list[ABCInfo]
    modules: list[ModuleInfo]
    cli_commands: list[CLICommand]
    test_patterns: list[str]
    conventions: list[str]
    config_schema: dict
    file_tree: str


class CodebaseAnalyzer:
    """Analyzes a codebase to extract structural info for skill generation."""

    def __init__(self, working_dir: str):
        self.root = Path(working_dir)

    def analyze(self) -> CodebaseAnalysis:
        """Run full codebase analysis."""
        logger.info(f"Analyzing codebase at {self.root}")
        return CodebaseAnalysis(
            abcs=self._find_abcs(),
            modules=self._find_modules(),
            cli_commands=self._find_cli_commands(),
            test_patterns=self._find_test_patterns(),
            conventions=self._find_conventions(),
            config_schema=self._find_config_schema(),
            file_tree=self._build_file_tree(),
        )

    def _find_abcs(self) -> list[ABCInfo]:
        """Find all ABC/Protocol definitions and their implementations."""
        abcs = []
        src = self.root / "src"
        if not src.exists():
            return abcs

        abc_pattern = re.compile(
            r"class\s+(\w+)\s*\(.*(?:ABC|Protocol).*\):"
        )
        abstract_pattern = re.compile(
            r"@(?:abstractmethod|property)\s*\n\s*(?:@\w+\s*\n\s*)*def\s+(\w+)"
        )
        impl_pattern_template = r"class\s+(\w+)\s*\(.*{}.*\):"

        # Scan all Python files for ABCs
        for py_file in src.rglob("*.py"):
            try:
                content = py_file.read_text()
            except Exception:
                continue

            for match in abc_pattern.finditer(content):
                abc_name = match.group(1)
                # Extract abstract methods
                methods = abstract_pattern.findall(content)
                # Extract docstring
                class_start = match.end()
                docstring = ""
                doc_match = re.search(
                    r'"""(.*?)"""',
                    content[class_start:class_start + 500],
                    re.DOTALL,
                )
                if doc_match:
                    docstring = doc_match.group(1).strip()

                abc_info = ABCInfo(
                    name=abc_name,
                    file_path=str(py_file.relative_to(self.root)),
                    abstract_methods=methods,
                    docstring=docstring,
                )

                # Find implementations across the codebase
                impl_pattern = re.compile(
                    impl_pattern_template.format(re.escape(abc_name))
                )
                for other_file in src.rglob("*.py"):
                    if other_file == py_file:
                        continue
                    try:
                        other_content = other_file.read_text()
                    except Exception:
                        continue
                    for impl_match in impl_pattern.finditer(other_content):
                        abc_info.implementations.append(
                            f"{impl_match.group(1)} ({other_file.relative_to(self.root)})"
                        )

                abcs.append(abc_info)

        return abcs

    def _find_modules(self) -> list[ModuleInfo]:
        """Find significant modules (directories with __init__.py)."""
        modules = []
        src = self.root / "src"
        if not src.exists():
            return modules

        for init_file in src.rglob("__init__.py"):
            module_dir = init_file.parent
            if module_dir == src:
                continue  # skip src/ itself

            key_files = [
                str(f.relative_to(module_dir))
                for f in module_dir.iterdir()
                if f.suffix == ".py" and f.name != "__init__.py"
            ]

            # Try to extract module description from __init__.py docstring
            description = ""
            try:
                content = init_file.read_text()
                doc_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
                if doc_match:
                    description = doc_match.group(1).strip().split("\n")[0]
            except Exception:
                pass

            # Find entry points (functions called from main.py or __init__.py)
            entry_points = []
            try:
                init_content = init_file.read_text()
                exports = re.findall(r"from\s+\.\w+\s+import\s+(\w+)", init_content)
                entry_points = exports[:5]
            except Exception:
                pass

            modules.append(ModuleInfo(
                name=module_dir.name,
                path=str(module_dir.relative_to(self.root)),
                description=description,
                key_files=key_files,
                entry_points=entry_points,
            ))

        return modules

    def _find_cli_commands(self) -> list[CLICommand]:
        """Parse CLI flags from the main entry point."""
        commands = []
        main_py = self.root / "src" / "main.py"
        if not main_py.exists():
            return commands

        try:
            content = main_py.read_text()
        except Exception:
            return commands

        # Match add_argument calls
        pattern = re.compile(
            r'parser\.add_argument\(\s*"(--[\w-]+)".*?help="([^"]*)"',
            re.DOTALL,
        )
        for match in pattern.finditer(content):
            flag = match.group(1)
            help_text = match.group(2)

            # Try to find the handler
            handler = ""
            flag_var = flag.lstrip("-").replace("-", "_")
            handler_match = re.search(
                rf"args\.{flag_var}.*?:\s*\n?\s*([\w.]+)\(",
                content,
                re.DOTALL,
            )
            if handler_match:
                handler = handler_match.group(1)

            commands.append(CLICommand(
                flag=flag,
                help_text=help_text,
                handler=handler,
            ))

        return commands

    def _find_test_patterns(self) -> list[str]:
        """Identify test patterns and frameworks used."""
        patterns = []
        tests_dir = self.root / "tests"
        if not tests_dir.exists():
            return patterns

        test_files = list(tests_dir.rglob("test_*.py"))
        patterns.append(f"{len(test_files)} test files in tests/")

        # Check for conftest.py fixtures
        conftest = tests_dir / "conftest.py"
        if conftest.exists():
            try:
                content = conftest.read_text()
                fixtures = re.findall(r"@(?:pytest\.)?fixture.*\ndef\s+(\w+)", content)
                if fixtures:
                    patterns.append(f"Shared fixtures: {', '.join(fixtures[:10])}")
            except Exception:
                pass

        # Check for mocking patterns
        for tf in test_files[:5]:
            try:
                content = tf.read_text()
                if "mock" in content.lower() or "patch" in content.lower():
                    patterns.append(f"Mocking used in {tf.name}")
                    break
            except Exception:
                continue

        return patterns

    def _find_conventions(self) -> list[str]:
        """Detect coding conventions from the codebase."""
        conventions = []

        # Check for type hints
        src = self.root / "src"
        if src.exists():
            sample_files = list(src.rglob("*.py"))[:10]
            type_hint_count = 0
            for f in sample_files:
                try:
                    content = f.read_text()
                    if "->" in content or ": str" in content or ": int" in content:
                        type_hint_count += 1
                except Exception:
                    continue
            if type_hint_count > len(sample_files) // 2:
                conventions.append("Type hints used throughout")

        # Check for dataclasses
        if src.exists():
            for f in src.rglob("*.py"):
                try:
                    content = f.read_text()
                    if "@dataclass" in content:
                        conventions.append("Dataclasses used for structured data")
                        break
                except Exception:
                    continue

        # Check pyproject.toml for packaging info
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                if "[project.scripts]" in content:
                    conventions.append("CLI entry point defined in pyproject.toml")
            except Exception:
                pass

        return conventions

    def _find_config_schema(self) -> dict:
        """Extract configuration schema from config files."""
        config_file = self.root / "retro_config.yaml"
        if not config_file.exists():
            return {}

        try:
            import yaml
            with open(config_file) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _build_file_tree(self, max_depth: int = 3) -> str:
        """Build a compact file tree string for context."""
        lines = []
        src = self.root / "src"
        if not src.exists():
            return ""

        def _walk(directory: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name))
            dirs = [e for e in entries if e.is_dir() and not e.name.startswith((".", "__"))]
            files = [e for e in entries if e.is_file() and e.suffix == ".py"]

            for d in dirs:
                lines.append(f"{prefix}{d.name}/")
                _walk(d, prefix + "  ", depth + 1)
            for f in files:
                lines.append(f"{prefix}{f.name}")

        lines.append("src/")
        _walk(src, "  ", 1)
        return "\n".join(lines)

    def format_for_llm(self, analysis: CodebaseAnalysis) -> str:
        """Format the analysis into a text block suitable for LLM prompts."""
        parts = []

        parts.append("## File Structure")
        parts.append(analysis.file_tree)

        if analysis.abcs:
            parts.append("\n## Extension Points (ABCs/Protocols)")
            for abc in analysis.abcs:
                parts.append(f"\n### {abc.name} ({abc.file_path})")
                if abc.docstring:
                    parts.append(f"  {abc.docstring}")
                parts.append(f"  Abstract methods: {', '.join(abc.abstract_methods)}")
                if abc.implementations:
                    parts.append(f"  Implementations: {', '.join(abc.implementations)}")

        if analysis.modules:
            parts.append("\n## Modules")
            for mod in analysis.modules:
                desc = f" — {mod.description}" if mod.description else ""
                parts.append(f"\n### {mod.name} ({mod.path}){desc}")
                parts.append(f"  Files: {', '.join(mod.key_files)}")
                if mod.entry_points:
                    parts.append(f"  Exports: {', '.join(mod.entry_points)}")

        if analysis.cli_commands:
            parts.append("\n## CLI Commands")
            for cmd in analysis.cli_commands:
                handler = f" -> {cmd.handler}" if cmd.handler else ""
                parts.append(f"  {cmd.flag}: {cmd.help_text}{handler}")

        if analysis.test_patterns:
            parts.append("\n## Test Patterns")
            for tp in analysis.test_patterns:
                parts.append(f"  - {tp}")

        if analysis.conventions:
            parts.append("\n## Conventions")
            for conv in analysis.conventions:
                parts.append(f"  - {conv}")

        return "\n".join(parts)
