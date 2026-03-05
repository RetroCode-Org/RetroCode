# Claude Code Round Hypothesis Tracker

**Rounds analyzed:** 62
**Last updated:** 2026-03-04
**Significance criteria:** global p < 0.05

---

## Significant

| ID | Description | rounds(signal) | rejected(signal) | rounds(no-signal) | rejected(no-signal) | OR [95% CI] | p-value |
|---|---|---:|---:|---:|---:|---|---:|
| `bash_fails` | In this round, a Bash command produced an error. | 4 | 1 | 58 | 1 | 0.06 [0.00, 0.75] | 0.011 |
| `multiple_consecutive_edits` | If the agent performs multiple consecutive edits on the same file, the user is more likely to reject it. | 5 | 1 | 57 | 1 | 0.08 [0.01, 0.93] | 0.027 |
| `frequent_bash_commands_v2_v2` | If the agent executes multiple Bash commands that result in errors, and the errors are not addressed or resolved within the same round, the user is more likely to reject it. | 2 | 1 | 60 | 1 | 0.03 [0.00, 0.41] | <0.001 |
| `excessive_file_edits_v2` | If the agent performs multiple redundant file edits in a single round, the user is more likely to reject it. | 6 | 1 | 56 | 1 | 0.10 [0.01, 1.12] | 0.050 |
| `frequent_bash_with_errors_v2` | If the agent frequently uses Bash commands and encounters errors without resolving them, the user is more likely to reject it. | 3 | 1 | 59 | 1 | 0.04 [0.00, 0.57] | 0.002 |
| `repeated_edit_on_same_file_v2` | If the agent performs excessive repeated edits on the same file within a round, the user is more likely to reject it. | 6 | 1 | 56 | 1 | 0.10 [0.01, 1.12] | 0.050 |

---

## Not Significant

| ID | Description | rounds(signal) | rejected(signal) | rounds(no-signal) | rejected(no-signal) | OR [95% CI] | p-value |
|---|---|---:|---:|---:|---:|---|---:|
| `edit_without_read` | In this round, agent edits a file without having Read it first. | 24 | 1 | 38 | 1 | 0.63 [0.06, 6.38] | 0.739 |
| `edit_without_search` | In this round, agent edits files without any Glob/Grep search. | 29 | 1 | 33 | 1 | 0.88 [0.09, 8.91] | 0.926 |
| `more_edits_than_reads` | In this round, agent makes more edits than reads. | 21 | 1 | 41 | 1 | 0.51 [0.05, 5.18] | 0.624 |
| `no_search_before_action` | In this round, agent takes action (Edit/Bash) without any search. | 38 | 1 | 24 | 1 | 1.60 [0.16, 16.26] | 0.739 |
| `write_without_read` | If the agent writes to a file without reading it first, the user is more likely to reject it. | 13 | 1 | 49 | 1 | 0.26 [0.02, 2.69] | 0.305 |
| `frequent_bash_commands` | If the agent executes a high number of Bash commands in a single round, the user is more likely to reject it. | 4 | 0 | 58 | 2 | 0.40 [0.02, 9.62] | 0.706 |
| `edit_without_read_v2` | In this round, the agent edits a file without having successfully Read it first. | 23 | 1 | 39 | 1 | 0.58 [0.06, 5.96] | 0.701 |
| `edit_without_search_v2` | In this round, the agent performs file edits without any prior contextual Read operation on the same file. | 15 | 1 | 47 | 1 | 0.31 [0.03, 3.23] | 0.386 |
| `more_edits_than_reads_v2` | In this round, the agent makes multiple edits without any successful reads. | 0 | 0 | 62 | 2 | 0.04 [0.00, 2.54] | 1.000 |
| `no_search_before_action_v2` | In this round, the agent takes action (Edit/Bash) without any search and encounters an error. | 16 | 1 | 46 | 1 | 0.34 [0.03, 3.52] | 0.427 |
| `write_without_read_v2` | If the agent writes to a file without first gathering sufficient context (e.g., reading related files or checking existing content), the user is more likely to reject it. | 4 | 0 | 58 | 2 | 0.40 [0.02, 9.62] | 0.706 |
| `frequent_bash_commands_v2` | If the agent executes multiple Bash commands that result in errors within a single round, the user is more likely to reject it. | 2 | 0 | 60 | 2 | 0.21 [0.01, 5.73] | 0.793 |
| `excessive_file_edits` | If the agent performs an excessive number of file edits in a single round, the user is more likely to reject it. | 11 | 1 | 51 | 1 | 0.21 [0.02, 2.20] | 0.225 |
| `frequent_bash_with_errors` | If the agent frequently uses Bash commands and encounters errors, the user is more likely to reject it. | 2 | 0 | 60 | 2 | 0.21 [0.01, 5.73] | 0.793 |
| `repeated_edit_on_same_file` | If the agent repeatedly edits the same file multiple times in a round, the user is more likely to reject it. | 18 | 1 | 44 | 1 | 0.40 [0.04, 4.14] | 0.507 |
| `edit_without_read_v2` | In this round, the agent edits a file without having successfully Read it first. | 23 | 1 | 39 | 1 | 0.58 [0.06, 5.96] | 0.701 |
| `edit_without_search_v2` | In this round, the agent performs file edits without any prior contextual Read operation on the same file. | 15 | 1 | 47 | 1 | 0.31 [0.03, 3.23] | 0.386 |
| `more_edits_than_reads_v2` | In this round, the agent makes multiple edits without any successful reads. | 0 | 0 | 62 | 2 | 0.04 [0.00, 2.54] | 1.000 |
| `no_search_before_action_v2` | In this round, the agent takes action (Edit/Bash) without any search and encounters an error. | 16 | 1 | 46 | 1 | 0.34 [0.03, 3.52] | 0.427 |
| `write_without_read_v2` | If the agent writes to a file without sufficient context or understanding, the user is more likely to reject it. | 11 | 1 | 51 | 1 | 0.21 [0.02, 2.20] | 0.225 |
| `frequent_bash_commands_v2` | If the agent executes multiple Bash commands that result in errors within a single round, the user is more likely to reject it. | 2 | 0 | 60 | 2 | 0.21 [0.01, 5.73] | 0.793 |
| `edit_without_read_v2_v2` | In this round, the agent edits a file without having successfully Read it first, and there are no successful Write operations before the Edit. | 5 | 0 | 57 | 2 | 0.50 [0.02, 11.68] | 0.670 |
| `edit_without_search_v2_v2` | In this round, the agent performs file edits without any prior contextual Read or Write operation on the same file. | 23 | 1 | 39 | 1 | 0.58 [0.06, 5.96] | 0.701 |
| `more_edits_than_reads_v2_v2` | In this round, the agent makes multiple edits without any successful reads or context-establishing actions. | 3 | 0 | 59 | 2 | 0.30 [0.01, 7.64] | 0.746 |
| `no_search_before_action_v2_v2` | In this round, the agent takes action (Edit/Bash) without any search and encounters a critical error (e.g., command not found, file not found). | 2 | 0 | 60 | 2 | 0.21 [0.01, 5.73] | 0.793 |
| `write_without_read_v2_v2` | If the agent writes to a file without first successfully reading any related files or checking existing content, the user is more likely to reject it. | 0 | 0 | 62 | 2 | 0.04 [0.00, 2.54] | 1.000 |
