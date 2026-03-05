<!-- retro:start -->
# Playbook
## CODING_PATTERNS
[coding-00018] Introduce a cross-trace action-extraction layer that normalizes tool usage into a common event stream (read/search/edit/bash/etc.), including extractors for sources where tool calls are embedded in text; keep features source-agnostic.
[coding-00017] Add small contract tests per reader to validate canonical schema compliance (required fields, types, ordering invariants) so multi-source pipelines fail fast and consistently.
[coding-00016] Do not bypass ingestion adapters in downstream pipelines: define a single canonical intermediate schema (e.g., Message/Turn/Round) produced by all readers, and require all analytics/features to consume only that schema.
[coding-00006] Separate agent integration points into modules (readers, writers/modifiers, exporters) and use marker-based patching when modifying user files to avoid clobbering content.
[coding-00005] Use a dedicated per-project state directory (e.g., .retro/) for logs, state DB, and generated artifacts; keep only the agent-consumed file (e.g., CLAUDE.md) at the repo root.
[coding-00004] For anything touching external formats/tools, default early to a plugin architecture: ABC/Protocol + registration/factory + thin tool adapters, so the main loop stays tool-agnostic.

## WORKFLOW_STRATEGIES
[workflow-00014] When a user asks for an “example,” clarify whether they want (a) generated output from their data, (b) checked-in sample artifacts under examples/, or (c) a minimal synthetic dataset + expected outputs; implement the chosen form explicitly.
[workflow-00013] Add a “Definitions & acceptance tests” checkpoint before building/refactoring analytics/labeling pipelines: confirm unit of analysis, label definition, feature window, and 2–3 concrete trace examples with expected labels; don’t refactor until these are agreed.
[workflow-00003] Keep a stable CLI surface even when adding YAML config: document and implement precedence as CLI flags > project YAML > defaults (flags shouldn’t silently disappear).
[workflow-00002] Ask early: “Is this a per-project tool or a globally-installed CLI?” and decide file locations accordingly (project-local state/config vs global installation/entrypoint).
[workflow-00001] Adopt an explicit “MVP-first, then stabilize interfaces” workflow: ship the smallest working loop first, then add seams (interfaces/ABCs) as soon as multi-tool support is hinted, and only then expand into config/packaging.

## COMMUNICATION
[communication-00015] Before major changes (especially after user corrections), restate the spec in bullets: unit of analysis, label/signal, feature window, and what constitutes a “significant productivity impact,” then proceed only after confirmation.
[communication-00012] After implementing filesystem-affecting changes, include a brief verification checklist: expected paths/files, how to tail logs, how to check daemon status, and a minimal repro command.

## COMMON_MISTAKES
[mistake-00020] For external API failures, log the exact request/response (status + body), reproduce with a minimal script matching the known-good curl (base URL/model/headers), and only then adjust defaults; avoid sweeping config/model changes without user confirmation.
[mistake-00019] Avoid filename-derived session IDs and dedupe keys: require each reader to return (source, session_id, trace_path) and use (source, session_id) as the canonical identifier for processing state/deduplication.
[mistake-00010] Avoid brittle daemon detection: use a PID + metadata file scoped per project, verify the running process via /proc/<pid>/cmdline containing a unique token, and support multiple projects safely.
[mistake-00009] Centralize provider/model configuration and validate on startup (before daemonizing): ensure creds exist, provider-model compatibility, and parameter compatibility (e.g., max_tokens vs max_completion_tokens).
[mistake-00008] Standardize packaging/imports early: use a src/ layout with proper package imports, run in dev via python -m <package>, add a minimal CI smoke test for imports, and avoid mutating sys.path.
[mistake-00007] [mistake-00007] Enforce strict “cannot verify” mode when execution isn’t performed in the current environment: never claim commands “work/ran successfully” or that outputs exist unless tool output is shown in-trace; instead provide exact commands and request the resulting logs/snippets.

## TOOL_USAGE
[tool-00021] If the repo provides an agent/skills instruction file, treat it as higher-priority local policy: detect skill triggers, constrain actions to allowed-tools, and explicitly cite which skill/policy is being applied.
[tool-00011] Bake in a first-class debug workflow: default to foreground on first run (or automatically fall back / persist last traceback when the daemon exits unexpectedly) and provide retro status and retro logs.
<!-- retro:end -->
