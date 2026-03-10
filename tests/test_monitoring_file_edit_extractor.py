from monitoring.file_edit_extractor import _extract_filepath_from_args, _infer_text_edits


def test_extracts_relative_project_paths_from_edit_tools(tmp_path):
    project = tmp_path / "project"
    src = project / "src"
    src.mkdir(parents=True)
    (src / "main.py").write_text("print('hi')\n")

    result = _extract_filepath_from_args(
        "Edit",
        {"file_path": str(src / "main.py")},
        str(project),
    )

    assert result == "src/main.py"


def test_rejects_shell_redirection_noise(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    for candidate in ("/dev/null", "&1", "="):
        result = _extract_filepath_from_args(
            "Bash",
            {"command": f"echo hi > {candidate}"},
            str(project),
        )
        assert result is None


def test_keeps_real_bash_write_targets_inside_project(tmp_path):
    project = tmp_path / "project"
    docs = project / "docs"
    docs.mkdir(parents=True)
    (docs / "plan.md").write_text("hello\n")

    result = _extract_filepath_from_args(
        "Bash",
        {"command": "cat <<'EOF' > docs/plan.md\nhello\nEOF"},
        str(project),
    )

    assert result == "docs/plan.md"


def test_rejects_bare_shell_words_that_are_not_project_files(tmp_path):
    project = tmp_path / "project"
    project.mkdir()

    result = _extract_filepath_from_args(
        "Bash",
        {"command": "echo ok > dash"},
        str(project),
    )

    assert result is None


def test_allows_common_root_filenames(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "Makefile").write_text("all:\n\ttrue\n")

    result = _extract_filepath_from_args(
        "Bash",
        {"command": "cp template.mk Makefile"},
        str(project),
    )

    assert result == "Makefile"


def test_rejects_absolute_paths_outside_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "elsewhere" / "note.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("hello\n")

    result = _extract_filepath_from_args(
        "Write",
        {"file_path": str(outside)},
        str(project),
    )

    assert result is None


def test_infers_cursor_summary_edits_from_change_messages(tmp_path):
    project = tmp_path / "project"
    (project / "src" / "contextEngineering").mkdir(parents=True)
    (project / "src" / "contextEngineering" / "curator.py").write_text("def curate():\n    pass\n")
    (project / "retro_config.yaml").write_text("playbook:\n  max_bullets: 20\n")
    (project / "README.md").write_text("# RetroCode\n")

    edits = _infer_text_edits(
        session_id="cursor-1",
        source="cursor",
        round_num=0,
        timestamp="",
        round_msgs=[{
            "role": "assistant",
            "content": (
                "Summary of changes:\n\n"
                "**Curator (`curator.py`)**:\n"
                "1. Removed auto-pruning.\n\n"
                "**Config and docs:**\n"
                "- `retro_config.yaml`: comment changed from old behavior.\n"
                "- `README.md`: Updated to describe curator-driven consolidation."
            ),
        }],
        working_dir=str(project),
    )

    assert [edit.file_path for edit in edits] == [
        "src/contextEngineering/curator.py",
        "retro_config.yaml",
        "README.md",
    ]


def test_infers_codex_summary_edits_from_markdown_links(tmp_path):
    project = tmp_path / "project"
    monitoring = project / "src" / "monitoring"
    monitoring.mkdir(parents=True)
    (monitoring / "dashboard.html").write_text("<html></html>\n")
    (monitoring / "file_edit_extractor.py").write_text("pass\n")
    (monitoring / "server.py").write_text("pass\n")

    edits = _infer_text_edits(
        session_id="codex-1",
        source="codex",
        round_num=2,
        timestamp="2026-03-09T05:40:28.923Z",
        round_msgs=[{
            "role": "assistant",
            "content": (
                f"The main rewrite is in [dashboard.html]({monitoring / 'dashboard.html'}). "
                f"I also tightened the backend signal in "
                f"[file_edit_extractor.py]({monitoring / 'file_edit_extractor.py'}) and "
                f"[server.py]({monitoring / 'server.py'})."
            ),
        }],
        working_dir=str(project),
    )

    assert [edit.file_path for edit in edits] == [
        "src/monitoring/dashboard.html",
        "src/monitoring/file_edit_extractor.py",
        "src/monitoring/server.py",
    ]


def test_does_not_treat_exploration_messages_as_edits(tmp_path):
    project = tmp_path / "project"
    (project / "src" / "monitoring").mkdir(parents=True)
    (project / "src" / "monitoring" / "server.py").write_text("pass\n")

    edits = _infer_text_edits(
        session_id="cursor-2",
        source="cursor",
        round_num=0,
        timestamp="",
        round_msgs=[{
            "role": "assistant",
            "content": "Let me look at that area in `server.py`.",
        }],
        working_dir=str(project),
    )

    assert edits == []


def test_infers_round_level_file_mentions_when_completion_happens_later(tmp_path):
    project = tmp_path / "project"
    monitoring = project / "src" / "monitoring"
    monitoring.mkdir(parents=True)
    (monitoring / "server.py").write_text("pass\n")

    edits = _infer_text_edits(
        session_id="cursor-3",
        source="cursor",
        round_num=2,
        timestamp="",
        round_msgs=[
            {
                "role": "assistant",
                "content": "The ugly display is coming from that area in `server.py`.",
            },
            {
                "role": "assistant",
                "content": "Done. Two changes: shortened the label and improved the layout.",
            },
        ],
        working_dir=str(project),
    )

    assert [edit.file_path for edit in edits] == ["src/monitoring/server.py"]


def test_ignores_build_copies_when_resolving_bare_names(tmp_path):
    project = tmp_path / "project"
    real = project / "src" / "contextEngineering"
    build = project / "build" / "lib" / "src" / "contextEngineering"
    real.mkdir(parents=True)
    build.mkdir(parents=True)
    (real / "curator.py").write_text("pass\n")
    (build / "curator.py").write_text("pass\n")
    (project / "README.md").write_text("# Demo\n")

    edits = _infer_text_edits(
        session_id="cursor-4",
        source="cursor",
        round_num=1,
        timestamp="",
        round_msgs=[{
            "role": "assistant",
            "content": (
                "Summary of changes:\n"
                "- `curator.py`: Removed auto-pruning.\n"
                "- `README.md`: Updated the docs."
            ),
        }],
        working_dir=str(project),
    )

    assert [edit.file_path for edit in edits] == [
        "src/contextEngineering/curator.py",
        "README.md",
    ]
