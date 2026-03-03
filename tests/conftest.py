"""Shared fixtures for context engineering tests."""

import json
import sys
import os
import pytest

# Make src importable from tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


SAMPLE_MESSAGES_2_ROUNDS = [
    {"role": "user", "content": "Fix the null pointer bug in auth.py"},
    {"role": "assistant", "content": "I'll read the file first. Found it on line 42 — missing null check. Fixed."},
    {"role": "user", "content": "Can you add a test for that?"},
    {"role": "assistant", "content": "Added test_auth_null_check to tests/test_auth.py."},
]

SAMPLE_MESSAGES_1_ROUND = [
    {"role": "user", "content": "What does this function do?"},
    {"role": "assistant", "content": "It validates the JWT token expiry."},
]


@pytest.fixture
def traces_dir(tmp_path):
    """A temp directory with two sample trace files."""
    d = tmp_path / "traces"
    d.mkdir()
    t1 = {
        "session_id": "session_001",
        "timestamp": "2026-03-01T10:00:00Z",
        "messages": SAMPLE_MESSAGES_2_ROUNDS,
    }
    t2 = {
        "session_id": "session_002",
        "timestamp": "2026-03-01T14:00:00Z",
        "messages": SAMPLE_MESSAGES_1_ROUND,
    }
    (d / "session_001.json").write_text(json.dumps(t1))
    (d / "session_002.json").write_text(json.dumps(t2))
    return d


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def empty_playbook():
    return """\
## CODING_PATTERNS

## WORKFLOW_STRATEGIES

## COMMON_MISTAKES

## TOOL_USAGE
"""


@pytest.fixture
def populated_playbook():
    return """\
## CODING_PATTERNS
[pat-00001] Always read files before editing them.

## WORKFLOW_STRATEGIES
[wf-00002] Explore the repo structure before making changes.

## COMMON_MISTAKES
[mis-00003] Do not assume file paths without checking.

## TOOL_USAGE
"""
