"""
Compute fun statistics from AI coding traces — Spotify Wrapped style.

All stats are computed from parsed trace data (sessions, rounds, messages).
No LLM calls needed — pure data analysis.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def compute_stats(
    sessions: list[dict],
    rounds: list[dict],
) -> dict[str, Any]:
    """Compute all analyzeme stats from parsed sessions and rounds.

    Args:
        sessions: List of dicts with keys: session_id, timestamp, messages
        rounds: List of round dicts with keys: session_id, round_id, msgs,
                reward, user_msg, next_user_msg, n_msgs

    Returns:
        Dict of all computed statistics.
    """
    stats: dict[str, Any] = {}

    # ── Basic counts ──────────────────────────────────────────────────
    stats["total_sessions"] = len(sessions)
    stats["total_rounds"] = len(rounds)
    stats["total_messages"] = sum(len(s.get("messages", [])) for s in sessions)
    stats["total_rejections"] = sum(1 for r in rounds if r.get("reward") == 0.0)
    stats["total_accepted"] = stats["total_rounds"] - stats["total_rejections"]

    # ── Tool usage ────────────────────────────────────────────────────
    tool_counter: Counter = Counter()
    tool_per_round: list[int] = []
    for r in rounds:
        round_tools = 0
        for m in r.get("msgs", []):
            if m.get("role") == "assistant":
                for tn in m.get("tool_names", []):
                    tool_counter[tn] += 1
                    round_tools += 1
        tool_per_round.append(round_tools)

    stats["tool_usage"] = dict(tool_counter.most_common())
    stats["total_tool_calls"] = sum(tool_counter.values())
    stats["top_tool"] = tool_counter.most_common(1)[0] if tool_counter else ("None", 0)
    stats["rarest_tool"] = tool_counter.most_common()[-1] if tool_counter else ("None", 0)
    stats["avg_tools_per_round"] = (
        sum(tool_per_round) / len(tool_per_round) if tool_per_round else 0
    )
    stats["max_tools_in_round"] = max(tool_per_round) if tool_per_round else 0

    # ── File / language analysis ──────────────────────────────────────
    ext_counter: Counter = Counter()
    files_touched: set[str] = set()
    for r in rounds:
        for m in r.get("msgs", []):
            if m.get("role") == "assistant":
                for tn, ta in zip(m.get("tool_names", []), m.get("tool_args", [])):
                    if not isinstance(ta, dict):
                        continue
                    fp = ta.get("file_path", "")
                    if fp:
                        files_touched.add(fp)
                        ext = Path(fp).suffix.lower()
                        if ext:
                            ext_counter[ext] += 1

    _EXT_LANG = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".tsx": "React/TSX", ".jsx": "React/JSX", ".rs": "Rust",
        ".go": "Go", ".java": "Java", ".rb": "Ruby", ".cpp": "C++",
        ".c": "C", ".cs": "C#", ".swift": "Swift", ".kt": "Kotlin",
        ".php": "PHP", ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
        ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML",
        ".md": "Markdown", ".sh": "Shell", ".sql": "SQL", ".vue": "Vue",
        ".svelte": "Svelte", ".dart": "Dart", ".lua": "Lua",
    }
    lang_counter: Counter = Counter()
    for ext, count in ext_counter.items():
        lang = _EXT_LANG.get(ext, ext)
        lang_counter[lang] += count

    stats["languages"] = dict(lang_counter.most_common(10))
    stats["top_language"] = lang_counter.most_common(1)[0] if lang_counter else ("None", 0)
    stats["files_touched"] = len(files_touched)

    # ── Time analysis ─────────────────────────────────────────────────
    timestamps: list[datetime] = []
    for s in sessions:
        ts = s.get("timestamp")
        if isinstance(ts, str):
            try:
                timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                pass
        elif isinstance(ts, datetime):
            timestamps.append(ts)

    if timestamps:
        hours = [t.hour for t in timestamps]
        hour_counter = Counter(hours)
        stats["most_active_hour"] = hour_counter.most_common(1)[0][0]
        stats["hour_distribution"] = dict(sorted(hour_counter.items()))

        # Night owl vs early bird
        night_sessions = sum(1 for h in hours if h >= 22 or h < 6)
        morning_sessions = sum(1 for h in hours if 6 <= h < 12)
        afternoon_sessions = sum(1 for h in hours if 12 <= h < 18)
        evening_sessions = sum(1 for h in hours if 18 <= h < 22)

        periods = {
            "Night Owl": night_sessions,
            "Early Bird": morning_sessions,
            "Afternoon Coder": afternoon_sessions,
            "Evening Hacker": evening_sessions,
        }
        stats["coding_period"] = max(periods, key=periods.get)
        stats["period_distribution"] = periods

        # Day of week
        dow_counter = Counter(t.strftime("%A") for t in timestamps)
        stats["busiest_day"] = dow_counter.most_common(1)[0][0]
        stats["day_distribution"] = dict(dow_counter.most_common())

        # Streak: consecutive days with sessions
        dates = sorted(set(t.date() for t in timestamps))
        if dates:
            max_streak = 1
            current_streak = 1
            for i in range(1, len(dates)):
                if dates[i] - dates[i - 1] == timedelta(days=1):
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
                    current_streak = 1
            stats["longest_streak"] = max_streak
            stats["total_active_days"] = len(dates)
            stats["first_session"] = dates[0].isoformat()
            stats["last_session"] = dates[-1].isoformat()
    else:
        stats["most_active_hour"] = None
        stats["coding_period"] = "Unknown"
        stats["longest_streak"] = 0
        stats["total_active_days"] = 0

    # ── Editing style ─────────────────────────────────────────────────
    reads_before_edit = 0
    edits_without_read = 0
    for r in rounds:
        read_files: set[str] = set()
        for m in r.get("msgs", []):
            if m.get("role") == "assistant":
                for tn, ta in zip(m.get("tool_names", []), m.get("tool_args", [])):
                    if not isinstance(ta, dict):
                        continue
                    if tn == "Read":
                        read_files.add(ta.get("file_path", ""))
                    elif tn in ("Edit", "Write"):
                        fp = ta.get("file_path", "")
                        if fp and fp in read_files:
                            reads_before_edit += 1
                        elif fp:
                            edits_without_read += 1

    total_edit_events = reads_before_edit + edits_without_read
    if total_edit_events > 0:
        careful_pct = reads_before_edit / total_edit_events * 100
    else:
        careful_pct = 100
    stats["careful_edit_pct"] = careful_pct
    stats["editing_style"] = "Careful" if careful_pct >= 60 else "Cowboy"

    # ── Patience score ────────────────────────────────────────────────
    if stats["total_rounds"] > 0:
        patience = (1 - stats["total_rejections"] / stats["total_rounds"]) * 100
    else:
        patience = 100
    stats["patience_score"] = patience

    # ── Agent delegation ──────────────────────────────────────────────
    delegation_rounds = sum(
        1 for r in rounds
        if any(
            "Agent" in m.get("tool_names", [])
            for m in r.get("msgs", [])
            if m.get("role") == "assistant"
        )
    )
    stats["delegation_rounds"] = delegation_rounds
    stats["delegation_pct"] = (
        delegation_rounds / stats["total_rounds"] * 100
        if stats["total_rounds"] else 0
    )

    # ── Conversation length distribution ──────────────────────────────
    session_lengths = [len(s.get("messages", [])) for s in sessions]
    if session_lengths:
        stats["avg_session_length"] = sum(session_lengths) / len(session_lengths)
        stats["longest_session"] = max(session_lengths)
        stats["shortest_session"] = min(session_lengths)
    else:
        stats["avg_session_length"] = 0
        stats["longest_session"] = 0
        stats["shortest_session"] = 0

    # ── AI compatibility score ────────────────────────────────────────
    # How well you and your AI work together (acceptance + diversity + engagement)
    acceptance_rate = stats["patience_score"] / 100
    tool_diversity = min(len(tool_counter) / 8, 1.0)
    avg_len_factor = min(stats["avg_session_length"] / 50, 1.0)
    stats["compatibility_score"] = (
        acceptance_rate * 0.5 + tool_diversity * 0.25 + avg_len_factor * 0.25
    ) * 100

    # ── Persona assignment ────────────────────────────────────────────
    stats["persona"] = _assign_persona(stats)

    # ── Fun facts ─────────────────────────────────────────────────────
    stats["fun_facts"] = _generate_fun_facts(stats, rounds)

    return stats


def _assign_persona(stats: dict) -> dict[str, str]:
    """Assign a coding persona based on patterns."""
    persona_name = "The Balanced Coder"
    persona_desc = "A well-rounded developer who uses AI effectively."
    persona_emoji = "🎯"

    tool_usage = stats.get("tool_usage", {})
    total_tools = stats.get("total_tool_calls", 0)
    patience = stats.get("patience_score", 100)
    style = stats.get("editing_style", "Careful")
    delegation = stats.get("delegation_pct", 0)

    # Determine dominant pattern
    if total_tools == 0:
        persona_name = "The Conversationalist"
        persona_desc = "You prefer talking through problems over tool calls. Words are your power."
        persona_emoji = "💬"
    elif delegation > 20:
        persona_name = "The Architect"
        persona_desc = "You delegate to sub-agents like a tech lead. You design, they execute."
        persona_emoji = "🏗️"
    elif style == "Cowboy":
        if patience < 70:
            persona_name = "The Impatient Trailblazer"
            persona_desc = "Edit first, ask questions later. You move fast and break things."
            persona_emoji = "🤠"
        else:
            persona_name = "The Speed Demon"
            persona_desc = "You trust your AI and jump straight to edits. Efficiency is your game."
            persona_emoji = "⚡"
    elif patience < 60:
        persona_name = "The Perfectionist"
        persona_desc = "You have high standards and aren't afraid to say 'no'. Quality over speed."
        persona_emoji = "🎯"
    elif stats.get("avg_tools_per_round", 0) > 8:
        persona_name = "The Power User"
        persona_desc = "You push your AI to the limit with complex, tool-heavy sessions."
        persona_emoji = "🚀"
    elif tool_usage.get("Bash", 0) > tool_usage.get("Edit", 0):
        persona_name = "The Terminal Wizard"
        persona_desc = "Bash is your native tongue. You live in the command line."
        persona_emoji = "🧙"
    elif tool_usage.get("Grep", 0) + tool_usage.get("Glob", 0) > total_tools * 0.3:
        persona_name = "The Code Detective"
        persona_desc = "You search and investigate before acting. No line of code escapes your eye."
        persona_emoji = "🔍"
    elif style == "Careful":
        persona_name = "The Methodical Craftsman"
        persona_desc = "Read, understand, then edit. You believe in doing things right the first time."
        persona_emoji = "🛠️"

    return {"name": persona_name, "description": persona_desc, "emoji": persona_emoji}


def _generate_fun_facts(stats: dict, rounds: list[dict]) -> list[str]:
    """Generate quirky fun facts from the stats."""
    facts: list[str] = []

    total = stats.get("total_tool_calls", 0)
    if total > 100:
        facts.append(f"Your AI made {total:,} tool calls. That's like clicking a mouse {total:,} times... but smarter.")
    elif total > 0:
        facts.append(f"Your AI used {total:,} tool calls to help you. Every click counts!")

    top = stats.get("top_tool", ("None", 0))
    if top[0] != "None":
        pct = top[1] / total * 100 if total else 0
        facts.append(f"Your go-to tool was {top[0]} ({pct:.0f}% of all calls). You two are inseparable.")

    rare = stats.get("rarest_tool", ("None", 0))
    if rare[0] != "None" and rare[0] != top[0]:
        facts.append(f"Your rarest tool was {rare[0]} (used only {rare[1]} time{'s' if rare[1] != 1 else ''}). A true hidden gem.")

    if stats.get("longest_streak", 0) > 1:
        facts.append(f"Longest coding streak: {stats['longest_streak']} days in a row. Dedication level: maximum.")

    rejections = stats.get("total_rejections", 0)
    if rejections > 0:
        facts.append(f"You said 'No' to your AI {rejections} time{'s' if rejections != 1 else ''}. Sometimes the human knows best.")
    else:
        facts.append("You never said 'No' to your AI. Either it's perfect, or you're very forgiving.")

    files = stats.get("files_touched", 0)
    if files > 0:
        facts.append(f"Together you touched {files:,} different files. That's a lot of ground covered.")

    lang = stats.get("top_language", ("None", 0))
    if lang[0] != "None":
        facts.append(f"Your top language was {lang[0]}. It's not just a language, it's a lifestyle.")

    max_tools = stats.get("max_tools_in_round", 0)
    if max_tools > 10:
        facts.append(f"Your biggest round had {max_tools} tool calls. Your AI was in beast mode.")

    period = stats.get("coding_period", "")
    if period == "Night Owl":
        facts.append("You code at night. The bugs can't see you coming in the dark.")
    elif period == "Early Bird":
        facts.append("You code in the morning. Fresh brain, fresh code.")

    days = stats.get("total_active_days", 0)
    if days > 0:
        facts.append(f"You coded with AI on {days} different days. That's commitment.")

    # Avg tools per round
    avg_tools = stats.get("avg_tools_per_round", 0)
    if avg_tools > 5:
        facts.append(f"Average {avg_tools:.1f} tool calls per round. You keep your AI busy.")
    elif avg_tools > 0:
        facts.append(f"Average {avg_tools:.1f} tool calls per round. Lean and efficient.")

    # Compatibility
    compat = stats.get("compatibility_score", 0)
    if compat >= 90:
        facts.append(f"AI compatibility: {compat:.0f}%. You two should get matching keyboards.")
    elif compat >= 70:
        facts.append(f"AI compatibility: {compat:.0f}%. A strong partnership.")

    # Session marathon
    longest = stats.get("longest_session", 0)
    if longest > 200:
        facts.append(f"Your longest session had {longest} messages. That's a coding marathon!")
    elif longest > 50:
        facts.append(f"Your longest session: {longest} messages. Deep work mode activated.")

    return facts
