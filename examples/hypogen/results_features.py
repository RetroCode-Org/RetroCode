"""
Auto-generated feature functions for Claude Code trace hypotheses.
Each function takes msgs (list[dict]) and returns bool.
"""
from __future__ import annotations
import json, re
from src.hypoGen.generator.hypothesis import (
    get_early_pct, iter_tool_calls, iter_tool_results, _parse_args,
    EDIT_TOOLS, READ_TOOLS, SEARCH_TOOLS, BASH_TOOL, AGENT_TOOL, ERROR_KWS,
)

# not significant  |  OR=0.63  p=0.7390
# [TOXIC] In this round, agent edits a file without having Read it first.
def feat_edit_without_read(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, agent edits a file without having Read it first."""
    read_files: set[str] = set()
    for tn, args in iter_tool_calls(msgs):
        if tn in READ_TOOLS:
            read_files.add(args.get("file_path", ""))
        elif tn in EDIT_TOOLS:
            path = args.get("file_path", "")
            if path and path not in read_files:
                return True
    return False

# not significant  |  OR=0.88  p=0.9260
# [TOXIC] In this round, agent edits files without any Glob/Grep search.
def feat_edit_without_search(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, agent edits files without any Glob/Grep search."""
    has_search = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
    has_edit = any(tn in EDIT_TOOLS for tn, _ in iter_tool_calls(msgs))
    return has_edit and not has_search

# not significant  |  OR=0.51  p=0.6242
# [TOXIC] In this round, agent makes more edits than reads.
def feat_more_edits_than_reads(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, agent makes more edits than reads."""
    reads = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in READ_TOOLS)
    edits = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in EDIT_TOOLS)
    return edits >= 2 and edits > reads

# SIGNIFICANT  |  OR=0.06  p=0.0108
# [TOXIC] In this round, a Bash command produced an error.
def feat_bash_fails(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, a Bash command produced an error."""
    for name, content in iter_tool_results(msgs):
        if name == BASH_TOOL and any(kw in content.lower() for kw in ERROR_KWS):
            return True
    return False

# not significant  |  OR=1.60  p=0.7390
# [TOXIC] In this round, agent takes action (Edit/Bash) without any search.
def feat_no_search_before_action(msgs: list[dict]) -> bool:
    """[TOXIC] In this round, agent takes action (Edit/Bash) without any search."""
    has_action = any(
        tn in EDIT_TOOLS or tn == BASH_TOOL
        for tn, _ in iter_tool_calls(msgs)
    )
    has_search = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
    return has_action and not has_search

# SIGNIFICANT  |  OR=0.08  p=0.0268
# If the agent performs multiple consecutive edits on the same file, the user is more likely to reject it.
def feat_multiple_consecutive_edits(msgs):
    edit_count = 0
    last_file_path = None
    for tn, args in iter_tool_calls(msgs):
        if tn == 'Edit':
            path = args.get('file_path', '')
            if path == last_file_path:
                edit_count += 1
            else:
                edit_count = 1
            last_file_path = path
        if edit_count > 3:
            return True
    return False

# not significant  |  OR=0.26  p=0.3052
# If the agent writes to a file without reading it first, the user is more likely to reject it.
def feat_write_without_read(msgs):
    read_files = set()
    for tn, args in iter_tool_calls(msgs):
        if tn == 'Read':
            read_files.add(args.get('file_path', ''))
        if tn == 'Write':
            if args.get('file_path', '') not in read_files:
                return True
    return False

# not significant  |  OR=0.40  p=0.7058
# If the agent executes a high number of Bash commands in a single round, the user is more likely to reject it.
def feat_frequent_bash_commands(msgs):
    bash_count = 0
    for tn, _ in iter_tool_calls(msgs):
        if tn == 'Bash':
            bash_count += 1
    return bash_count > 5

# not significant  |  OR=0.58  p=0.7010
# In this round, the agent edits a file without having successfully Read it first.
def feat_edit_without_read_v2(msgs):

    read_files = set()
    for tn, args in iter_tool_calls(msgs):
        if tn == 'Read':
            read_files.add(args.get('file_path', ''))

    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            if args.get('file_path', '') not in read_files:
                return True

    return False

# not significant  |  OR=0.31  p=0.3863
# In this round, the agent performs file edits without any prior contextual Read operation on the same file.
def feat_edit_without_search_v2(msgs):
    edited_files = set()
    read_files = set()

    for tn, args in iter_tool_calls(msgs):
        if tn == 'Edit':
            edited_files.add(args.get('file_path', ''))
        elif tn == 'Read':
            read_files.add(args.get('file_path', ''))

    # Check if there are edits without prior reads on the same file
    return any(file for file in edited_files if file not in read_files)

# not significant  |  OR=0.04  p=1.0000
# In this round, the agent makes multiple edits without any successful reads.
def feat_more_edits_than_reads_v2(msgs):
    read_success = any(name == 'Read' and 'error' not in content.lower() for name, content in iter_tool_results(msgs))
    edit_count = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in EDIT_TOOLS)
    not read_success and edit_count > 0

# not significant  |  OR=0.34  p=0.4267
# In this round, the agent takes action (Edit/Bash) without any search and encounters an error.
def feat_no_search_before_action_v2(msgs):

    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS or tn == BASH_TOOL:
            # Check if there was a search before the action
            search_before_action = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
            if not search_before_action:
                # Check if there was an error in the tool results
                for name, content in iter_tool_results(msgs):
                    if any(error_kw in content.lower() for error_kw in ERROR_KWS):
                        return True
    return False

# not significant  |  OR=0.40  p=0.7058
# If the agent writes to a file without first gathering sufficient context (e.g., reading related files or checking existing content), the user is more likely to reject it.
def feat_write_without_read_v2(msgs):
    write_actions = 0
    context_gathered = False

    for tn, args in iter_tool_calls(msgs):
        if tn in READ_TOOLS or tn == 'Bash':
            context_gathered = True
        if tn in EDIT_TOOLS or tn == 'Write':
            write_actions += 1

    # If there are write actions but no context was gathered before them
    if write_actions > 0 and not context_gathered:
        return True

    return False

# not significant  |  OR=0.21  p=0.7930
# If the agent executes multiple Bash commands that result in errors within a single round, the user is more likely to reject it.
def feat_frequent_bash_commands_v2(msgs):

    error_count = 0
    for name, content in iter_tool_results(msgs):
        if name == BASH_TOOL and any(kw in content.lower() for kw in ERROR_KWS):
            error_count += 1
    return error_count > 2

# not significant  |  OR=0.21  p=0.2248
# If the agent performs an excessive number of file edits in a single round, the user is more likely to reject it.
def feat_excessive_file_edits(msgs):
    edit_count = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in EDIT_TOOLS)
    return edit_count > 5

