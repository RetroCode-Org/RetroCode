"""Load and expose retro configuration.

Config is read from <working_dir>/retro_config.yaml at runtime.
If the file doesn't exist, built-in defaults are used.

Usage:
    from src.retro_config import load_config
    cfg = load_config(working_dir)
    cfg.poll_interval  # 30
"""

from dataclasses import dataclass, field
from pathlib import Path
import yaml

CONFIG_FILENAME = "retro_config.yaml"

# ---------------------------------------------------------------------------
# Compatibility matrix defaults
# ---------------------------------------------------------------------------
# inputs:  which agent trace sources to ingest
# outputs: which agent rule files to update
#
# | input source | trace location                                   |
# |--------------|--------------------------------------------------|
# | claude-code  | ~/.claude/projects/<key>/*.jsonl                 |
# | cursor       | ~/.cursor/projects/<key>/agent-transcripts/*/*.jsonl |
# | codex        | ~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl (filtered by cwd) |
#
# | output target | file written                                    |
# |---------------|------------------------------------------------|
# | claude-code   | CLAUDE.md  (between retro markers)             |
# | cursor        | .cursor/rules/retro.mdc  (alwaysApply: true)   |
# | codex         | AGENTS.md  (between retro markers)             |

_DEFAULTS = {
    "daemon": {
        "poll_interval": 30,
        "min_rounds": 2,
        "pid_file": ".retro.pid",
        "retro_dir": ".retro",
    },
    "playbook": {
        "max_bullets": 40,
        "default_model": "gpt-5.2",
        "batch_size": 4,
        "sections": {
            "CODING_PATTERNS": "coding",
            "WORKFLOW_STRATEGIES": "workflow",
            "COMMUNICATION": "communication",
            "COMMON_MISTAKES": "mistake",
            "TOOL_USAGE": "tool",
            "OTHERS": "other",
        },
    },
    "sources": {
        "inputs":  ["claude-code", "cursor", "codex"],
        "outputs": ["claude-code"],
    },
}


@dataclass
class RetroConfig:
    # Daemon
    poll_interval: int
    min_rounds: int
    pid_file: str
    retro_dir: str
    # Playbook
    max_bullets: int
    default_model: str
    batch_size: int
    section_prefixes: dict[str, str]
    # Compatibility matrix
    inputs: list[str]   # which trace sources to ingest
    outputs: list[str]  # which agent rule files to update


def load_config(working_dir: str | Path) -> RetroConfig:
    """Load config from <working_dir>/retro_config.yaml, falling back to defaults."""
    cfg = _deep_merge(_DEFAULTS, _load_yaml(working_dir))
    d = cfg["daemon"]
    p = cfg["playbook"]
    s = cfg["sources"]
    return RetroConfig(
        poll_interval=d["poll_interval"],
        min_rounds=d["min_rounds"],
        pid_file=d["pid_file"],
        retro_dir=d["retro_dir"],
        max_bullets=p["max_bullets"],
        default_model=p["default_model"],
        batch_size=p["batch_size"],
        section_prefixes=p["sections"],
        inputs=s["inputs"],
        outputs=s["outputs"],
    )


def _load_yaml(working_dir: str | Path) -> dict:
    path = Path(working_dir) / CONFIG_FILENAME
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
