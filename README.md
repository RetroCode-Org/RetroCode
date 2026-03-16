![RetroCode](assets/imgs/retro_wide.png)

<p align="center">
  <a href="https://join.slack.com/t/retrocode-workspace/shared_invite/zt-3s4qb61lg-WH3V_3K0i4fe97tJed8Icw">
    <img alt="Join us on Slack" src="https://img.shields.io/badge/Slack-4A154B?style=for-the-badge&logo=slack&logoColor=white">
  </a>
  <a href="https://discord.gg/CFEcwyWC">
    <img alt="Join us on Discord" src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white">
  </a>
  <a href="https://forms.gle/CyBKhEyGSvEUmXJT6">
    <img alt="Chat with us!" src="https://img.shields.io/badge/Chat%20with%20us!-34A853?style=for-the-badge">
  </a>
</p>

A plugin for AI coding agents (Claude Code, Cursor, Codex) that adds capabilities current providers don't offer. RetroCode reads your agent session traces and turns them into actionable improvements — automatically.

**What you get:**
- **Playbook Generation** — Automatically builds and maintains project-specific rules from your past sessions, written directly into your agent's rule files
- **Hypothesis Generation** — Statistically identifies which agent behaviors predict user rejection, with community sharing
- **AnalyzeMe** — Your AI Coding Wrapped: Spotify-style fun stats about your vibe coding patterns, personas, and habits
- **AI Code Blast Radius** — Automatically estimates the blast radius of a code edit by identifying how many execution paths and subsystems depend on the modified code

Works with Claude Code, Cursor, and Codex. Supports OpenAI, Anthropic, Gemini, and CommonStack as LLM providers.

> **Full reference:** [docs/reference.md](docs/reference.md)

---

## Playbook Generation

Automatically builds and maintains a project-specific playbook of coding patterns, workflow strategies, and common mistakes learned from your past sessions. Focuses on real misunderstandings between you and your AI agent — every rule stems from actual friction. The playbook is written directly into your agent's rule files (`CLAUDE.md`, `.cursor/rules/retro.mdc`, `AGENTS.md`) so every future session benefits.

**How it works:**
1. Reads session traces from Claude Code, Cursor, and/or Codex
2. A **Reflector** analyzes each conversation for misunderstandings — corrections, wrong assumptions, over-engineering, communication breakdowns
3. A **Curator** takes all reflections together, identifies cross-session patterns, and adds/modifies/removes one-liner bullets in a structured playbook
4. The playbook is synced into configured output files between `<!-- retro:start/end -->` markers

**Two modes:**

| Mode | Flag | Behavior |
|---|---|---|
| **Silent** *(default)* | `--silent` or no flag | Auto-applies all curator decisions to the playbook |
| **Interactive** | `--verbose` | Shows proposed changes 5 at a time; you pick which to keep |

```bash
# Silent mode (default) — auto-apply
retro --offline --dir .

# Interactive mode — review each change
retro --offline --verbose --dir .

# Background daemon
retro --up --dir .            # start polling continuously
retro --down --dir .          # stop the daemon
```

In `--verbose` mode, you'll see batches of 5 proposed changes and can select by number, `a` (accept all), `s` (skip batch), or `q` (quit):

```
  Candidates 1-5 of 12:

  [1] + ADD to CODING_PATTERNS
      Always read the file before editing to avoid overwriting recent changes.

  [2] ~ MODIFY [coding-00003]
      Prefer Glob/Grep before editing unfamiliar files.

  [3] - DELETE [mistake-00007]

  Enter numbers to keep (e.g. 1,2), 'a' for all, 's' to skip all, or 'q' to quit:
  >
```

## Hypothesis Generation

Statistically identifies patterns in your sessions that predict explicit user rejection ("No, that's wrong", "undo this"). Useful for understanding what mistakes your AI agent keeps making and sharing discoveries with the community.

```bash
retro --hypogen --dir .       # find patterns in your sessions
retro --submit --dir .        # submit discoveries to the shared collection
retro --pull --dir .          # verify community hypotheses against your traces
retro --contribute --dir .    # contribute your verification stats back
```

