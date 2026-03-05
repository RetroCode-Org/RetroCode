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
        results.append((row["session_id"], row["reward"], bool(feat)))

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
    lines = ["\n" + "=" * 60, "  HYPOTHESIS VERIFICATION REPORT", "=" * 60]
    sig = [h for h in ranked if h.is_significant]
    insig = [h for h in ranked if not h.is_significant]

    lines.append(f"\nSIGNIFICANT ({len(sig)}):")
    for h in sig:
        lines.append(h.summary())

    lines.append(f"\nNOT SIGNIFICANT ({len(insig)}):")
    for h in insig:
        lines.append(h.summary())

    return "\n".join(lines)
