"""
Terminal renderer for analyzeme — Spotify Wrapped style cards.

Uses box-drawing characters and ANSI colors for a fun, visual output.
"""
from __future__ import annotations

import sys
from typing import Any


# ── ANSI color helpers ────────────────────────────────────────────────

def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

_COLOR = _supports_color()

def _c(code: str, text: str) -> str:
    if not _COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def bold(t: str) -> str: return _c("1", t)
def dim(t: str) -> str: return _c("2", t)
def cyan(t: str) -> str: return _c("36", t)
def green(t: str) -> str: return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def magenta(t: str) -> str: return _c("35", t)
def red(t: str) -> str: return _c("31", t)
def blue(t: str) -> str: return _c("34", t)
def white_bg(t: str) -> str: return _c("47;30", t)


# ── Card drawing ──────────────────────────────────────────────────────

def _word_wrap(text: str, max_width: int) -> list[str]:
    """Word-wrap text to max_width, respecting ANSI codes."""
    words = text.split()
    if not words:
        return [text]
    result_lines = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        if len(_strip_ansi(test)) > max_width:
            result_lines.append(current)
            current = "  " + word  # indent continuation
        else:
            current = test
    result_lines.append(current)
    return result_lines


def _card(title: str, lines: list[str], width: int = 56) -> str:
    """Draw a card with a title and content lines."""
    top    = f"  ╔{'═' * (width - 2)}╗"
    bottom = f"  ╚{'═' * (width - 2)}╝"
    max_text_width = width - 6  # 2 for "  " prefix + 2 for "  " suffix + 2 for ║

    # Title bar
    title_padded = f"  {title}  "
    pad_len = width - 2 - len(title_padded)
    if pad_len < 0:
        title_padded = title_padded[:width - 2]
        pad_len = 0
    title_line = f"  ║{title_padded}{' ' * pad_len}║"

    # Content lines (with word wrap for long lines)
    content = []
    for line in lines:
        visible_len = len(_strip_ansi(line))
        if visible_len > max_text_width:
            wrapped = _word_wrap(line, max_text_width)
            for wl in wrapped:
                vis = len(_strip_ansi(wl))
                pad = max_text_width - vis
                content.append(f"  ║  {wl}{' ' * max(0, pad)}  ║")
        else:
            pad = max_text_width - visible_len
            content.append(f"  ║  {line}{' ' * max(0, pad)}  ║")

    parts = [top, title_line, f"  ║{'─' * (width - 2)}║"]
    if content:
        parts.extend(content)
    parts.append(bottom)
    return "\n".join(parts)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes for length calculation."""
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _bar(value: float, max_value: float, width: int = 20, char: str = "█") -> str:
    """Render a simple bar chart segment."""
    if max_value <= 0:
        return ""
    filled = int(value / max_value * width)
    empty = width - filled
    return green(char * filled) + dim("░" * empty)


def _pct_bar(pct: float, width: int = 20) -> str:
    """Render a percentage bar."""
    return _bar(pct, 100, width)


# ── Main render function ──────────────────────────────────────────────

def render_terminal(stats: dict[str, Any]) -> str:
    """Render the full analyzeme report as terminal cards."""
    cards: list[str] = []

    # ── Title card ────────────────────────────────────────────────
    persona = stats.get("persona", {})
    emoji = persona.get("emoji", "🎯")
    cards.append(_card(
        f"{emoji}  YOUR AI CODING WRAPPED  {emoji}",
        [
            bold(f"Persona: {persona.get('name', 'Unknown')}"),
            dim(persona.get("description", "")),
            "",
            f"Sessions: {bold(str(stats.get('total_sessions', 0)))}  "
            f"Rounds: {bold(str(stats.get('total_rounds', 0)))}  "
            f"Days: {bold(str(stats.get('total_active_days', 0)))}",
        ],
    ))

    # ── Tool usage card ───────────────────────────────────────────
    tool_usage = stats.get("tool_usage", {})
    top_tools = list(tool_usage.items())[:6]
    max_ct = max(tool_usage.values()) if tool_usage else 1
    tool_lines = [bold(f"Total tool calls: {stats.get('total_tool_calls', 0):,}"), ""]
    for name, count in top_tools:
        bar = _bar(count, max_ct, 15)
        tool_lines.append(f"{name:12s} {bar} {count:,}")

    cards.append(_card("🔧  YOUR TOOLKIT", tool_lines))

    # ── Languages card ────────────────────────────────────────────
    languages = stats.get("languages", {})
    if languages:
        max_lang = max(languages.values())
        lang_lines = [bold(f"Files touched: {stats.get('files_touched', 0):,}"), ""]
        for lang, count in list(languages.items())[:5]:
            bar = _bar(count, max_lang, 15)
            lang_lines.append(f"{lang:12s} {bar} {count:,}")
        cards.append(_card("💻  LANGUAGES YOU VIBED WITH", lang_lines))

    # ── Time card ─────────────────────────────────────────────────
    period = stats.get("coding_period", "Unknown")
    period_emojis = {
        "Night Owl": "🦉", "Early Bird": "🐦",
        "Afternoon Coder": "☀️", "Evening Hacker": "🌙",
    }
    period_emoji = period_emojis.get(period, "⏰")

    time_lines = [
        bold(f"You are: {period_emoji} {period}"),
        "",
    ]
    hour = stats.get("most_active_hour")
    if hour is not None:
        time_lines.append(f"Peak coding hour: {bold(f'{hour:02d}:00')}")
    busiest = stats.get("busiest_day")
    if busiest:
        time_lines.append(f"Busiest day: {bold(busiest)}")
    streak = stats.get("longest_streak", 0)
    if streak > 0:
        unit = "day" if streak == 1 else "days"
        time_lines.append(f"Longest streak: {bold(f'{streak} {unit}')} 🔥")

    cards.append(_card("⏰  YOUR SCHEDULE", time_lines))

    # ── Editing style card ────────────────────────────────────────
    style = stats.get("editing_style", "Unknown")
    careful_pct = stats.get("careful_edit_pct", 0)
    style_emoji = "🛡️" if style == "Careful" else "🤠"

    style_lines = [
        bold(f"Style: {style_emoji} {style}"),
        "",
        f"Read-before-edit: {_pct_bar(careful_pct)} {careful_pct:.0f}%",
        "",
    ]
    if style == "Careful":
        style_lines.append(dim("You read files before editing them."))
        style_lines.append(dim("Your code reviews itself."))
    else:
        style_lines.append(dim("You edit first, read later."))
        style_lines.append(dim("Fortune favors the bold."))

    cards.append(_card("✏️  YOUR EDITING STYLE", style_lines))

    # ── Patience card ─────────────────────────────────────────────
    patience = stats.get("patience_score", 100)
    rejections = stats.get("total_rejections", 0)
    total = stats.get("total_rounds", 0)

    patience_lines = [
        f"Patience score: {_pct_bar(patience)} {bold(f'{patience:.0f}%')}",
        "",
        f"Times you said No: {bold(str(rejections))} / {total} rounds",
    ]
    if patience >= 90:
        patience_lines.append(dim("You're extremely chill. Your AI appreciates it."))
    elif patience >= 70:
        patience_lines.append(dim("You know when to push back. Balanced."))
    elif patience >= 50:
        patience_lines.append(dim("You have standards. The AI is learning."))
    else:
        patience_lines.append(dim("You're tough but fair. Only the best work survives."))

    cards.append(_card("🧘  YOUR PATIENCE", patience_lines))

    # ── Delegation card (if applicable) ───────────────────────────
    delegation_pct = stats.get("delegation_pct", 0)
    if delegation_pct > 0:
        deleg_lines = [
            f"Agent delegation: {_pct_bar(delegation_pct)} {delegation_pct:.0f}%",
            "",
            f"Rounds with sub-agents: {stats.get('delegation_rounds', 0)}",
        ]
        if delegation_pct > 20:
            deleg_lines.append(dim("You're a manager at heart. Delegate!"))
        else:
            deleg_lines.append(dim("You prefer to handle things yourself."))
        cards.append(_card("🤖  DELEGATION SCORE", deleg_lines))

    # ── AI compatibility card ────────────────────────────────────
    compat = stats.get("compatibility_score", 0)
    compat_lines = [
        f"Compatibility: {_pct_bar(compat)} {bold(f'{compat:.0f}%')}",
        "",
    ]
    if compat >= 90:
        compat_lines.append(dim("You and your AI are in perfect sync."))
        compat_lines.append(dim("This is a power duo."))
    elif compat >= 70:
        compat_lines.append(dim("Strong partnership. You complement each other well."))
    elif compat >= 50:
        compat_lines.append(dim("Good foundation. Room to grow together."))
    else:
        compat_lines.append(dim("Still getting to know each other. Keep at it!"))

    avg_len = stats.get("avg_session_length", 0)
    longest = stats.get("longest_session", 0)
    if avg_len > 0:
        compat_lines.append("")
        compat_lines.append(f"Avg session: {bold(f'{avg_len:.0f}')} messages")
        compat_lines.append(f"Longest marathon: {bold(str(longest))} messages")
    cards.append(_card("💞  AI COMPATIBILITY", compat_lines))

    # ── Fun facts card ────────────────────────────────────────────
    fun_facts = stats.get("fun_facts", [])
    if fun_facts:
        fact_lines = []
        max_fact_width = 52  # usable width inside card
        for i, fact in enumerate(fun_facts[:8]):
            # Word-wrap long facts
            words = fact.split()
            line = f"{magenta('•')} "
            for word in words:
                if len(_strip_ansi(line)) + len(word) + 1 > max_fact_width:
                    fact_lines.append(line)
                    line = f"  {word}"
                else:
                    line += f" {word}" if not line.endswith(" ") else word
            fact_lines.append(line)
            if i < len(fun_facts) - 1:
                fact_lines.append("")
        cards.append(_card("✨  FUN FACTS", fact_lines, width=60))

    # ── Assemble ──────────────────────────────────────────────────
    header = bold(cyan("""
    ╦═╗╔═╗╔╦╗╦═╗╔═╗  ╔═╗╔═╗╔╦╗╔═╗  ╦ ╦╦═╗╔═╗╔═╗╔═╗╔═╗╔╦╗
    ╠╦╝║╣  ║ ╠╦╝║ ║  ║  ║ ║ ║║║╣   ║║║╠╦╝╠═╣╠═╝╠═╝║╣  ║║
    ╩╚═╚═╝ ╩ ╩╚═╚═╝  ╚═╝╚═╝═╩╝╚═╝  ╚╩╝╩╚═╩ ╩╩  ╩  ╚═╝═╩╝
    """))

    footer = dim(f"\n  Generated by RetroCode • retro --analyzeme\n")

    return header + "\n\n".join(cards) + "\n" + footer


def render_html(stats: dict[str, Any]) -> str:
    """Render the analyzeme report as a shareable HTML file."""
    persona = stats.get("persona", {})
    tool_usage = stats.get("tool_usage", {})
    languages = stats.get("languages", {})
    fun_facts = stats.get("fun_facts", [])

    tool_rows = "\n".join(
        f'<div class="bar-row">'
        f'<span class="bar-label">{name}</span>'
        f'<div class="bar" style="width: {count / max(tool_usage.values()) * 100 if tool_usage else 0:.0f}%"></div>'
        f'<span class="bar-value">{count:,}</span>'
        f'</div>'
        for name, count in list(tool_usage.items())[:8]
    )

    lang_rows = "\n".join(
        f'<div class="bar-row">'
        f'<span class="bar-label">{lang}</span>'
        f'<div class="bar lang-bar" style="width: {count / max(languages.values()) * 100 if languages else 0:.0f}%"></div>'
        f'<span class="bar-value">{count:,}</span>'
        f'</div>'
        for lang, count in list(languages.items())[:6]
    )

    fact_items = "\n".join(f"<li>{fact}</li>" for fact in fun_facts[:10])

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RetroCode Wrapped</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    color: #e0e0e0;
    min-height: 100vh;
    padding: 40px 20px;
  }}
  .container {{ max-width: 640px; margin: 0 auto; }}
  h1 {{
    text-align: center;
    font-size: 2rem;
    margin-bottom: 8px;
    background: linear-gradient(90deg, #00d4ff, #7b2ff7, #ff006e);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .subtitle {{ text-align: center; color: #888; margin-bottom: 40px; }}
  .card {{
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 24px;
    backdrop-filter: blur(10px);
  }}
  .card h2 {{
    font-size: 1.1rem;
    margin-bottom: 16px;
    color: #00d4ff;
  }}
  .persona-emoji {{ font-size: 3rem; text-align: center; }}
  .persona-name {{ text-align: center; font-size: 1.4rem; font-weight: bold; margin: 8px 0; }}
  .persona-desc {{ text-align: center; color: #aaa; font-style: italic; }}
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    text-align: center;
    margin-top: 16px;
  }}
  .stat-num {{ font-size: 1.8rem; font-weight: bold; color: #7b2ff7; }}
  .stat-label {{ font-size: 0.8rem; color: #888; }}
  .bar-row {{ display: flex; align-items: center; margin: 6px 0; }}
  .bar-label {{ width: 100px; font-size: 0.85rem; }}
  .bar {{
    height: 20px;
    background: linear-gradient(90deg, #00d4ff, #7b2ff7);
    border-radius: 4px;
    min-width: 4px;
    flex-shrink: 0;
  }}
  .lang-bar {{ background: linear-gradient(90deg, #ff006e, #7b2ff7); }}
  .bar-value {{ margin-left: 8px; font-size: 0.85rem; color: #aaa; }}
  .style-meter {{
    height: 24px;
    background: rgba(255,255,255,0.1);
    border-radius: 12px;
    overflow: hidden;
    margin: 12px 0;
  }}
  .style-fill {{
    height: 100%;
    background: linear-gradient(90deg, #00d4ff, #00ff88);
    border-radius: 12px;
    transition: width 0.5s;
  }}
  .facts li {{
    margin: 10px 0;
    padding-left: 12px;
    border-left: 3px solid #7b2ff7;
    color: #ccc;
    font-size: 0.9rem;
  }}
  .footer {{
    text-align: center;
    color: #555;
    margin-top: 40px;
    font-size: 0.8rem;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>RetroCode Wrapped</h1>
  <p class="subtitle">Your AI Coding Year in Review</p>

  <div class="card">
    <div class="persona-emoji">{persona.get('emoji', '🎯')}</div>
    <div class="persona-name">{persona.get('name', 'Unknown')}</div>
    <div class="persona-desc">{persona.get('description', '')}</div>
    <div class="stats-grid">
      <div><div class="stat-num">{stats.get('total_sessions', 0)}</div><div class="stat-label">Sessions</div></div>
      <div><div class="stat-num">{stats.get('total_rounds', 0)}</div><div class="stat-label">Rounds</div></div>
      <div><div class="stat-num">{stats.get('total_active_days', 0)}</div><div class="stat-label">Active Days</div></div>
    </div>
  </div>

  <div class="card">
    <h2>🔧 Your Toolkit</h2>
    <p style="margin-bottom:12px"><strong>{stats.get('total_tool_calls', 0):,}</strong> total tool calls</p>
    {tool_rows}
  </div>

  <div class="card">
    <h2>💻 Languages You Vibed With</h2>
    <p style="margin-bottom:12px"><strong>{stats.get('files_touched', 0):,}</strong> files touched</p>
    {lang_rows}
  </div>

  <div class="card">
    <h2>✏️ Your Editing Style: {stats.get('editing_style', 'Unknown')}</h2>
    <p>Read-before-edit score:</p>
    <div class="style-meter">
      <div class="style-fill" style="width: {stats.get('careful_edit_pct', 0):.0f}%"></div>
    </div>
    <p style="color:#aaa">{stats.get('careful_edit_pct', 0):.0f}% careful • {100 - stats.get('careful_edit_pct', 0):.0f}% cowboy</p>
  </div>

  <div class="card">
    <h2>🧘 Patience Score</h2>
    <div class="style-meter">
      <div class="style-fill" style="width: {stats.get('patience_score', 100):.0f}%; background: linear-gradient(90deg, #ff006e, #00ff88);"></div>
    </div>
    <p><strong>{stats.get('patience_score', 100):.0f}%</strong> — said No <strong>{stats.get('total_rejections', 0)}</strong> times out of {stats.get('total_rounds', 0)} rounds</p>
  </div>

  <div class="card">
    <h2>⏰ Schedule: {stats.get('coding_period', 'Unknown')}</h2>
    <p>Peak hour: <strong>{f"{stats['most_active_hour']:02d}:00" if stats.get('most_active_hour') is not None else "??"}</strong> • Busiest day: <strong>{stats.get('busiest_day', '??')}</strong></p>
    <p>Longest streak: <strong>{stats.get('longest_streak', 0)} {"day" if stats.get('longest_streak', 0) == 1 else "days"}</strong> 🔥</p>
  </div>

  <div class="card">
    <h2>💞 AI Compatibility Score</h2>
    <div class="style-meter">
      <div class="style-fill" style="width: {stats.get('compatibility_score', 0):.0f}%; background: linear-gradient(90deg, #7b2ff7, #00d4ff);"></div>
    </div>
    <p><strong>{stats.get('compatibility_score', 0):.0f}%</strong> — based on acceptance rate, tool diversity, and engagement</p>
    <p style="color:#888; margin-top:8px">Avg session: <strong>{stats.get('avg_session_length', 0):.0f}</strong> messages • Longest: <strong>{stats.get('longest_session', 0)}</strong> messages</p>
  </div>

  <div class="card">
    <h2>✨ Fun Facts</h2>
    <ul class="facts">
      {fact_items}
    </ul>
  </div>

  <div class="footer">Generated by RetroCode • retro --analyzeme</div>
</div>
</body>
</html>
"""
