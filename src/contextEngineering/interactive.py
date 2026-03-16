"""Interactive playbook curation mode (--verbose).

Shows candidate skill updates 5 at a time, lets the user pick which to keep.
"""
from __future__ import annotations

import re
import sys
from typing import Optional

from .curator import apply_operations, get_playbook_stats, SECTION_PREFIXES


def _render_candidate(idx: int, op: dict) -> str:
    """Render a single candidate operation for terminal display."""
    op_type = op.get("type", "?")
    section = op.get("section", "")
    bullet_id = op.get("id", "")

    if op_type == "ADD":
        content = op.get("content", "")
        return f"  \033[32m[{idx}] + ADD to {section}\033[0m\n      {content}"

    elif op_type == "MODIFY":
        content = op.get("content", "")
        return f"  \033[33m[{idx}] ~ MODIFY {bullet_id}\033[0m\n      {content}"

    elif op_type == "DELETE":
        return f"  \033[31m[{idx}] - DELETE {bullet_id}\033[0m"

    return f"  [{idx}] ? {op_type}: {op}"


def interactive_curate(
    playbook: str,
    operations: list[dict],
    next_global_id: int,
    batch_size: int = 5,
) -> tuple[str, int, list[dict]]:
    """Present operations to user in batches of `batch_size` for approval.

    Returns (updated_playbook, new_next_id, selected_operations).
    """
    if not operations:
        print("\n  No changes proposed.")
        return playbook, next_global_id, []

    stats = get_playbook_stats(playbook)
    print(f"\n{'=' * 60}")
    print("  PLAYBOOK UPDATE — review proposed changes")
    print(f"{'=' * 60}")
    print(f"  Current skills: {stats['total_bullets']}")
    print(f"  Proposed changes: {len(operations)}")

    selected: list[dict] = []
    for batch_start in range(0, len(operations), batch_size):
        batch = operations[batch_start : batch_start + batch_size]
        batch_end = min(batch_start + batch_size, len(operations))

        print(f"\n{'─' * 60}")
        print(f"  Candidates {batch_start + 1}-{batch_end} of {len(operations)}:")
        print()

        for i, op in enumerate(batch):
            global_idx = batch_start + i + 1
            print(_render_candidate(global_idx, op))
            print()

        # Get user selection
        print(f"  Enter numbers to keep (e.g. {batch_start+1},{batch_start+2}),")
        print(f"  'a' for all, 's' to skip all, or 'q' to quit:")
        try:
            raw = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Aborted.")
            break

        if raw.lower() == "q":
            print("  Stopped.")
            break
        elif raw.lower() == "a":
            selected.extend(batch)
            print(f"  Kept all {len(batch)}")
        elif raw.lower() == "s":
            print(f"  Skipped all {len(batch)}")
        else:
            try:
                indices = {int(x.strip()) for x in raw.split(",") if x.strip()}
                for i, op in enumerate(batch):
                    global_idx = batch_start + i + 1
                    if global_idx in indices:
                        selected.append(op)
                kept = len([i for i in indices if batch_start < i <= batch_end])
                print(f"  Kept {kept} of {len(batch)}")
            except ValueError:
                print("  Invalid input, skipping this batch.")

    if not selected:
        print("\n  No changes selected. Playbook unchanged.")
        return playbook, next_global_id, []

    # Apply selected operations
    print(f"\n  Applying {len(selected)} selected changes ...")
    updated, new_id = apply_operations(playbook, selected, next_global_id)

    adds = sum(1 for o in selected if o["type"] == "ADD")
    mods = sum(1 for o in selected if o["type"] == "MODIFY")
    dels = sum(1 for o in selected if o["type"] == "DELETE")
    print(f"  Done: +{adds} added, ~{mods} modified, -{dels} deleted")

    return updated, new_id, selected
