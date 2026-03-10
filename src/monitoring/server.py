"""HTTP server for the blast radius monitoring dashboard.

Uses stdlib http.server -- no Flask/FastAPI dependency needed.

Endpoints:
    GET  /                     -> dashboard HTML
    GET  /api/risk-summary     -> overall health, review queue, hotspots
    GET  /api/sessions         -> sessions with narratives + risk levels
    GET  /api/session/<id>     -> round detail + "safe to ship?" summary
    GET  /api/codebase-health  -> files grouped by tier with edit frequency
    GET  /api/timeline         -> chronological edit events
    GET  /api/graph            -> raw dependency graph (for drill-down)
    GET  /api/file/<path>      -> single file detail
    GET  /api/status           -> server health
    POST /api/refresh          -> re-scan traces and rebuild graph
    POST /api/file-chat        -> summarize recent file edits with an LLM
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

from .depgraph import DependencyGraph
from .file_edit_extractor import extract_all_sessions, SessionSummary


_DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"
_FAVICON_PATH = Path(__file__).parent.parent.parent / "assets" / "imgs" / "retro-pilot.png"


# -----------------------------------------------------------------------
# Tier classification
# -----------------------------------------------------------------------

def file_tier(blast_ratio: float) -> int:
    """Classify a file into a risk tier based on blast ratio.

    Tier 1: Critical infrastructure (>=50% of codebase depends on it)
    Tier 2: Shared component (20-50%)
    Tier 3: Feature-specific (5-20%)
    Tier 4: Leaf node (<5%)
    """
    if blast_ratio >= 0.50:
        return 1
    if blast_ratio >= 0.20:
        return 2
    if blast_ratio >= 0.05:
        return 3
    return 4


_TIER_LABELS = {
    1: "Critical Infrastructure",
    2: "Shared Component",
    3: "Feature-Specific",
    4: "Leaf Node",
}

_TIER_DESCRIPTIONS = {
    1: "Changes here affect >50% of the codebase",
    2: "Changes here affect many shared components",
    3: "Changes here are contained to specific features",
    4: "Safe to iterate -- no other files depend on this",
}


def risk_score(blast_ratio: float, edit_count: int) -> float:
    """Composite risk: high blast ratio + frequently edited = danger."""
    return blast_ratio * (1 + 0.5 * max(0, edit_count - 1))


# -----------------------------------------------------------------------
# Guidance heuristics
# -----------------------------------------------------------------------

def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _is_test_file(file_path: str) -> bool:
    path = Path(file_path)
    return (
        "tests" in path.parts
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
    )


def _candidate_test_paths(file_path: str) -> list[str]:
    path = Path(file_path)
    if _is_test_file(file_path):
        return [str(path)]
    if path.suffix != ".py":
        return []

    stem = path.parent.name if path.stem == "__init__" else path.stem
    roots = [Path("tests")]
    if path.parts and path.parts[0] == "src":
        roots.append(Path("tests", *path.parts[1:-1]))
    roots.append(Path("tests", *path.parts[:-1]))

    candidates: list[str] = []
    for root in roots:
        candidates.append(str(root / f"test_{stem}.py"))
        candidates.append(str(root / f"{stem}_test.py"))
    return _dedupe_keep_order(candidates)


def _obvious_test_status(file_path: str, working_dir: str) -> tuple[bool | None, list[str]]:
    if _is_test_file(file_path):
        return True, [file_path]
    candidates = _candidate_test_paths(file_path)
    if not candidates:
        return None, []
    root = Path(working_dir)
    existing = [candidate for candidate in candidates if (root / candidate).is_file()]
    return bool(existing), existing or candidates[:3]


def _file_guidance(
    file_path: str,
    graph: DependencyGraph,
    edit_count: int,
    working_dir: str,
) -> dict:
    ratio = graph.blast_ratio(file_path)
    tier = file_tier(ratio)
    blast = graph.blast_radius(file_path)
    loc = graph.loc.get(file_path, 0)
    has_test, test_paths = _obvious_test_status(file_path, working_dir)

    signals: list[dict] = []
    recommendations: list[str] = []

    def add_signal(signal_id: str, label: str, tone: str, reason: str):
        signals.append({
            "id": signal_id,
            "label": label,
            "tone": tone,
            "reason": reason,
        })

    if tier <= 2 and edit_count <= 1 and blast > 0:
        add_signal(
            "quiet-core",
            "Critical + quiet",
            "red",
            "Large dependency surface with very little recent edit history.",
        )
        recommendations.extend([
            "Read the diff manually before merging.",
            "Run or add a focused regression test for the main call path.",
            "Keep rollout small or behind a flag if possible.",
        ])
    elif tier <= 2 and blast > 0:
        add_signal(
            "load-bearing",
            "Load-bearing",
            "red",
            "A lot of the codebase depends on this file.",
        )
        recommendations.extend([
            "Review the downstream callers before shipping.",
            "Prefer one narrow change over several stacked prompts here.",
        ])
    elif tier == 3 and blast >= 5 and edit_count <= 1:
        add_signal(
            "shared-quiet",
            "Shared + quiet",
            "yellow",
            "Touches a shared area that does not change often.",
        )
        recommendations.extend([
            "Check the adjacent feature paths by hand.",
            "Capture the expected behavior before asking for more edits.",
        ])

    if edit_count >= 3 and tier <= 3:
        add_signal(
            "churn",
            "Churning",
            "yellow",
            f"Edited in {edit_count} different sessions.",
        )
        recommendations.extend([
            "Pause and write down the invariant the agent is trying to reach.",
            "Compare the last two diffs before prompting again.",
        ])

    if has_test is False and tier <= 3:
        add_signal(
            "test-gap",
            "No obvious test",
            "yellow",
            "Could not find a nearby regression test file.",
        )
        recommendations.extend([
            "Add a small regression test before broadening the change.",
        ])

    if loc >= 200 and tier <= 3:
        add_signal(
            "large-surface",
            "Large surface",
            "blue",
            f"{loc} lines in a shared or feature-critical area.",
        )
        recommendations.extend([
            "Prefer scoped edits or split the file before another large pass.",
        ])

    if file_path in graph.files and tier == 4 and blast == 0:
        add_signal(
            "safe-sandbox",
            "Safe sandbox",
            "green",
            "Leaf file with no transitive dependents.",
        )
        recommendations.extend([
            "Prototype here first if you need to explore behavior quickly.",
        ])

    return {
        "signals": signals[:4],
        "recommended_actions": _dedupe_keep_order(recommendations)[:4],
        "has_obvious_test": has_test,
        "test_paths": test_paths[:3],
    }


def _build_action_items(
    file_profiles: list[dict],
    sessions: list[SessionSummary],
) -> tuple[list[dict], dict]:
    def has_signal(profile: dict, signal_id: str) -> bool:
        return any(signal["id"] == signal_id for signal in profile["guidance"]["signals"])

    quiet_core = [
        profile for profile in file_profiles
        if has_signal(profile, "quiet-core") or has_signal(profile, "shared-quiet")
    ]
    churn = [profile for profile in file_profiles if has_signal(profile, "churn")]
    test_gap = [
        profile for profile in file_profiles
        if profile["guidance"]["has_obvious_test"] is False and profile["tier"] <= 3
    ]
    safe_zone = [profile for profile in file_profiles if has_signal(profile, "safe-sandbox")]

    broad_sessions = []
    for sess in sessions:
        if not sess.files_edited:
            continue
        unique_files = len(sess.files_edited)
        if unique_files >= 8:
            broad_sessions.append({
                "session_id": sess.session_id,
                "source": sess.source,
                "timestamp": sess.timestamp,
                "files_edited": unique_files,
            })

    action_items: list[dict] = []

    if quiet_core:
        action_items.append({
            "type": "quiet-core",
            "severity": "urgent",
            "title": "Hand-review the quiet shared/core files",
            "summary": "These files do not move often, but they sit on paths other code depends on.",
            "rationale": "When a quiet shared or core file changes, the blast radius is larger and the surrounding behavior is often less exercised by recent edits.",
            "steps": [
                "Read the diff manually instead of trusting the narrative alone.",
                "Run or add a focused regression test on the dependent path.",
                "Keep rollout narrow if this change lands.",
            ],
            "files": [
                {
                    "path": profile["path"],
                    "label": profile["impact_label"],
                }
                for profile in quiet_core[:3]
            ],
        })

    if churn:
        action_items.append({
            "type": "churn",
            "severity": "attention",
            "title": "Stabilize the files that keep getting touched",
            "summary": "The agent is revisiting the same files across sessions, which usually means the target behavior is still fuzzy.",
            "rationale": "Repeated prompting on the same shared files tends to accumulate accidental complexity faster than confidence.",
            "steps": [
                "Write down the intended invariant before another prompt.",
                "Compare the last two diffs side by side.",
                "Consider slicing the work into smaller, one-file passes.",
            ],
            "files": [
                {
                    "path": profile["path"],
                    "label": f"{profile['edit_count']} sessions",
                }
                for profile in churn[:3]
            ],
        })

    if test_gap:
        action_items.append({
            "type": "test-gap",
            "severity": "attention",
            "title": "Backfill tests around shared code",
            "summary": "Some touched files do not have an obvious nearby test file.",
            "rationale": "If the code is shared and the test path is unclear, the safest next move is usually a narrow regression test before more edits.",
            "steps": [
                "Add a focused regression test for the changed path.",
                "Capture the failure mode before continuing broad refactors.",
            ],
            "files": [
                {
                    "path": profile["path"],
                    "label": f"try {profile['guidance']['test_paths'][0].rsplit('/', 1)[-1]}" if profile["guidance"]["test_paths"] else "no candidate found",
                }
                for profile in test_gap[:3]
            ],
        })

    if broad_sessions:
        action_items.append({
            "type": "broad-session",
            "severity": "attention",
            "title": "Split the widest sessions into smaller passes",
            "summary": "A few sessions touched many files at once.",
            "rationale": "Wide sessions are harder to review and make it easier for the model to mix unrelated intent in one sweep.",
            "steps": [
                "Replay the session and separate unrelated edits into follow-up tasks.",
                "Review the highest-blast files first, then the leaf files.",
            ],
            "sessions": broad_sessions[:3],
        })

    if safe_zone:
        action_items.append({
            "type": "safe-zone",
            "severity": "opportunity",
            "title": "Use the safe sandbox files for exploration",
            "summary": "Some touched files are leaf nodes with almost no downstream risk.",
            "rationale": "If you want to keep iterating quickly, push experimentation into files that do not ripple through shared code.",
            "steps": [
                "Prototype behavior here before touching shared modules.",
                "Promote the change upward only after the leaf behavior feels stable.",
            ],
            "files": [
                {
                    "path": profile["path"],
                    "label": profile["impact_label"],
                }
                for profile in safe_zone[:3]
            ],
        })

    counts = {
        "quiet_core": len(quiet_core),
        "churn": len(churn),
        "test_gap": len(test_gap),
        "safe_zone": len(safe_zone),
        "broad_sessions": len(broad_sessions),
    }
    return action_items[:5], counts


# -----------------------------------------------------------------------
# Narrative generation (template-based, no LLM)
# -----------------------------------------------------------------------

def _generate_narrative(edited_files: list[str], graph: DependencyGraph) -> str:
    """Generate a plain-English summary for a set of edited files."""
    if not edited_files:
        return "No files were modified."

    # Group by directory
    dirs: dict[str, list[str]] = {}
    for f in edited_files:
        d = str(Path(f).parent)
        dirs.setdefault(d, []).append(f)

    n = len(edited_files)
    if len(dirs) == 1:
        dir_name = list(dirs.keys())[0]
        dir_phrase = f"in {dir_name}/"
    elif len(dirs) == 2:
        dir_phrase = f"across {' and '.join(d + '/' for d in dirs)}"
    else:
        dir_phrase = f"across {len(dirs)} directories"

    # Highest tier (lowest number = most critical)
    tiers = [file_tier(graph.blast_ratio(f)) for f in edited_files]
    highest = min(tiers) if tiers else 4

    impact = {
        1: "This could affect most of the codebase.",
        2: "This could affect several shared components.",
        3: "Impact is contained to specific features.",
        4: "Low risk -- only leaf files were changed.",
    }[highest]

    return f"Modified {n} file{'s' if n != 1 else ''} {dir_phrase}. {impact}"


def _scope_label(edited_files: list[str], graph: DependencyGraph) -> str:
    """Generate a scope classification like 'Affects all users'."""
    if not edited_files:
        return "No changes"

    tiers = [file_tier(graph.blast_ratio(f)) for f in edited_files]
    if 1 in tiers:
        return "Broad impact -- affects most code paths"
    if 2 in tiers:
        unique_dirs = sorted(set(str(Path(f).parent) for f in edited_files))
        if len(unique_dirs) <= 2:
            return f"Affects shared code in {', '.join(d + '/' for d in unique_dirs)}"
        return f"Affects shared components across {len(unique_dirs)} areas"
    unique_dirs = sorted(set(str(Path(f).parent) for f in edited_files))
    if len(unique_dirs) == 1:
        return f"Scoped to {unique_dirs[0]}/"
    return f"Scoped to {len(unique_dirs)} feature areas"


def _risk_level(edited_files: list[str], graph: DependencyGraph) -> str:
    """Classify session risk as high/medium/low."""
    if not edited_files:
        return "none"
    tiers = [file_tier(graph.blast_ratio(f)) for f in edited_files]
    if 1 in tiers:
        return "high"
    if 2 in tiers:
        return "medium"
    return "low"


def _review_summary(edited_files: list[str], graph: DependencyGraph) -> dict:
    """Generate 'Safe to Ship?' review guidance."""
    must_review = []
    worth_checking = []
    probably_fine = []

    for f in edited_files:
        ratio = graph.blast_ratio(f)
        tier = file_tier(ratio)
        br = graph.blast_radius(f)
        entry = {
            "path": f,
            "label": f"affects {br} files ({ratio*100:.0f}%)",
            "tier": tier,
        }

        if tier <= 1:
            must_review.append(entry)
        elif tier == 2:
            worth_checking.append(entry)
        else:
            probably_fine.append(entry)

    if not must_review and not worth_checking:
        recommendation = "All changes look low-risk. Safe to ship."
    elif must_review:
        paths = [e["path"] for e in must_review[:3]]
        recommendation = f"Review {', '.join(paths)} before deploying -- these are load-bearing files."
    else:
        paths = [e["path"] for e in worth_checking[:3]]
        recommendation = f"Worth checking {', '.join(paths)} -- they're shared components."

    return {
        "must_review": must_review,
        "worth_checking": worth_checking,
        "probably_fine": probably_fine,
        "recommendation": recommendation,
    }


def _build_file_edit_history(
    file_path: str,
    sessions: list[SessionSummary],
    graph: DependencyGraph,
) -> list[dict]:
    history: list[dict] = []
    for sess in sessions:
        if file_path not in sess.files_edited:
            continue
        session_narrative = _generate_narrative(sess.files_edited, graph)
        scope_label = _scope_label(sess.files_edited, graph)
        risk_level = _risk_level(sess.files_edited, graph)
        for rs in sess.rounds:
            preview = (rs.user_message or "").strip()[:220]
            for e in rs.edits:
                if e.file_path != file_path:
                    continue
                history.append({
                    "session_id": sess.session_id,
                    "source": sess.source,
                    "round_num": rs.round_num,
                    "tool_name": e.tool_name,
                    "action": e.action,
                    "timestamp": e.timestamp,
                    "session_narrative": session_narrative,
                    "scope_label": scope_label,
                    "risk_level": risk_level,
                    "user_message_preview": preview,
                })
    history.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return history


def _file_detail_payload(
    file_path: str,
    graph: DependencyGraph,
    sessions: list[SessionSummary],
    counts: Counter,
    working_dir: str,
    impact_label: str,
) -> dict:
    ratio = graph.blast_ratio(file_path)
    br = graph.blast_radius(file_path)
    tier = file_tier(ratio)
    edit_count = counts.get(file_path, 0)
    guidance = _file_guidance(file_path, graph, edit_count, working_dir)
    in_graph = file_path in graph.files
    deps = graph.dependents(file_path) if in_graph else []
    imports = graph.dependencies(file_path) if in_graph else []
    edit_history = _build_file_edit_history(file_path, sessions, graph)

    return {
        "path": file_path,
        "in_graph": in_graph,
        "loc": graph.loc.get(file_path, 0),
        "blast_radius": br,
        "blast_ratio": round(ratio, 4),
        "tier": tier,
        "tier_label": _TIER_LABELS[tier],
        "tier_description": _TIER_DESCRIPTIONS[tier],
        "edit_count": edit_count,
        "risk_score": round(risk_score(ratio, edit_count), 4),
        "impact_label": impact_label,
        "direct_imports": sorted(graph.imports.get(file_path, set())),
        "direct_imported_by": sorted(graph.imported_by.get(file_path, set())),
        "transitive_dependents": deps,
        "transitive_dependencies": imports,
        "edit_history": edit_history,
        "last_edit": edit_history[0] if edit_history else None,
        "signals": guidance["signals"],
        "recommended_actions": guidance["recommended_actions"],
        "has_obvious_test": guidance["has_obvious_test"],
        "test_paths": guidance["test_paths"],
    }


def _build_file_chat_context(file_detail: dict) -> dict:
    buckets: dict[str, dict] = {}
    for edit in file_detail["edit_history"]:
        bucket = buckets.setdefault(edit["source"], {
            "source": edit["source"],
            "edit_count": 0,
            "last_timestamp": None,
            "last_tool": None,
        })
        bucket["edit_count"] += 1
        if not bucket["last_timestamp"] or (edit["timestamp"] or "") > bucket["last_timestamp"]:
            bucket["last_timestamp"] = edit["timestamp"]
            bucket["last_tool"] = edit["tool_name"]

    recent_traces: list[dict] = []
    seen_rounds: set[tuple[str, int]] = set()
    for edit in file_detail["edit_history"]:
        key = (edit["session_id"], edit["round_num"])
        if key in seen_rounds:
            continue
        seen_rounds.add(key)
        recent_traces.append({
            "session_id": edit["session_id"],
            "source": edit["source"],
            "timestamp": edit["timestamp"],
            "round_num": edit["round_num"],
            "tool_name": edit["tool_name"],
            "session_narrative": edit["session_narrative"],
            "scope_label": edit["scope_label"],
            "risk_level": edit["risk_level"],
            "user_message_preview": edit["user_message_preview"],
        })

    return {
        "file": {
            "path": file_detail["path"],
            "tier": file_detail["tier"],
            "impact_label": file_detail["impact_label"],
            "blast_radius": file_detail["blast_radius"],
            "edit_count": file_detail["edit_count"],
            "risk_score": file_detail["risk_score"],
            "loc": file_detail["loc"],
            "has_obvious_test": file_detail["has_obvious_test"],
            "test_paths": file_detail["test_paths"][:3],
        },
        "signals": file_detail["signals"],
        "recommended_actions": file_detail["recommended_actions"],
        "direct_imports": file_detail["direct_imports"][:6],
        "direct_imported_by": file_detail["direct_imported_by"][:6],
        "editor_activity": sorted(
            buckets.values(),
            key=lambda item: (item["edit_count"], str(item["last_timestamp"] or "")),
            reverse=True,
        ),
        "recent_traces": recent_traces[:6],
    }


_FILE_CHAT_SYSTEM = """You explain AI-authored file changes to engineers.

