![RetroCode](assets/imgs/retro_wide.png)

Turn your AI coding agent sessions into an auto-updating project playbook.

RetroCode watches conversation traces from Claude Code, Cursor, and Codex, extracts patterns and insights using an LLM, and writes them directly into your project's agent rule files (`CLAUDE.md`, `.cursor/rules/retro.mdc`, `AGENTS.md`) so every future session benefits automatically.

---

## Quickstart

```bash
# 1. Install
git clone <repo-url>
cd RetroCode
pip install -e .

# 2. Set your API key (pick one)
export COMMONSTACK_API_KEY=your_key_here   # default — free credits for members
# export OPENAI_API_KEY=your_key_here      # or use OpenAI  (LLM_PROVIDER=openai)
# export ANTHROPIC_API_KEY=your_key_here   # or Anthropic   (LLM_PROVIDER=anthropic)
# export GEMINI_API_KEY=your_key_here      # or Gemini      (LLM_PROVIDER=gemini)
# export OPENROUTER_API_KEY=your_key_here  # or OpenRouter  (LLM_PROVIDER=openrouter)

# 3. Go to your project and run once
cd ~/my-project
retro --offline --dir .
```

That's it. RetroCode will read all new sessions from your configured agent tools, update the playbook, and write it into your rule files.

---

## How it works

1. RetroCode reads session traces from Claude Code, Cursor, and/or Codex
2. A **Reflector** agent analyzes new conversations for patterns, mistakes, and strategies
3. A **Curator** agent adds, modifies, or removes bullets in a structured playbook
4. The playbook is synced into your configured output files between `<!-- retro:start -->` / `<!-- retro:end -->` markers

---

## Installation

```bash
git clone <repo-url>
cd RetroCode
pip install -e .
```

Requires Python 3.11+.

---

## Usage

```bash
# Run once — process all new sessions and update rule files, then exit
retro --offline --dir .

# Start a background daemon that polls continuously
retro --up --dir .

# Start daemon in foreground (useful for debugging)
retro --up --foreground --dir .

# Stop the daemon
retro --down --dir .

# Generate hypotheses about what causes rejections in your sessions
retro --hypogen --dir .
```

---

## Configuration

Drop a `retro_config.yaml` in your project root. See the project root for a full example. Key options:

```yaml
daemon:
  poll_interval: 30       # seconds between polling cycles
  min_rounds: 5           # minimum new conversation rounds before triggering update
  pid_file: .retro.pid
  retro_dir: .retro

playbook:
  max_bullets: 40         # hard cap; curator consolidates when exceeded
  default_model: gpt-5.2
  sections:
    CODING_PATTERNS: coding
    WORKFLOW_STRATEGIES: workflow
    COMMUNICATION: communication
    COMMON_MISTAKES: mistake
    TOOL_USAGE: tool
    OTHERS: other

sources:
  inputs:                 # which agent traces to read
    - claude-code
    - cursor
    - codex
  outputs:                # which rule files to update
    - claude-code         # writes CLAUDE.md
    - cursor              # writes .cursor/rules/retro.mdc
    - codex               # writes AGENTS.md
```

---

## Source compatibility matrix

### Inputs — where RetroCode reads traces from

| Agent | `inputs` value | Trace location |
|---|---|---|
| Claude Code | `claude-code` | `~/.claude/projects/<key>/*.jsonl` |
| Cursor | `cursor` | `~/.cursor/projects/<key>/agent-transcripts/*/*.jsonl` |
| OpenAI Codex CLI | `codex` | `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl` (filtered by `cwd`) |

### Outputs — where RetroCode writes the playbook

| Agent | `outputs` value | File written | Format |
|---|---|---|---|
| Claude Code | `claude-code` | `CLAUDE.md` | Markdown between retro markers |
| Cursor | `cursor` | `.cursor/rules/retro.mdc` | MDC with `alwaysApply: true` |
| OpenAI Codex CLI | `codex` | `AGENTS.md` | Markdown between retro markers |

Default: all three inputs enabled, only `claude-code` output. To sync all agents:

```yaml
sources:
  inputs:  [claude-code, cursor, codex]
  outputs: [claude-code, cursor, codex]
```

---

## LLM providers

RetroCode uses **CommonStack** by default. CommonStack provides free credits for members, so most users won't need to configure anything beyond setting `COMMONSTACK_API_KEY`.

If you prefer to use your own API key from another provider, set `LLM_PROVIDER` before running:

```bash
# OpenAI
export LLM_PROVIDER=openai
export OPENAI_API_KEY=your_key_here

# Anthropic
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=your_key_here

# Gemini
export LLM_PROVIDER=gemini
export GEMINI_API_KEY=your_key_here

# OpenRouter (for other models)
export LLM_PROVIDER=openrouter
export OPENROUTER_API_KEY=your_key_here

# CommonStack (default — free credits available)
export COMMONSTACK_API_KEY=your_key_here
```

| Provider | `LLM_PROVIDER` | Key env var |
|---|---|---|
| CommonStack *(default, free credits)* | `commonstack` | `COMMONSTACK_API_KEY`, `COMMONSTACK_API_URL` *(optional)* |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| Gemini | `gemini` | `GEMINI_API_KEY` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` |

The default model is `gpt-5.2`. Override with `playbook.default_model` in `retro_config.yaml`.

---

## Output files

All intermediate files live in `.retro/` inside your project:

```
your-project/
  retro_config.yaml           # optional config
  CLAUDE.md                   # updated if claude-code in outputs
  AGENTS.md                   # updated if codex in outputs
  .cursor/rules/retro.mdc     # updated if cursor in outputs
  .retro/
    playbook.txt              # structured playbook with bullet IDs
    daemon.log                # full daemon logs
    .trace_state.json         # tracks which sessions have been processed
    .retro.pid                # daemon PID
```

The playbook is injected between these markers — anything outside is untouched:

```
<!-- retro:start -->
# Playbook
...
<!-- retro:end -->
```

---

## Playbook operations

Each cycle the Curator can perform:

- **ADD** — insert a new insight bullet into a section
- **MODIFY** — update an existing bullet in place (keeps its ID)
- **DELETE** — remove a bullet that is outdated or contradicted

Bullets are capped at `max_bullets`. When exceeded, the curator consolidates (merges or deletes) to bring the count down.
