"""Build a Python dependency graph and compute blast-radius scores.

Blast radius of file X = number of files that transitively depend on X.
If you change X, all those files *could* be affected.

Only intra-project imports are tracked; stdlib and third-party are skipped.
"""

from __future__ import annotations

import ast
import os
from collections import deque
from pathlib import Path


# Directories to always skip when walking the project tree
_SKIP_DIRS = frozenset({
    "__pycache__", ".git", ".venv", "venv", "env",
    "node_modules", ".tox", ".mypy_cache", ".pytest_cache",
    "build", "dist", ".eggs",
})


class DependencyGraph:
    """Static import-based dependency graph for a Python project."""

    def __init__(self, project_root: str, exclude_dirs: list[str] | None = None):
        self.root = Path(project_root).resolve()
        self.exclude = _SKIP_DIRS | set(exclude_dirs or [])

        # rel_path -> set of rel_paths it imports (forward edges)
        self.imports: dict[str, set[str]] = {}
        # rel_path -> set of rel_paths that import it (reverse edges)
        self.imported_by: dict[str, set[str]] = {}
        # rel_path -> line count
        self.loc: dict[str, int] = {}
        # all known files
        self.files: set[str] = set()
        # cached blast radius results (invalidated on build)
        self._br_cache: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Walk the project, parse every .py file, and build the graph."""
        self.imports.clear()
        self.imported_by.clear()
        self.loc.clear()
        self.files.clear()
        self._br_cache.clear()

        py_files = self._find_py_files()
        for pf in py_files:
            rel = str(pf.relative_to(self.root))
            self.files.add(rel)
            self.imports.setdefault(rel, set())
            self.imported_by.setdefault(rel, set())

        for pf in py_files:
            rel = str(pf.relative_to(self.root))
            try:
                source = pf.read_text(encoding="utf-8", errors="replace")
                self.loc[rel] = source.count("\n") + 1
                tree = ast.parse(source, filename=str(pf))
            except (SyntaxError, UnicodeDecodeError):
                self.loc.setdefault(rel, 0)
                continue

            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        targets.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    level = node.level
                    resolved = self._resolve_import(module, level, pf)
                    if resolved:
                        targets.append(resolved)
                    else:
                        targets.append(module)
                else:
                    continue

                for target in targets:
                    dep = self._module_to_file(target)
                    if dep and dep in self.files and dep != rel:
                        self.imports[rel].add(dep)
                        self.imported_by.setdefault(dep, set()).add(rel)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def _compute_dependents(self, filepath: str) -> set[str]:
        """BFS on reverse edges; cached."""
        if filepath in self._br_cache:
            return self._br_cache[filepath]
        if filepath not in self.files:
            return set()
        visited: set[str] = set()
        queue = deque([filepath])
        while queue:
            node = queue.popleft()
            for dep in self.imported_by.get(node, set()):
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)
        self._br_cache[filepath] = visited
        return visited

    def blast_radius(self, filepath: str) -> int:
        """Count of files transitively dependent on filepath."""
        return len(self._compute_dependents(filepath))

    def blast_ratio(self, filepath: str) -> float:
        total = len(self.files)
        if total <= 1:
            return 0.0
        return self.blast_radius(filepath) / (total - 1)

    def dependents(self, filepath: str) -> list[str]:
        """Return all files transitively dependent on filepath."""
        return sorted(self._compute_dependents(filepath))

    def dependencies(self, filepath: str) -> list[str]:
        """Return all files that filepath transitively depends on."""
        if filepath not in self.files:
            return []
        visited: set[str] = set()
        queue = deque([filepath])
        while queue:
            node = queue.popleft()
            for dep in self.imports.get(node, set()):
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)
        return sorted(visited)

    def directory_summary(self) -> list[dict]:
        """Aggregate blast radius by directory (for treemap views)."""
        dirs: dict[str, dict] = {}
        for f in self.files:
            d = str(Path(f).parent)
            if d not in dirs:
                dirs[d] = {"path": d, "file_count": 0, "total_loc": 0,
                           "max_blast_radius": 0, "avg_blast_ratio": 0.0,
                           "files": []}
            info = dirs[d]
            info["file_count"] += 1
            info["total_loc"] += self.loc.get(f, 0)
            br = self.blast_radius(f)
            info["max_blast_radius"] = max(info["max_blast_radius"], br)
            info["files"].append(f)

        for info in dirs.values():
            if info["file_count"]:
                info["avg_blast_ratio"] = round(
                    sum(self.blast_ratio(f) for f in info["files"]) / info["file_count"], 4
                )
            del info["files"]  # don't send file list in summary

        return sorted(dirs.values(), key=lambda x: x["max_blast_radius"], reverse=True)

    def to_json(self) -> dict:
        """Serialize the graph for the frontend."""
        nodes = []
        for f in sorted(self.files):
            br = self.blast_radius(f)
            nodes.append({
                "id": f,
                "blast_radius": br,
                "blast_ratio": round(self.blast_ratio(f), 4),
                "loc": self.loc.get(f, 0),
                "imports_count": len(self.imports.get(f, set())),
                "imported_by_count": len(self.imported_by.get(f, set())),
                "directory": str(Path(f).parent),
            })
        edges = []
        for src, targets in sorted(self.imports.items()):
            for tgt in sorted(targets):
                edges.append({"source": src, "target": tgt})
        return {
            "nodes": nodes,
            "edges": edges,
            "total_files": len(self.files),
            "directories": self.directory_summary(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_py_files(self) -> list[Path]:
        """Walk the project tree and collect all .py files."""
        result: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [
                d for d in dirnames
                if d not in self.exclude and not d.endswith(".egg-info")
            ]
            for fn in filenames:
                if fn.endswith(".py"):
                    result.append(Path(dirpath) / fn)
        return sorted(result)

    def _resolve_import(self, module: str, level: int, source_file: Path) -> str | None:
        """Resolve a relative import to a dotted module path."""
        if level == 0:
            return None
        pkg_dir = source_file.parent
        for _ in range(level - 1):
            pkg_dir = pkg_dir.parent
        try:
            rel = pkg_dir.relative_to(self.root)
        except ValueError:
            return None
        parts = list(rel.parts)
        if module:
            parts.extend(module.split("."))
        return ".".join(parts)

    def _module_to_file(self, dotted: str) -> str | None:
        """Convert a dotted module path to a relative file path, or None if external."""
        parts = dotted.split(".")
        # Try as module file: a/b/c.py
        candidate = Path(*parts).with_suffix(".py")
        if (self.root / candidate).is_file():
            return str(candidate)
        # Try as package: a/b/c/__init__.py
        candidate = Path(*parts) / "__init__.py"
        if (self.root / candidate).is_file():
            return str(candidate)
        # Try partial: strip trailing parts (e.g. "from src.main import X" -> src/main.py)
        for i in range(len(parts), 0, -1):
            sub = parts[:i]
            candidate = Path(*sub).with_suffix(".py")
            if (self.root / candidate).is_file():
                return str(candidate)
            candidate = Path(*sub) / "__init__.py"
            if (self.root / candidate).is_file():
                return str(candidate)
        return None
