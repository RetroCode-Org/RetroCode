"""
Statistical verification of hypotheses.

Global chi-squared test + odds ratio (no within-issue concordance for user traces).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.stats import chi2_contingency

from src.hypoGen.generator.hypothesis import Hypothesis


def _odds_ratio_ci(a: int, b: int, c: int, d: int, z: float = 1.96):
    """
    2x2 table:
        feature=T  feature=F
    pass   a          b
    fail   c          d

    Returns (OR, lo, hi) with Haldane-Anscombe correction for zeros.
    """
    a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    or_ = (a * d) / (b * c)
    log_or = math.log(or_)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return or_, math.exp(log_or - z * se), math.exp(log_or + z * se)


def _chi2(a: int, b: int, c: int, d: int) -> float:
    """Return p-value from chi-squared test on 2x2 contingency table."""
    table = np.array([[a, b], [c, d]])
    if table.sum() == 0 or 0 in table.sum(axis=0) or 0 in table.sum(axis=1):
        return 1.0
    _, p, _, _ = chi2_contingency(table, correction=False)
    return float(p)


def verify(hyp: Hypothesis, rows: list[dict[str, Any]]) -> Hypothesis:
    """
    Run global verification test. Updates hyp in-place and returns it.

    rows must have keys: reward (0.0 or 1.0), msgs (list[dict]).
    Works for both session rows and round rows.
    """
    results = []
    for row in rows:
        try:
            feat = hyp.feature_fn(row["msgs"])
        except Exception:
            feat = False
        row_id = row.get("round_id") or row.get("session_id", "")
        results.append((row_id, row["reward"], bool(feat)))

    # 2x2 table: rows = pass/fail, cols = feature T/F
    pass_T = sum(1 for _, rw, ft in results if rw == 1.0 and ft)
    pass_F = sum(1 for _, rw, ft in results if rw == 1.0 and not ft)
    fail_T = sum(1 for _, rw, ft in results if rw == 0.0 and ft)
    fail_F = sum(1 for _, rw, ft in results if rw == 0.0 and not ft)

    n_T = pass_T + fail_T
    n_F = pass_F + fail_F

    hyp.n_pos = n_T
    hyp.n_neg = n_F
    hyp.pass_rate_pos = pass_T / n_T if n_T else 0.0
    hyp.pass_rate_neg = pass_F / n_F if n_F else 0.0
    hyp.p_value = _chi2(pass_T, pass_F, fail_T, fail_F)
    hyp.odds_ratio, hyp.or_ci_lo, hyp.or_ci_hi = _odds_ratio_ci(
        pass_T, pass_F, fail_T, fail_F
    )

    return hyp


def report(hypotheses: list[Hypothesis]) -> str:
    """Print a ranked summary of all verified hypotheses."""
    ranked = sorted(hypotheses, key=lambda h: (not h.is_significant, h.p_value))
    sig = [h for h in ranked if h.is_significant]
    insig = [h for h in ranked if not h.is_significant]

    sig_toxic = [h for h in sig if h.toxic]
    sig_healthy = [h for h in sig if not h.toxic]

    lines = [
        "\n" + "=" * 60,
        "  WHAT TRIGGERS USERS TO SAY NO?",
        "=" * 60,
        f"\n  {len(ranked)} hypotheses tested  |  {len(sig)} significant",
    ]

    if sig_toxic:
        lines.append(f"\nSIGNIFICANT TOXIC — these patterns predict rejection (p < 0.05):")
        for h in sig_toxic:
            rej_when = (1 - h.pass_rate_pos) * 100
            rej_base = (1 - h.pass_rate_neg) * 100
            lines.append(
                f"\n  {h.id}"
                f"\n    {h.description}"
                f"\n    rejection rate: {rej_when:.0f}% when signal fires vs {rej_base:.0f}% baseline"
                f"\n    OR={h.odds_ratio:.2f}  p={h.p_value:.4f}  (n={h.n_pos}+{h.n_neg})"
            )

    if sig_healthy:
        lines.append(f"\nSIGNIFICANT HEALTHY — these patterns predict acceptance (p < 0.05):")
        for h in sig_healthy:
            acc_when = h.pass_rate_pos * 100
            acc_base = h.pass_rate_neg * 100
            lines.append(
                f"\n  {h.id}"
                f"\n    {h.description}"
                f"\n    acceptance rate: {acc_when:.0f}% when signal fires vs {acc_base:.0f}% baseline"
                f"\n    OR={h.odds_ratio:.2f}  p={h.p_value:.4f}  (n={h.n_pos}+{h.n_neg})"
            )

    if not sig:
        lines.append("\nNo significant patterns found yet.")

    if insig:
        lines.append(f"\nNOT SIGNIFICANT ({len(insig)}):")
        for h in insig:
            direction = "toxic" if h.toxic else "healthy"
            lines.append(f"  {h.id:35s}  p={h.p_value:.4f}  OR={h.odds_ratio:.2f}  ({direction})")

    return "\n".join(lines)
