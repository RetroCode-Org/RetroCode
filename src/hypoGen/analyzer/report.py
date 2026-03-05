"""
Report generation: HYPOTHESES.md, results.json, features.py.
"""
from __future__ import annotations

import inspect
import json
import re
from datetime import date
from pathlib import Path

from src.hypoGen.generator.hypothesis import Hypothesis


def save_results_json(hypotheses: list[Hypothesis], path: str):
    """Write hypothesis verification results to JSON."""
    out = []
    for h in hypotheses:
        out.append({
            "id": h.id,
            "description": h.description,
            "toxic": h.toxic,
            "significant": h.is_significant,
            "n_pos": h.n_pos,
            "n_neg": h.n_neg,
            "pass_rate_pos": round(h.pass_rate_pos, 4),
            "pass_rate_neg": round(h.pass_rate_neg, 4),
            "p_value": round(h.p_value, 6),
            "odds_ratio": round(h.odds_ratio, 4),
            "or_ci": [round(h.or_ci_lo, 4), round(h.or_ci_hi, 4)],
        })
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"Results saved to {path}")


def save_features_py(hypotheses: list[Hypothesis], path: str):
    """Write every hypothesis feature function to a standalone Python file."""
    lines = [
        '"""',
        "Auto-generated feature functions for Claude Code trace hypotheses.",
        "Each function takes msgs (list[dict]) and returns bool.",
        '"""',
        "from __future__ import annotations",
        "import json, re",
        "from src.hypoGen.generator.hypothesis import (",
        "    get_early_pct, iter_tool_calls, iter_tool_results, _parse_args,",
        "    EDIT_TOOLS, READ_TOOLS, SEARCH_TOOLS, BASH_TOOL, AGENT_TOOL, ERROR_KWS,",
        ")",
        "",
    ]

    for h in hypotheses:
        sig_mark = "SIGNIFICANT" if h.is_significant else "not significant"
        src = h.code_src
        if not src:
            try:
                src = inspect.getsource(h.feature_fn)
            except Exception:
                src = f"def feat_{h.id}(msgs):\n    raise NotImplementedError\n"

        src = re.sub(r"^def \w+\(", f"def feat_{h.id}(", src, count=1)

        lines.append(
            f"# {sig_mark}  |  OR={h.odds_ratio:.2f}  p={h.p_value:.4f}"
        )
        lines.append(f"# {h.description}")
        lines.append(src.rstrip())
        lines.append("")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Feature functions saved to {path}")


def update_hypotheses_md(
    hypotheses: list[Hypothesis],
    n_sessions: int,
    md_path: str,
    label: str = "sessions",
):
    """Write a human-readable HYPOTHESES.md report."""
    sig = [h for h in hypotheses if h.is_significant]
    insig = [h for h in hypotheses if not h.is_significant]

    def row(h: Hypothesis) -> str:
        desc = re.sub(r"^\[(TOXIC|HEALTHY)\] ", "", h.description).strip()
        or_str = f"{h.odds_ratio:.2f} [{h.or_ci_lo:.2f}, {h.or_ci_hi:.2f}]"
        p_str = "<0.001" if h.p_value < 0.001 else f"{h.p_value:.3f}"
        # show rejected counts explicitly: n_rejected = rounds where signal=T/F AND reward=0
        n_rej_T = round(h.n_pos * (1 - h.pass_rate_pos))
        n_rej_F = round(h.n_neg * (1 - h.pass_rate_neg))
        return (
            f"| `{h.id}` | {desc} | {h.n_pos:,} | {n_rej_T} | {h.n_neg:,} | {n_rej_F} | "
            f"{or_str} | {p_str} |"
        )

    header = (
        "| ID | Description | rounds(signal) | rejected(signal) | rounds(no-signal) | rejected(no-signal) "
        "| OR [95% CI] | p-value |\n"
        "|---|---|---:|---:|---:|---:|---|---:|"
    )

    lines = [
        "# Claude Code Round Hypothesis Tracker",
        "",
        f"**{label.capitalize()} analyzed:** {n_sessions}",
        f"**Last updated:** {date.today().isoformat()}",
        "**Significance criteria:** global p < 0.05",
        "",
        "---",
        "",
        "## Significant",
        "",
        header,
    ]
    lines += [row(h) for h in sig] if sig else [
        "| -- | No significant hypotheses yet | | | | | | |"
    ]

    lines += [
        "",
        "---",
        "",
        "## Not Significant",
        "",
        header,
    ]
    lines += [row(h) for h in insig] if insig else ["| -- | None | | | | | | |"]

    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"HYPOTHESES.md updated -> {md_path}")
