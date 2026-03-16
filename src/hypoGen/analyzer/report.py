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
        rej_rate_signal = (1 - h.pass_rate_pos) if h.n_pos else 0
        rej_rate_baseline = (1 - h.pass_rate_neg) if h.n_neg else 0
        out.append({
            "id": h.id,
            "description": h.description,
            "toxic": h.toxic,
            "significant": h.is_significant,
            "n_pos": h.n_pos,
            "n_neg": h.n_neg,
            "rejection_rate_when_signal": round(rej_rate_signal, 4),
            "rejection_rate_baseline": round(rej_rate_baseline, 4),
            "pass_rate_pos": round(h.pass_rate_pos, 4),
            "pass_rate_neg": round(h.pass_rate_neg, 4),
            "p_value": round(h.p_value, 6),
            "odds_ratio": round(h.odds_ratio, 4),
            "or_ci": [round(h.or_ci_lo, 4), round(h.or_ci_hi, 4)],
        })
    # Sort: significant first, then by p-value
    out.sort(key=lambda x: (not x["significant"], x["p_value"]))
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
    n_rounds: int = 0,
    n_sessions: int = 0,
    md_path: str = "HYPOTHESES.md",
):
    """Write a human-readable HYPOTHESES.md report.

    Accepts either n_rounds or n_sessions for backwards compat.
    """
    total = n_rounds or n_sessions
    unit = "rounds" if n_rounds else "sessions"
    sig = [h for h in hypotheses if h.is_significant]
    insig = [h for h in hypotheses if not h.is_significant]

    def row(h: Hypothesis) -> str:
        desc = re.sub(r"^\[(TOXIC|HEALTHY)\] ", "", h.description).strip()
        or_str = f"{h.odds_ratio:.2f} [{h.or_ci_lo:.2f}, {h.or_ci_hi:.2f}]"
        p_str = "<0.001" if h.p_value < 0.001 else f"{h.p_value:.3f}"
        n_rej_T = round(h.n_pos * (1 - h.pass_rate_pos))
        n_rej_F = round(h.n_neg * (1 - h.pass_rate_neg))
        return (
            f"| `{h.id}` | {desc} | {h.n_pos:,} | {n_rej_T} | {h.n_neg:,} | {n_rej_F} | "
            f"{or_str} | {p_str} |"
        )

    def interpret(h: Hypothesis) -> str:
        """Plain-English one-liner explaining what the hypothesis means."""
        desc = re.sub(r"^\[(TOXIC|HEALTHY)\] ", "", h.description).strip()
        n_rej_T = round(h.n_pos * (1 - h.pass_rate_pos))
        rej_rate_T = (1 - h.pass_rate_pos) * 100 if h.n_pos else 0
        rej_rate_F = (1 - h.pass_rate_neg) * 100 if h.n_neg else 0
        return (
            f"When this signal fires, {rej_rate_T:.0f}% of rounds are rejected "
            f"(vs {rej_rate_F:.0f}% baseline). "
            f"Seen in {h.n_pos} of {h.n_pos + h.n_neg} rounds."
        )

    header = (
        "| ID | Description | rounds(signal) | rejected | rounds(no signal) | rejected "
        "| OR [95% CI] | p |\n"
        "|---|---|---:|---:|---:|---:|---|---:|"
    )

    lines = [
        "# What triggers users to say No?",
        "",
        "Hypotheses about Claude Code agent behavior patterns that predict",
        "the user explicitly rejecting or correcting the agent's work.",
        "",
        f"**{unit.capitalize()} analyzed:** {total:,}",
        f"**Last updated:** {date.today().isoformat()}",
        f"**Rejected rounds:** {sum(1 for h in hypotheses[:1] for _ in [0] if total)}",
        "**Significance:** p < 0.05 (chi-squared test)",
        "",
        "---",
        "",
    ]

    sig_toxic = [h for h in sig if h.toxic]
    sig_healthy = [h for h in sig if not h.toxic]

    if sig_toxic:
        lines += [
            "## Significant toxic patterns",
            "",
            "These agent behaviors are statistically linked to user rejection:",
            "",
            header,
        ]
        lines += [row(h) for h in sig_toxic]
        lines += [""]
        for h in sig_toxic:
            lines.append(f"- **`{h.id}`**: {interpret(h)}")
        lines += [""]

    if sig_healthy:
        lines += [
            "## Significant healthy patterns",
            "",
            "These agent behaviors are statistically linked to user acceptance:",
            "",
            header,
        ]
        lines += [row(h) for h in sig_healthy]
        lines += [""]
        for h in sig_healthy:
            lines.append(f"- **`{h.id}`**: {interpret(h)}")
        lines += [""]

    if not sig:
        lines += [
            "## Significant patterns",
            "",
            "No statistically significant patterns found yet. Gather more traces.",
            "",
        ]

    lines += [
        "---",
        "",
        "## Not yet significant",
        "",
        "These patterns showed a trend but need more data:",
        "",
        header,
    ]
    lines += [row(h) for h in insig] if insig else ["| -- | None | | | | | | |"]

    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"HYPOTHESES.md updated -> {md_path}")
