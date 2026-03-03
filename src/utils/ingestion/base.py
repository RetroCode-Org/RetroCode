"""
Abstract base class for tool-specific trace readers.

To add support for a new tool, subclass BaseReader and implement all
abstract methods, then pass an instance to run_daemon() in src/main.py.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseReader(ABC):

    @property
    @abstractmethod
    def tool_name(self) -> str:
        """Human-readable name of the tool whose traces this reader handles."""

    @abstractmethod
    def find_trace_files(self, working_dir: str | Path) -> list[Path]:
        """Return all trace files relevant to *working_dir*, sorted."""

    @abstractmethod
    def read_head_tail(self, filepath: Path, n: int = 5) -> tuple[list[str], list[str]]:
        """Return (head, tail) where each is at most *n* lines from *filepath*.

        If the file has <= n lines, tail should be empty to avoid duplication.
        Lines must be stripped of their trailing newline.
        """
