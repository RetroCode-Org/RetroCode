![RetroCode](assets/imgs/retro_wide.png)


Turn your Claude Code session traces into an auto-updating project playbook.

RetroCode runs as a background daemon, watches your Claude Code conversation history, and uses an LLM to extract patterns and insights — then writes them directly into your project's `CLAUDE.md` so future sessions benefit automatically.

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

# 3. Go to your project and start the daemon
cd ~/my-project
retro --up --dir .

# 4. Watch it work
tail -f .retro/daemon.log
```

That's it. Once enough new conversation rounds accumulate, RetroCode will update `.retro/playbook.txt` and inject the results into your `CLAUDE.md` automatically.

---

## How it works

1. Claude Code stores every session as a `.jsonl` trace in `~/.claude/projects/<project-key>/`
2. RetroCode polls those traces every `poll_interval` seconds
3. A **Reflector** agent analyzes new conversations for patterns, mistakes, and strategies
4. A **Curator** agent adds, modifies, or removes bullets in a structured playbook
5. The playbook is synced into your project's `CLAUDE.md` between two marker comments

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
# Start in background
retro --up --dir .

# Start in foreground (see logs live, useful for debugging)
retro --up --foreground --dir .

# Stop
retro --down --dir .
```

---

## Configuration

Drop a `retro_config.yaml` in your project root to override any defaults:

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
```

If no `retro_config.yaml` is present, built-in defaults are used.

---

## LLM providers

RetroCode uses **CommonStack** by default. CommonStack provides free credits for RetroCode users registered through this link: \<TBD\>.

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

The default model is `gpt-5.2`. Override it in `retro_config.yaml` under `playbook.default_model`.

---

---

## Source compatibility matrix

Configure which trace sources to ingest and which agent rule files to update
via `retro_config.yaml`:

```yaml
sources:
  inputs:  ["claude-code", "cursor", "codex"]   # which sessions to read
  outputs: ["claude-code", "cursor", "codex"]   # which rule files to update
```

### Inputs

| Source | `inputs` value | Trace location |
|---|---|---|
| Claude Code | `claude-code` | `~/.claude/projects/<key>/*.jsonl` |
| Cursor | `cursor` | `~/.cursor/projects/<key>/agent-transcripts/*/*.jsonl` |
| OpenAI Codex CLI | `codex` | `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl` (filtered by `cwd`) |

### Outputs

| Target | `outputs` value | File written | Format |
|---|---|---|---|
| Claude Code | `claude-code` | `CLAUDE.md` | Markdown between `<!-- retro:start/end -->` markers |
| Cursor | `cursor` | `.cursor/rules/retro.mdc` | MDC with `alwaysApply: true` frontmatter |
| OpenAI Codex CLI | `codex` | `AGENTS.md` | Markdown between `<!-- retro:start/end -->` markers |

**Default**: all three sources as inputs, only `claude-code` as output.
To write to all agents simultaneously:

```yaml
sources:
  inputs:  ["claude-code", "cursor", "codex"]
  outputs: ["claude-code", "cursor", "codex"]
```

---

## Output files

All intermediate files live in `.retro/` inside your project:

```
your-project/
  retro_config.yaml       # optional config
  CLAUDE.md               # auto-updated (Claude Code reads this)
  .retro/
    playbook.txt          # structured playbook with bullet IDs
    daemon.log            # full daemon logs
    .trace_state.json     # tracks which sessions have been processed
    .retro.pid            # daemon PID
```

The playbook is injected into `CLAUDE.md` between these markers — anything outside is untouched:

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

Bullets are capped at `max_bullets`. When exceeded, the curator is told to consolidate (merge or delete) to bring the count down.