# not significant  |  OR=0.21  p=0.7930
# If the agent frequently uses Bash commands and encounters errors, the user is more likely to reject it.
def feat_frequent_bash_with_errors(msgs):
    bash_count = sum(1 for tn, _ in iter_tool_calls(msgs) if tn == BASH_TOOL)
    error_count = sum(1 for name, content in iter_tool_results(msgs) if name == BASH_TOOL and any(kw in content.lower() for kw in ERROR_KWS))
    return bash_count > 3 and error_count > 0

# not significant  |  OR=0.40  p=0.5066
# If the agent repeatedly edits the same file multiple times in a round, the user is more likely to reject it.
def feat_repeated_edit_on_same_file(msgs):
    edit_paths = [args.get('file_path', '') for tn, args in iter_tool_calls(msgs) if tn in EDIT_TOOLS]
    return len(edit_paths) != len(set(edit_paths))

# not significant  |  OR=0.58  p=0.7010
# In this round, the agent edits a file without having successfully Read it first.
def feat_edit_without_read_v2(msgs):
    read_files = set()
    for tn, args in iter_tool_calls(msgs):
        if tn == 'Read':
            read_files.add(args.get('file_path', ''))
    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            if args.get('file_path', '') not in read_files:
                return True
    return False

# not significant  |  OR=0.31  p=0.3863
# In this round, the agent performs file edits without any prior contextual Read operation on the same file.
def feat_edit_without_search_v2(msgs):
    edited_files = set()
    read_files = set()

    for tn, args in iter_tool_calls(msgs):
        if tn == 'Edit':
            edited_files.add(args.get('file_path', ''))
        elif tn == 'Read':
            read_files.add(args.get('file_path', ''))

    # Check if there are edits without prior reads on the same file
    return any(file for file in edited_files if file not in read_files)

