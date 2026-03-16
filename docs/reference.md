# RetroCode — Full Reference

## CLI

```
retro [command] [options]
```

### Commands

| Flag | Description |
|---|---|
| `--offline` | Process all new sessions once and update rule files, then exit |
| `--up` | Start a background daemon that polls continuously |
| `--down` | Stop the running daemon |
| `--hypogen` | Run the hypothesis generator against collected traces |
| `--submit` | Interactively review generated hypotheses and submit selected ones as a PR to [swe-hypotheses](https://github.com/RetroCode-Org/swe-hypotheses) |
| `--pull` | Download community hypotheses and verify them against your local traces |
| `--contribute` | Submit your local verification stats for community hypotheses back as a PR |
| `--analyzeme` | Your AI Coding Wrapped — fun stats about your vibe coding patterns |
| `--monitor` | Start the blast radius monitoring web dashboard |

### Global options

| Flag | Default | Description |
|---|---|---|
| `--dir DIR` | `.` | Project directory to monitor |
| `--playbook FILE` | `.retro/playbook.txt` | Playbook output file |
| `--claude-md FILE` | `CLAUDE.md` | CLAUDE.md to sync the playbook into |
| `-q` / `--quiet` | off | Suppress all non-error output |

### Playbook mode options

| Flag | Default | Description |
|---|---|---|
| `--verbose` | off | Interactive mode: review each proposed playbook change in batches of 5 before applying |
| `--silent` | on *(default)* | Auto-apply all playbook changes without review |

### Daemon options

| Flag | Description |
|---|---|
| `--foreground` | Run in foreground instead of forking (useful for debugging) |

### Submit options

`retro --submit` requires the `gh` CLI to be installed and authenticated (`gh auth login`).
It forks the target repo, writes one `hypotheses/<id>.md` per selected hypothesis, and opens a PR.
Each file includes YAML frontmatter with stats (OR, p-value, round counts) and the Python feature function.
Duplicate detection: if a hypothesis already exists in the community repo, you'll be directed to use `--contribute` instead.

### Pull & Contribute options

`retro --pull` downloads hypotheses from the community repo (no `gh` required — uses public GitHub API) and verifies each one against your local traces. Results are saved to `.retro/hypoGen/community_results.json`.

`retro --contribute` reads the saved verification results from `--pull` and submits your anonymous stats (round counts, OR, p-value) back to the community repo as a PR. Each verification is written to `verifications/<hypothesis_id>/<anon_hash>.json` — no project names or usernames are included in the data, only statistical results. Requires `gh` CLI.

### AnalyzeMe options

| Flag | Default | Description |
|---|---|---|
| `--analyzeme` | — | Run your AI Coding Wrapped |
| `--save-html` | off | Also generate a shareable HTML report at `.retro/wrapped.html` |

### Monitor options

| Flag | Default | Description |
|---|---|---|
| `--monitor` | — | Start the blast radius monitoring web dashboard |
| `--port PORT` | `8585` | Port for the monitoring dashboard |

### Hypothesis generator options

| Flag | Default | Description |
|---|---|---|
| `--no-llm` | off | Skip LLM calls; verify seed hypotheses only |
| `--label-llm` | off | Use LLM for round labeling instead of regex |
| `--max-iter N` | `2` | Number of LLM propose+refine cycles |

---

## retro_config.yaml

All fields are optional; built-in defaults are used for anything omitted.

```yaml
daemon:
  poll_interval: 30       # seconds between polling cycles (daemon mode only)
  min_rounds: 5           # minimum new rounds before triggering a playbook update
  pid_file: .retro.pid    # PID file path, relative to project root
  retro_dir: .retro       # directory for logs, state, and artifacts

playbook:
  max_bullets: 40         # hard cap on playbook bullets; curator consolidates when exceeded
  default_model: gpt-5.2  # LLM model for reflect + curate steps
  batch_size: 4           # max parallel reflections per batch
  sections:               # playbook section names -> bullet ID prefix
    CODING_PATTERNS:    coding
    WORKFLOW_STRATEGIES: workflow
    COMMUNICATION:      communication
    COMMON_MISTAKES:    mistake
    TOOL_USAGE:         tool
    OTHERS:             other

sources:
  inputs:                 # trace sources to ingest (all enabled by default)
    - claude-code
    - cursor
    - codex
  outputs:                # agent rule files to update (claude-code only by default)
    - claude-code
    - cursor
    - codex
```

---

## LLM providers

Set `LLM_PROVIDER` to select a provider. Default is `commonstack`.

| Provider | `LLM_PROVIDER` | Key env var |
|---|---|---|
| CommonStack *(default, free credits)* | `commonstack` | `COMMONSTACK_API_KEY`, `COMMONSTACK_API_URL` *(optional)* |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| Gemini | `gemini` | `GEMINI_API_KEY` |
| OpenRouter | `openrouter` | `OPENROUTER_API_KEY` |

The model can be overridden per-project via `playbook.default_model` in `retro_config.yaml`.

---

## Source compatibility matrix

### Inputs

| Agent | `inputs` value | Trace location |
|---|---|---|
| Claude Code | `claude-code` | `~/.claude/projects/<key>/*.jsonl` |
| Cursor | `cursor` | `~/.cursor/projects/<key>/agent-transcripts/*/*.jsonl` |
| OpenAI Codex CLI | `codex` | `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl` (filtered by `cwd`) |

Project key derivation: `/a/b/c` → `a-b-c` (Cursor/Codex) or `-a-b-c` (Claude Code).

### Outputs

| Agent | `outputs` value | File written | Mechanism |
|---|---|---|---|
| Claude Code | `claude-code` | `CLAUDE.md` | Injected between `<!-- retro:start -->` / `<!-- retro:end -->` markers |
| Cursor | `cursor` | `.cursor/rules/retro.mdc` | MDC file with `alwaysApply: true` frontmatter |
| OpenAI Codex CLI | `codex` | `AGENTS.md` | Injected between `<!-- retro:start -->` / `<!-- retro:end -->` markers |

Content outside the markers is never modified.

---

## Hypothesis generator (`--hypogen`)

The hypothesis generator statistically tests whether early patterns in a conversation round predict explicit user rejection in the next message.

### How it works

1. **Labeling** — each round is labeled 0 (rejected) if the next user message matches an explicit rejection pattern ("No, that's wrong", "undo this", etc.), otherwise 1 (ok)
2. **Feature extraction** — deterministic feature functions check for patterns within each round (e.g. "did the agent edit a file without reading it first?")
3. **Verification** — chi-squared test + odds ratio with Haldane-Anscombe correction
4. **LLM proposal** — an LLM proposes new feature functions based on rejected vs ok round examples, which are compiled and statistically verified
5. **Refinement** — non-significant hypotheses are refined by the LLM and re-tested

### Outputs (written to `.retro/hypoGen/`)

| File | Description |
|---|---|
| `HYPOTHESES.md` | Human-readable report: significant and non-significant hypotheses with stats |
| `results.json` | Raw numbers: OR, p-value, n(signal), n(rejected) for every hypothesis |
| `results_features.py` | Standalone Python feature functions for all verified hypotheses |
| `labeled_traces.json` | Persisted round labels (cached across runs) |

### Seed hypotheses

| ID | Signal |
|---|---|
| `edit_without_read` | Agent edits a file without having Read it first |
| `edit_without_search` | Agent edits files without any Glob/Grep search |
| `more_edits_than_reads` | Agent makes more edits than reads in the round |
| `bash_fails` | A Bash command produced an error |
| `no_search_before_action` | Agent takes action (Edit/Bash) without any prior search |

### Report columns

| Column | Meaning |
|---|---|
| `rounds(signal)` | Total rounds where the feature fired |
| `rejected(signal)` | Of those, how many were rejected by the user |
| `rounds(no-signal)` | Total rounds where the feature did not fire |
| `rejected(no-signal)` | Of those, how many were rejected |
| `OR [95% CI]` | Odds ratio (< 1 means signal predicts rejection) |
| `p-value` | Fisher's exact / chi-squared p-value; significant < 0.05 |

---

## Output file structure

```
your-project/
  retro_config.yaml           # optional config
  CLAUDE.md                   # updated if claude-code in outputs
  AGENTS.md                   # updated if codex in outputs
  .cursor/
    rules/
      retro.mdc               # updated if cursor in outputs
  .retro/
    playbook.txt              # structured playbook with bullet IDs
    daemon.log                # full daemon logs
    .trace_state.json         # tracks processed session IDs
    .retro.pid                # daemon PID
    wrapped.html              # from --analyzeme --save-html
    hypoGen/
      HYPOTHESES.md
      results.json
      results_features.py
      labeled_traces.json
      community_results.json  # from --pull (community verification)
```

---

## Playbook format

Bullets are stored with stable IDs so the Curator can modify them in place across runs:

```
## CODING_PATTERNS
[coding-00001] Always read a file before editing it.
[coding-00002] Use Glob/Grep to understand a codebase before making changes.

## COMMON_MISTAKES
[mistake-00003] Do not assume a file exists — verify with Glob first.
```

ID format: `<prefix>-<5-digit-number>`. Prefixes are configured under `playbook.sections`.

---

## AnalyzeMe (`--analyzeme`)

A zero-LLM-cost analysis that reads your traces locally and renders fun statistics about your AI coding habits.

### Cards

| Card | Description |
|---|---|
| Persona | Coding personality assigned based on your usage patterns |
| Toolkit | Bar chart of tool usage (top 6 tools, normalized across sources) |
| Languages | Top languages by files touched (extracted from `file_path` in tool args) |
| Schedule | Night Owl / Early Bird / Afternoon / Evening, peak hour, busiest day, longest streak |
| Editing Style | "Careful" (>= 60% read-before-edit) vs "Cowboy" |
| Patience | `(1 - rejections / total_rounds) * 100` — how often you accept AI output |
| Delegation | Percentage of rounds that used the `Agent` tool |
| AI Compatibility | `acceptance_rate * 0.5 + tool_diversity * 0.25 + engagement * 0.25` |
| Fun Facts | Quirky auto-generated one-liners |

### Personas

| Persona | Trigger |
|---|---|
| The Conversationalist | Zero tool calls |
| The Architect | Delegation > 20% |
| The Impatient Trailblazer | Cowboy editing + low patience |
| The Speed Demon | Cowboy editing + high patience |
| The Perfectionist | Patience < 60% |
| The Power User | Avg tools per round > 8 |
| The Terminal Wizard | More Bash calls than Edit calls |
| The Code Detective | Grep + Glob > 30% of tool calls |
| The Methodical Craftsman | Careful editing style |
| The Balanced Coder | Default fallback |

### Tool name normalization

Tool names are normalized across sources so stats are consistent:

| Source tool name | Canonical name |
|---|---|
| `exec_command`, `shell`, `terminal`, `run_terminal_cmd` | `Bash` |
| `read_file`, `readfile`, `read_file_tool` | `Read` |
| `write_file`, `writefile` | `Write` |
| `edit_file`, `editfile`, `patch`, `apply_diff`, `edit_file_tool` | `Edit` |
| `search`, `grep`, `search_files`, `codebase_search` | `Grep` |
| `find_files`, `glob`, `list_dir`, `listdir`, `ls`, `list_files`, `file_search` | `Glob` |
| `update_plan` | `Agent` |

### HTML export

`--save-html` writes `.retro/wrapped.html` — a self-contained HTML file with:
- Dark gradient background
- Glassmorphism cards with `backdrop-filter: blur`
- Animated progress bars
- Gradient-filled tool/language bar charts
- No external dependencies — works offline