Results are written to `.retro/hypoGen/HYPOTHESES.md`. Significant hypotheses can be submitted to [swe-hypotheses](https://github.com/RetroCode-Org/swe-hypotheses) via `retro --submit`. Use `retro --pull` to see how community-discovered patterns hold up against your own data, and `retro --contribute` to add your stats to the shared evidence base.

## AnalyzeMe — Your AI Coding Wrapped

Get a Spotify Wrapped-style breakdown of your AI coding history. See your persona, tool habits, coding schedule, patience score, and quirky fun facts — all computed locally from your traces with zero LLM calls.

```bash
retro --analyzeme --dir .               # terminal output
retro --analyzeme --save-html --dir .   # also save a shareable HTML report
```

**What you'll see:**

| Card | What it shows |
|---|---|
| **Persona** | Your coding personality (e.g. "The Terminal Wizard", "The Architect", "The Perfectionist") with description |
| **Toolkit** | Bar chart of your most-used tools (Read, Edit, Bash, Grep, etc.) |
| **Languages** | Top languages by files touched |
| **Schedule** | Night Owl vs Early Bird, peak coding hour, busiest day, longest streak |
| **Editing Style** | "Careful" (read-then-edit) vs "Cowboy" (edit-first) with a percentage bar |
| **Patience Score** | How often you say "No" to your AI, with commentary |
| **Delegation Score** | How much you use sub-agents vs handling things yourself |
| **AI Compatibility** | Combined score based on acceptance rate, tool diversity, and session engagement |
| **Fun Facts** | Quirky one-liners about your habits ("Your go-to tool was Bash — you two are inseparable") |

The `--save-html` flag generates a dark-themed, shareable HTML page at `.retro/wrapped.html` with gradient cards and animated bars.

Tool names are normalized across sources — Codex's `exec_command` becomes `Bash`, Cursor's `read_file_tool` becomes `Read`, etc. — so your stats are consistent regardless of which agents you use.

---

## Quickstart

```bash
# 1. Install
git clone <repo-url>
cd RetroCode
pip install -e .

# 2. Set your API key (pick one)
export COMMONSTACK_API_KEY=your_key_here   # default — free credits for members
# export OPENAI_API_KEY=your_key_here      # or OpenAI   (LLM_PROVIDER=openai)
# export ANTHROPIC_API_KEY=your_key_here   # or Anthropic (LLM_PROVIDER=anthropic)
# export GEMINI_API_KEY=your_key_here      # or Gemini    (LLM_PROVIDER=gemini)

# 3. Go to your project and run
cd ~/my-project
retro --offline --dir .
```

---

## Supported agents

Configure which traces to read and which rule files to update in `retro_config.yaml`:

```yaml
sources:
  inputs:  [claude-code, cursor, codex]   # default: all three
  outputs: [claude-code]                  # default: CLAUDE.md only
```

| | Claude Code | Cursor | Codex |
|---|---|---|---|
| **Input** (traces) | `~/.claude/projects/` | `~/.cursor/projects/` | `~/.codex/sessions/` |
| **Output** (rules) | `CLAUDE.md` | `.cursor/rules/retro.mdc` | `AGENTS.md` |

---

## Configuration

Drop a `retro_config.yaml` in your project root. See the root `retro_config.yaml` for a full example with comments.

Key options: `daemon.poll_interval`, `daemon.min_rounds`, `playbook.max_bullets`, `playbook.batch_size`, `playbook.default_model`, `sources.inputs`, `sources.outputs`.

See [docs/reference.md](docs/reference.md) for all options.

---

## LLM providers

Default is **CommonStack** (free credits for members). Override with `LLM_PROVIDER`:

| Provider | `LLM_PROVIDER` | Key env var |
|---|---|---|
| CommonStack *(default)* | `commonstack` | `COMMONSTACK_API_KEY` |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| Gemini | `gemini` | `GEMINI_API_KEY` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` |
