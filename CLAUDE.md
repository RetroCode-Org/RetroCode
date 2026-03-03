<!-- retro:start -->
# Playbook
## CODING_PATTERNS
[coding-00006] Separate agent integration points into modules (readers, writers/modifiers, exporters) and use marker-based patching when modifying user files to avoid clobbering content.
[coding-00005] Use a dedicated per-project state directory (e.g., .retro/) for logs, state DB, and generated artifacts; keep only the agent-consumed file (e.g., CLAUDE.md) at the repo root.
[coding-00004] For anything touching external formats/tools, default early to a plugin architecture: ABC/Protocol + registration/factory + thin tool adapters, so the main loop stays tool-agnostic.

## WORKFLOW_STRATEGIES
[workflow-00003] Keep a stable CLI surface even when adding YAML config: document and implement precedence as CLI flags > project YAML > defaults (flags shouldn’t silently disappear).
[workflow-00002] Ask early: “Is this a per-project tool or a globally-installed CLI?” and decide file locations accordingly (project-local state/config vs global installation/entrypoint).
[workflow-00001] Adopt an explicit “MVP-first, then stabilize interfaces” workflow: ship the smallest working loop first, then add seams (interfaces/ABCs) as soon as multi-tool support is hinted, and only then expand into config/packaging.

## COMMUNICATION
[communication-00012] After implementing filesystem-affecting changes, include a brief verification checklist: expected paths/files, how to tail logs, how to check daemon status, and a minimal repro command.

## COMMON_MISTAKES
[mistake-00010] Avoid brittle daemon detection: use a PID + metadata file scoped per project, verify the running process via /proc/<pid>/cmdline containing a unique token, and support multiple projects safely.
[mistake-00009] Centralize provider/model configuration and validate on startup (before daemonizing): ensure creds exist, provider-model compatibility, and parameter compatibility (e.g., max_tokens vs max_completion_tokens).
[mistake-00008] Standardize packaging/imports early: use a src/ layout with proper package imports, run in dev via python -m <package>, add a minimal CI smoke test for imports, and avoid mutating sys.path.
[mistake-00007] When you can’t actually inspect the user’s filesystem/process state, switch to “cannot verify” mode: avoid definitive claims and instead provide commands to run and ask for the outputs.

## TOOL_USAGE
[tool-00011] Bake in a first-class debug workflow: default to foreground on first run (or automatically fall back / persist last traceback when the daemon exits unexpectedly) and provide retro status and retro logs.
<!-- retro:end -->
