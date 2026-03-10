from monitoring.depgraph import DependencyGraph
from monitoring.server import _build_action_items, _file_guidance, file_tier


def build_project(tmp_path):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "tests").mkdir(parents=True)

    (project / "src" / "__init__.py").write_text("")
    (project / "src" / "core.py").write_text("VALUE = 1\n")
    (project / "src" / "feature_a.py").write_text("from src.core import VALUE\nprint(VALUE)\n")
    (project / "src" / "feature_b.py").write_text("from src.core import VALUE\nprint(VALUE)\n")
    (project / "src" / "shared.py").write_text("def shared():\n    return 1\n")
    (project / "src" / "consumer.py").write_text("from src.shared import shared\nprint(shared())\n")
    (project / "tests" / "test_feature_a.py").write_text("def test_feature_a():\n    assert True\n")

    graph = DependencyGraph(str(project))
    graph.build()
    return project, graph


def test_file_guidance_flags_quiet_core(tmp_path):
    project, graph = build_project(tmp_path)

    guidance = _file_guidance("src/core.py", graph, edit_count=1, working_dir=str(project))

    signal_ids = {signal["id"] for signal in guidance["signals"]}
    assert "quiet-core" in signal_ids
    assert guidance["recommended_actions"]


def test_file_guidance_flags_missing_test_for_shared_code(tmp_path):
    project, graph = build_project(tmp_path)

    tier = file_tier(graph.blast_ratio("src/shared.py"))
    assert tier <= 3

    guidance = _file_guidance("src/shared.py", graph, edit_count=1, working_dir=str(project))

    signal_ids = {signal["id"] for signal in guidance["signals"]}
    assert "test-gap" in signal_ids
    assert guidance["has_obvious_test"] is False
    assert guidance["test_paths"]


def test_build_action_items_prioritizes_quiet_core_and_test_gap(tmp_path):
    project, graph = build_project(tmp_path)
    file_profiles = []
    for path, edit_count in [("src/core.py", 1), ("src/shared.py", 1)]:
        ratio = graph.blast_ratio(path)
        file_profiles.append({
            "path": path,
            "tier": file_tier(ratio),
            "blast_radius": graph.blast_radius(path),
            "blast_ratio": ratio,
            "edit_count": edit_count,
            "risk_score": ratio,
            "impact_label": f"{graph.blast_radius(path)} files",
            "guidance": _file_guidance(path, graph, edit_count, str(project)),
        })

    actions, counts = _build_action_items(file_profiles, sessions=[])

    action_types = {action["type"] for action in actions}
    assert "quiet-core" in action_types
    assert "test-gap" in action_types
    assert counts["quiet_core"] == 1
    assert counts["test_gap"] == 2