Use only the monitor context you are given. Do not invent missing edits, traces,
tests, or dependencies. Focus on:
- what changed recently
- how different editors contributed
- what looks risky or stable
- what to review next

Keep the answer concise and actionable."""

_FILE_CHAT_TIMEOUT_S = 18


def _fallback_file_chat_answer(context: dict, question: str) -> str:
    file_info = context["file"]
    editor_activity = context["editor_activity"]
    traces = context["recent_traces"]
    session_count = file_info["edit_count"]
    event_count = sum(item["edit_count"] for item in editor_activity)
    editors = ", ".join(
        f"{item['source']} ({item['edit_count']})" for item in editor_activity
    ) or "no recorded editor activity"
    signals = ", ".join(signal["label"] for signal in context["signals"]) or "no special risk flags"
    next_steps = "; ".join(context["recommended_actions"][:2]) or "open the latest trace and inspect the touched round"
    latest = traces[0] if traces else None
    latest_line = (
        f" Most recent trace: {latest['source']} round {latest['round_num']} using {latest['tool_name']}."
        if latest else
        ""
    )
    question_hint = ""
    if "editor" in question.lower():
        question_hint = " The edit mix by editor is the clearest signal here."
    return (
        f"{file_info['path']} was touched in {session_count} AI session{'s' if session_count != 1 else ''} "
        f"with {event_count} recorded edit event{'s' if event_count != 1 else ''} from {editors}. "
        f"It is a tier {file_info['tier']} file with {file_info['blast_radius']} downstream dependents and {signals}.{latest_line}"
        f"{question_hint} Review next: {next_steps}."
    )


def _answer_file_chat(
    question: str,
    context: dict,
    *,
    model: str | None = None,
    llm_callable=None,
) -> tuple[str, bool, str | None]:
    question = " ".join(question.split()).strip()[:1000]
    prompt = json.dumps(
        {
            "question": question,
            "monitor_context": context,
        },
        indent=2,
    )

    if llm_callable is None:
        try:
            from src.utils.inference import call_llm as llm_callable
        except Exception as exc:  # pragma: no cover - dependency/config dependent
            return (
                _fallback_file_chat_answer(context, question),
                False,
                f"LLM unavailable, showing heuristic summary instead: {exc}",
            )

    try:
        result: dict[str, str] = {}
        failure: dict[str, Exception] = {}

        def _call_llm() -> None:
            try:
                result["answer"] = llm_callable(
                    _FILE_CHAT_SYSTEM,
                    prompt,
                    model=model,
                    max_tokens=700,
                    temperature=0.2,
                )
            except Exception as exc:  # pragma: no cover - exercised via wrapper
                failure["error"] = exc

        worker = threading.Thread(target=_call_llm, daemon=True)
        worker.start()
        worker.join(_FILE_CHAT_TIMEOUT_S)
        if worker.is_alive():
            return (
                _fallback_file_chat_answer(context, question),
                False,
                f"LLM timed out after {_FILE_CHAT_TIMEOUT_S}s, showing heuristic summary instead.",
            )
        if "error" in failure:
            raise failure["error"]
        answer = result.get("answer", "")
        return (answer or "").strip(), True, None
    except Exception as exc:  # pragma: no cover - network/provider dependent
        return (
            _fallback_file_chat_answer(context, question),
            False,
            f"LLM unavailable, showing heuristic summary instead: {exc}",
        )


# -----------------------------------------------------------------------
# State
# -----------------------------------------------------------------------

class _State:
    """Shared mutable state between the HTTP handler and the refresh thread."""

    def __init__(
        self,
        working_dir: str,
        exclude_dirs: list[str] | None = None,
        default_model: str | None = None,
    ):
        self.working_dir = working_dir
        self.exclude_dirs = exclude_dirs or []
        self.default_model = default_model
        self.graph = DependencyGraph(working_dir, exclude_dirs=self.exclude_dirs)
        self.sessions: list[SessionSummary] = []
        self.file_edit_counts: Counter = Counter()
        self.last_refresh: str = ""
        self.lock = threading.Lock()

    def refresh(self) -> None:
        """Rebuild the dependency graph, re-extract sessions, compute frequencies."""
        graph = DependencyGraph(self.working_dir, exclude_dirs=self.exclude_dirs)
        graph.build()
        sessions = extract_all_sessions(self.working_dir)

        # Compute per-file edit frequency (how many sessions touched each file)
        counts: Counter = Counter()
        for sess in sessions:
            # Count unique files per session (not per edit)
            seen_in_session: set[str] = set()
            for r in sess.rounds:
                for e in r.edits:
                    seen_in_session.add(e.file_path)
            for f in seen_in_session:
                counts[f] += 1

        now = datetime.now(timezone.utc).isoformat()
        with self.lock:
            self.graph = graph
            self.sessions = sessions
            self.file_edit_counts = counts
            self.last_refresh = now


# -----------------------------------------------------------------------
# HTTP handler
# -----------------------------------------------------------------------

class MonitorHandler(BaseHTTPRequestHandler):
    state: _State

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        # Global source filter: ?source=claude-code / cursor / codex
        self._source_filter = params.get("source", [None])[0]

        routes = {
            "/": self._serve_dashboard,
            "/favicon.png": self._serve_favicon,
            "/api/risk-summary": self._serve_risk_summary,
            "/api/codebase-health": self._serve_codebase_health,
            "/api/sessions": self._serve_sessions,
            "/api/timeline": self._serve_timeline,
            "/api/graph": self._serve_graph,
            "/api/status": self._serve_status,
            "/api/sources": self._serve_sources,
        }

        if path in routes:
            routes[path]()
        elif path.startswith("/api/session/"):
            self._serve_session_detail(path[len("/api/session/"):])
        elif path.startswith("/api/file/"):
            self._serve_file_detail(path[len("/api/file/"):])
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        self._source_filter = params.get("source", [None])[0]
        if path == "/api/refresh":
            self._handle_refresh()
        elif path == "/api/file-chat":
            self._serve_file_chat()
        else:
            self._send_json({"error": "not found"}, 404)

    # ------------------------------------------------------------------
    # Source filtering helper
    # ------------------------------------------------------------------

    def _filtered_data(self) -> tuple[list, Counter]:
        """Return (sessions, file_edit_counts) filtered by ?source= if set."""
        src = getattr(self, "_source_filter", None)
        sessions = self.state.sessions
        counts = self.state.file_edit_counts

        if src:
            sessions = [s for s in sessions if s.source == src]
            # Recompute edit counts from filtered sessions only
            counts = Counter()
            for sess in sessions:
                seen: set[str] = set()
                for r in sess.rounds:
                    for e in r.edits:
                        seen.add(e.file_path)
                for f in seen:
                    counts[f] += 1

        return sessions, counts

    # ------------------------------------------------------------------
    # Sources endpoint
    # ------------------------------------------------------------------

    def _serve_sources(self):
        """Return available sources with session counts."""
        with self.state.lock:
            source_counts: Counter = Counter()
            for sess in self.state.sessions:
                source_counts[sess.source] += 1
        self._send_json({
            "sources": [
                {"name": src, "session_count": cnt}
                for src, cnt in sorted(source_counts.items())
            ]
        })

    # ------------------------------------------------------------------
    # Risk Summary (the main endpoint)
    # ------------------------------------------------------------------

    def _serve_risk_summary(self):
        with self.state.lock:
            graph = self.state.graph
            sessions, counts = self._filtered_data()

            # Build review queue: files that were edited AND have meaningful blast radius
            edited_files: set[str] = set()
            for sess in sessions:
                edited_files.update(sess.files_edited)

            review_queue = []
            file_profiles = []
            for f in edited_files:
                ratio = graph.blast_ratio(f)
                tier = file_tier(ratio)
                ec = counts.get(f, 0)
                rs = risk_score(ratio, ec)
                br = graph.blast_radius(f)
                guidance = _file_guidance(f, graph, ec, self.state.working_dir)

                # Find last editor
                last_editor = None
                for sess in sessions:
                    if f in sess.files_edited:
                        last_editor = {
                            "session_id": sess.session_id,
                            "source": sess.source,
                            "timestamp": sess.timestamp,
                        }
                        break  # sessions are sorted most recent first

                review_queue.append({
                    "path": f,
                    "tier": tier,
                    "tier_label": _TIER_LABELS[tier],
                    "blast_radius": br,
                    "blast_ratio": round(ratio, 4),
                    "edit_count": ec,
                    "risk_score": round(rs, 4),
                    "impact_label": self._impact_label(f, br, ratio, graph),
                    "last_editor": last_editor,
                    "signals": guidance["signals"],
                    "recommended_actions": guidance["recommended_actions"],
                    "has_obvious_test": guidance["has_obvious_test"],
                })
                file_profiles.append({
                    "path": f,
                    "tier": tier,
                    "blast_radius": br,
                    "blast_ratio": round(ratio, 4),
                    "edit_count": ec,
                    "risk_score": round(rs, 4),
                    "impact_label": self._impact_label(f, br, ratio, graph),
                    "guidance": guidance,
                })

            review_queue.sort(key=lambda x: x["risk_score"], reverse=True)
            file_profiles.sort(key=lambda x: x["risk_score"], reverse=True)
            # Only show files worth reviewing: T1/T2 always, T3 only if
            # edited multiple times or high risk score
            review_queue = [
                x for x in review_queue
                if x["tier"] <= 2
                or (x["tier"] == 3 and (x["edit_count"] >= 2 or x["risk_score"] >= 0.15))
            ]

            sessions_with_edits = sum(1 for sess in sessions if sess.files_edited)
            quiet_session_count = len(sessions) - sessions_with_edits
            highest_tier_touched = (
                min(file_tier(graph.blast_ratio(f)) for f in edited_files)
                if edited_files else None
            )
            action_items, action_counts = _build_action_items(file_profiles, sessions)

            # Overall health -- based on actual tiers of edited files
            if not review_queue:
                if not edited_files:
                    health = "green"
                    verdict = "No AI edits detected yet. Start coding!"
                else:
                    health = "green"
                    verdict = "AI edits are landing in low-blast areas. The current vibe is contained."
            else:
                min_tier = min(x["tier"] for x in review_queue)
                if min_tier == 1:
                    health = "red"
                    t1_files = [x["path"] for x in review_queue if x["tier"] == 1]
                    verdict = f"Critical files modified: {', '.join(t1_files[:3])}. Review before deploying."
                elif min_tier == 2:
                    health = "yellow"
                    t2_count = sum(1 for x in review_queue if x["tier"] == 2)
                    verdict = f"{t2_count} shared component{'s' if t2_count != 1 else ''} modified. Worth a quick review."
                else:
                    # T3/T4 only -- check if any file was edited by many sessions (churn)
                    max_edits = max((x["edit_count"] for x in review_queue), default=0)
                    if max_edits >= 3:
                        health = "yellow"
                        churned = [x["path"] for x in review_queue if x["edit_count"] >= 3][:2]
                        verdict = f"Some files are being modified repeatedly ({', '.join(churned)}). Might be worth stabilizing."
                    else:
                        health = "green"
                        verdict = "All recent AI changes are low-risk. Ship it."

            # Hotspot quadrants
            br_threshold = 0.15  # files above this are "high blast radius"
            freq_threshold = 2   # files edited by >= this many sessions are "frequently changed"

            danger, stable, safe_iter, leaf = [], [], [], []
            for f in graph.files:
                ratio = graph.blast_ratio(f)
                ec = counts.get(f, 0)
                high_br = ratio >= br_threshold
                high_freq = ec >= freq_threshold
                entry = {
                    "path": f,
                    "blast_ratio": round(ratio, 4),
                    "edit_count": ec,
                    "tier": file_tier(ratio),
                }
                if high_br and high_freq:
                    danger.append(entry)
                elif high_br and not high_freq:
                    stable.append(entry)
                elif not high_br and high_freq:
                    safe_iter.append(entry)
                else:
                    leaf.append(entry)

            danger.sort(key=lambda x: x["blast_ratio"], reverse=True)
            safe_iter.sort(key=lambda x: x["edit_count"], reverse=True)

            # Recent activity (last 5 sessions, compact)
            recent = []
            for sess in sessions[:5]:
                edited = sess.files_edited
                recent.append({
                    "session_id": sess.session_id,
                    "source": sess.source,
                    "timestamp": sess.timestamp,
                    "num_files": len(edited),
                    "risk_level": _risk_level(edited, graph),
                    "narrative": _generate_narrative(edited, graph),
                })

        self._send_json({
            "health": health,
            "verdict": verdict,
            "num_sessions": len(sessions),
            "sessions_with_edits": sessions_with_edits,
            "quiet_session_count": quiet_session_count,
            "edited_file_count": len(edited_files),
            "highest_tier_touched": highest_tier_touched,
            "action_items": action_items,
            "action_counts": action_counts,
            "review_queue": review_queue[:15],
            "hotspots": {
                "danger": danger[:10],
                "stable": stable[:10],
                "safe_iteration": safe_iter[:10],
                "leaf_count": len(leaf),
            },
            "recent_activity": recent,
        })

    # ------------------------------------------------------------------
    # Codebase Health (tier-grouped file list)
    # ------------------------------------------------------------------

    def _serve_codebase_health(self):
        with self.state.lock:
            graph = self.state.graph
            _, counts = self._filtered_data()

            tier_groups: dict[int, list] = {1: [], 2: [], 3: [], 4: []}
            tier_edit_counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

            for f in sorted(graph.files):
                ratio = graph.blast_ratio(f)
                tier = file_tier(ratio)
                ec = counts.get(f, 0)
                guidance = _file_guidance(f, graph, ec, self.state.working_dir)
                tier_edit_counts[tier] += ec
                tier_groups[tier].append({
                    "path": f,
                    "blast_radius": graph.blast_radius(f),
                    "blast_ratio": round(ratio, 4),
                    "edit_count": ec,
                    "loc": graph.loc.get(f, 0),
                    "imported_by_direct": len(graph.imported_by.get(f, set())),
                    "risk_score": round(risk_score(ratio, ec), 4),
                    "signals": guidance["signals"],
                    "recommended_actions": guidance["recommended_actions"],
                    "has_obvious_test": guidance["has_obvious_test"],
                })

            # Sort each tier by risk score
            for tier in tier_groups:
                tier_groups[tier].sort(key=lambda x: x["risk_score"], reverse=True)

            total_edits = sum(tier_edit_counts.values())
            tiers = []
            for t in [1, 2, 3, 4]:
                files = tier_groups[t]
                tiers.append({
                    "tier": t,
                    "label": _TIER_LABELS[t],
                    "description": _TIER_DESCRIPTIONS[t],
                    "file_count": len(files),
                    "edited_file_count": sum(1 for f in files if f["edit_count"] > 0),
                    "edit_count": tier_edit_counts[t],
                    "edit_pct": round(tier_edit_counts[t] / total_edits * 100, 1) if total_edits else 0,
                    "max_risk_score": round(files[0]["risk_score"], 4) if files else 0.0,
                    "files": files,
                })

        self._send_json({"tiers": tiers, "total_files": len(graph.files)})

    # ------------------------------------------------------------------
    # Sessions (with narratives)
    # ------------------------------------------------------------------

    def _serve_sessions(self):
        with self.state.lock:
            graph = self.state.graph
            sessions, _ = self._filtered_data()
            result = []
            for sess in sessions:
                edited = sess.files_edited
                affected: set[str] = set()
                max_single = 0
                for fp in edited:
                    br = graph.blast_radius(fp)
                    max_single = max(max_single, br)
                    affected.update(graph.dependents(fp))

                tiers_touched = sorted(set(
                    file_tier(graph.blast_ratio(f)) for f in edited
                ))

                result.append({
                    "session_id": sess.session_id,
                    "source": sess.source,
                    "timestamp": sess.timestamp,
                    "num_rounds": len(sess.rounds),
                    "files_edited": edited,
                    "total_blast_radius": len(affected),
                    "max_single_file_blast": max_single,
                    "narrative": _generate_narrative(edited, graph),
                    "scope_label": _scope_label(edited, graph),
                    "risk_level": _risk_level(edited, graph),
                    "tiers_touched": tiers_touched,
                })
        self._send_json({"sessions": result})

    # ------------------------------------------------------------------
    # Session detail (with "Safe to Ship?")
    # ------------------------------------------------------------------

    def _serve_session_detail(self, session_id: str):
        with self.state.lock:
            graph = self.state.graph
            target = None
            for sess in self.state.sessions:
                if sess.session_id == session_id:
                    target = sess
                    break
            if not target:
                self._send_json({"error": "session not found"}, 404)
                return

            all_edited: list[str] = []
            rounds = []
            for rs in target.rounds:
                edits = []
                round_affected: set[str] = set()
                for e in rs.edits:
                    br = graph.blast_radius(e.file_path)
                    ratio = graph.blast_ratio(e.file_path)
                    deps = graph.dependents(e.file_path)
                    round_affected.update(deps)
                    tier = file_tier(ratio)
                    all_edited.append(e.file_path)
                    edits.append({
                        "file_path": e.file_path,
                        "tool_name": e.tool_name,
                        "action": e.action,
                        "blast_radius": br,
                        "blast_ratio": round(ratio, 4),
                        "tier": tier,
                        "tier_label": _TIER_LABELS[tier],
                        "impact_label": self._impact_label(e.file_path, br, ratio, graph),
                        "short_impact": self._short_impact(br, ratio),
                    })
                # Sort edits: highest tier (lowest number) first
                edits.sort(key=lambda x: (x["tier"], -x["blast_radius"]))
                rounds.append({
                    "round_num": rs.round_num,
                    "user_message_preview": rs.user_message[:300] if rs.user_message else "",
                    "file_edits": edits,
                    "round_blast_radius": len(round_affected),
                    "round_risk_level": _risk_level(
                        [e.file_path for e in rs.edits], graph
                    ),
                })

            # Deduplicate for review summary
            unique_edited = list(dict.fromkeys(all_edited))
            review = _review_summary(unique_edited, graph)

        self._send_json({
            "session_id": target.session_id,
            "source": target.source,
            "timestamp": target.timestamp,
            "narrative": _generate_narrative(unique_edited, graph),
            "risk_level": _risk_level(unique_edited, graph),
            "scope_label": _scope_label(unique_edited, graph),
            "rounds": rounds,
            "review_summary": review,
        })

    # ------------------------------------------------------------------
    # Other endpoints (preserved)
    # ------------------------------------------------------------------

    def _serve_dashboard(self):
        try:
            html = _DASHBOARD_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._send_text("Dashboard file not found", 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_favicon(self):
        try:
            data = _FAVICON_PATH.read_bytes()
        except FileNotFoundError:
            self._send_text("Favicon not found", 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_timeline(self):
        with self.state.lock:
            graph = self.state.graph
            sessions, _ = self._filtered_data()
            events = []
            for sess in sessions:
                for rs in sess.rounds:
                    for e in rs.edits:
                        ratio = graph.blast_ratio(e.file_path)
                        events.append({
                            "timestamp": e.timestamp,
                            "session_id": e.session_id,
                            "source": e.source,
                            "round_num": e.round_num,
                            "file_path": e.file_path,
                            "tool_name": e.tool_name,
                            "action": e.action,
                            "blast_radius": graph.blast_radius(e.file_path),
                            "blast_ratio": round(ratio, 4),
                            "tier": file_tier(ratio),
                        })
        events.sort(key=lambda x: x["timestamp"] or "")
        self._send_json({"events": events})

    def _serve_graph(self):
        with self.state.lock:
            data = self.state.graph.to_json()
            data["built_at"] = self.state.last_refresh
            _, counts = self._filtered_data()
            for node in data["nodes"]:
                ec = counts.get(node["id"], 0)
                node["edit_count"] = ec
                node["tier"] = file_tier(node["blast_ratio"])
                node["risk_score"] = round(risk_score(node["blast_ratio"], ec), 4)
        self._send_json(data)

    def _serve_file_detail(self, file_path: str):
        with self.state.lock:
            graph = self.state.graph
            sessions, counts = self._filtered_data()
            file_path = unquote(file_path)
            payload = _file_detail_payload(
                file_path,
                graph,
                sessions,
                counts,
                self.state.working_dir,
                self._impact_label(file_path, graph.blast_radius(file_path), graph.blast_ratio(file_path), graph),
            )
        self._send_json(payload)

    def _serve_file_chat(self):
        try:
            body = self._read_json_body()
        except ValueError as exc:
            self._send_json({"error": str(exc)}, 400)
            return

        file_path = unquote(str(body.get("file_path") or "")).strip()
        question = str(body.get("question") or "").strip()
        if not file_path:
            self._send_json({"error": "file_path is required"}, 400)
            return
        if not question:
            self._send_json({"error": "question is required"}, 400)
            return

        with self.state.lock:
            graph = self.state.graph
            sessions, counts = self._filtered_data()
            sessions = list(sessions)
            counts = Counter(counts)
            working_dir = self.state.working_dir
            model = self.state.default_model

        file_detail = _file_detail_payload(
            file_path,
            graph,
            sessions,
            counts,
            working_dir,
            self._impact_label(file_path, graph.blast_radius(file_path), graph.blast_ratio(file_path), graph),
        )
        context = _build_file_chat_context(file_detail)
        answer, used_llm, warning = _answer_file_chat(question, context, model=model)
        self._send_json({
            "file_path": file_path,
            "question": question,
            "answer": answer,
            "used_llm": used_llm,
            "warning": warning,
        })

    def _serve_status(self):
        with self.state.lock:
            source_counts: dict[str, int] = {}
            for sess in self.state.sessions:
                source_counts[sess.source] = source_counts.get(sess.source, 0) + 1
            sessions, _ = self._filtered_data()
            self._send_json({
                "status": "ok",
                "working_dir": self.state.working_dir,
                "last_refresh": self.state.last_refresh,
                "total_files": len(self.state.graph.files),
                "total_sessions": len(sessions),
                "all_sessions": len(self.state.sessions),
                "source_counts": source_counts,
                "active_filter": getattr(self, "_source_filter", None),
            })

    def _handle_refresh(self):
        self.state.refresh()
        with self.state.lock:
            self._send_json({
                "status": "ok",
                "total_files": len(self.state.graph.files),
                "total_sessions": len(self.state.sessions),
                "refreshed_at": self.state.last_refresh,
            })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _impact_label(self, filepath: str, br: int, ratio: float, graph: DependencyGraph) -> str:
        """Generate a human-readable impact description."""
        total = len(graph.files)
        if ratio >= 0.5:
            return f"Affects {br} files ({ratio*100:.0f}% of codebase) -- changes here ripple everywhere"
        if ratio >= 0.2:
            return f"Affects {br} files ({ratio*100:.0f}% of codebase) -- shared component"
        if br > 0:
            return f"Affects {br} file{'s' if br != 1 else ''} ({ratio*100:.0f}%)"
        return "Leaf file -- no other files depend on this"

    @staticmethod
    def _short_impact(br: int, ratio: float) -> str:
        """Short impact label for inline display in edit rows."""
        if br == 0:
            return "Leaf"
        return f"{br} files ({ratio*100:.0f}%)"

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("request body must be valid JSON") from exc

    def _send_text(self, text: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(text.encode("utf-8"))


def _auto_refresh_loop(state: _State, interval: int):
    while True:
        time.sleep(interval)
        try:
            state.refresh()
        except Exception:
            pass


def run_monitor(working_dir: str, port: int, cfg=None) -> None:
    """Start the blast radius monitoring web server."""
    exclude_dirs = []
    refresh_interval = 30
    default_model = None
    if cfg and hasattr(cfg, "monitor_exclude_dirs"):
        exclude_dirs = cfg.monitor_exclude_dirs
    if cfg and hasattr(cfg, "monitor_refresh_interval"):
        refresh_interval = cfg.monitor_refresh_interval
    if cfg and hasattr(cfg, "default_model"):
        default_model = cfg.default_model

    state = _State(working_dir, exclude_dirs=exclude_dirs, default_model=default_model)
    print(f"[retro] Building dependency graph for: {working_dir}")
    state.refresh()
    print(f"[retro] Found {len(state.graph.files)} Python files, "
          f"{len(state.sessions)} agent sessions")

    t = threading.Thread(target=_auto_refresh_loop, args=(state, refresh_interval), daemon=True)
    t.start()

    handler = type("Handler", (MonitorHandler,), {"state": state})
    server = HTTPServer(("0.0.0.0", port), handler)
    print(f"[retro] Blast radius monitor running at http://localhost:{port}")
    print(f"[retro] Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[retro] Monitor stopped")
        server.shutdown()