# not significant  |  OR=0.04  p=1.0000
# In this round, the agent makes multiple edits without any successful reads.
def feat_more_edits_than_reads_v2(msgs):
    read_success = any(name == 'Read' and 'error' not in content.lower() for name, content in iter_tool_results(msgs))
    edit_count = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in EDIT_TOOLS)
    read_count = sum(1 for tn, _ in iter_tool_calls(msgs) if tn in READ_TOOLS)
    not read_success and edit_count > 0 and read_count == 0

# not significant  |  OR=0.34  p=0.4267
# In this round, the agent takes action (Edit/Bash) without any search and encounters an error.
def feat_no_search_before_action_v2(msgs):

    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS or tn == BASH_TOOL:
            # Check if there was a search before the action
            search_before_action = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
            if not search_before_action:
                # Check if there was an error in the tool results
                for name, content in iter_tool_results(msgs):
                    if any(error_kw in content.lower() for error_kw in ERROR_KWS):
                        return True
    return False

# not significant  |  OR=0.21  p=0.2248
# If the agent writes to a file without sufficient context or understanding, the user is more likely to reject it.
def feat_write_without_read_v2(msgs):

    read_before_write = False
    for tn, args in iter_tool_calls(msgs):
        if tn in READ_TOOLS:
            read_before_write = True
        if tn in EDIT_TOOLS and not read_before_write:
            return True
        if tn == 'Write' and not read_before_write:
            return True
    return False

# not significant  |  OR=0.21  p=0.7930
# If the agent executes multiple Bash commands that result in errors within a single round, the user is more likely to reject it.
def feat_frequent_bash_commands_v2(msgs):

    error_count = 0
    for name, content in iter_tool_results(msgs):
        if name == BASH_TOOL and any(kw in content.lower() for kw in ERROR_KWS):
            error_count += 1
    return error_count > 2

# not significant  |  OR=0.50  p=0.6703
# In this round, the agent edits a file without having successfully Read it first, and there are no successful Write operations before the Edit.
def feat_edit_without_read_v2_v2(msgs):
    read_successful = False
    write_successful = False
    for tn, args in iter_tool_calls(msgs):
        if tn == 'Read':
            read_successful = True
        elif tn == 'Write':
            write_successful = True
        elif tn == 'Edit' and not read_successful and not write_successful:
            return True
    return False

# not significant  |  OR=0.58  p=0.7010
# In this round, the agent performs file edits without any prior contextual Read or Write operation on the same file.
def feat_edit_without_search_v2_v2(msgs):
    edited_files = set()
    read_or_written_files = set()

    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            edited_files.add(args.get('file_path', ''))
        elif tn in READ_TOOLS or tn == 'Write':
            read_or_written_files.add(args.get('file_path', ''))

    # Check if there are any edited files that were not read or written to first
    return any(file not in read_or_written_files for file in edited_files)

# not significant  |  OR=0.30  p=0.7458
# In this round, the agent makes multiple edits without any successful reads or context-establishing actions.
def feat_more_edits_than_reads_v2_v2(msgs):

    read_success = False
    edit_count = 0

    for tn, args in iter_tool_calls(msgs):
        if tn in READ_TOOLS:
            read_success = True
        elif tn in EDIT_TOOLS:
            edit_count += 1

    # Check if there are multiple edits without any successful reads
    if edit_count > 1 and not read_success:
        return True

    return False

# not significant  |  OR=0.21  p=0.7930
# In this round, the agent takes action (Edit/Bash) without any search and encounters a critical error (e.g., command not found, file not found).
def feat_no_search_before_action_v2_v2(msgs):

    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS or tn == BASH_TOOL:
            # Check if there was a search before the action
            search_before_action = any(tn in SEARCH_TOOLS for tn, _ in iter_tool_calls(msgs))
            if not search_before_action:
                # Check for critical errors in tool results
                for name, content in iter_tool_results(msgs):
                    if name == BASH_TOOL and any(kw in content.lower() for kw in ["command not found", "file not found", "no such file or directory"]):
                        return True
    return False

# not significant  |  OR=0.04  p=1.0000
# If the agent writes to a file without first successfully reading any related files or checking existing content, the user is more likely to reject it.
def feat_write_without_read_v2_v2(msgs):
    has_written = False
    has_successful_read = False

    for tn, args in iter_tool_calls(msgs):
        if tn in WRITE_TOOLS:
            has_written = True
        elif tn in READ_TOOLS:
            path = args.get('file_path', '')
            for name, content in iter_tool_results(msgs):
                if name == 'Read' and 'File does not exist' not in content:
                    has_successful_read = True
                    break

    return has_written and not has_successful_read

# SIGNIFICANT  |  OR=0.03  p=0.0001
# If the agent executes multiple Bash commands that result in errors, and the errors are not addressed or resolved within the same round, the user is more likely to reject it.
def feat_frequent_bash_commands_v2_v2(msgs):

    error_count = 0
    resolved = False

    for name, content in iter_tool_results(msgs):
        if name == BASH_TOOL:
            if any(kw in content.lower() for kw in ERROR_KWS):
                error_count += 1
            elif 'success' in content.lower() or 'resolved' in content.lower():
                resolved = True

    # Check if there are multiple errors and they are not resolved
    return error_count > 1 and not resolved

# SIGNIFICANT  |  OR=0.10  p=0.0499
# If the agent performs multiple redundant file edits in a single round, the user is more likely to reject it.
def feat_excessive_file_edits_v2(msgs):
    edit_counts = {}
    for tn, args in iter_tool_calls(msgs):
        if tn in EDIT_TOOLS:
            path = args.get('file_path', '')
            edit_counts[path] = edit_counts.get(path, 0) + 1
    redundant_edits = any(count > 3 for count in edit_counts.values())
    return redundant_edits

# SIGNIFICANT  |  OR=0.04  p=0.0025
# If the agent frequently uses Bash commands and encounters errors without resolving them, the user is more likely to reject it.
def feat_frequent_bash_with_errors_v2(msgs):

    error_count = 0
    resolved_errors = 0

    for name, content in iter_tool_results(msgs):
        if name == BASH_TOOL:
            if any(kw in content.lower() for kw in ERROR_KWS):
                error_count += 1
            elif 'successfully' in content.lower() or 'requirement already satisfied' in content.lower():
                resolved_errors += 1

    # Check if there are unresolved errors
    return error_count > 0 and resolved_errors == 0

# SIGNIFICANT  |  OR=0.10  p=0.0499
# If the agent performs excessive repeated edits on the same file within a round, the user is more likely to reject it.
def feat_repeated_edit_on_same_file_v2(msgs):
    from collections import Counter

    edit_counts = Counter()

    for tn, args in iter_tool_calls(msgs):
        if tn == 'Edit':
            path = args.get('file_path', '')
            edit_counts[path] += 1

    # Define 'excessive' as more than 3 edits on the same file
    return any(count > 3 for count in edit_counts.values())

