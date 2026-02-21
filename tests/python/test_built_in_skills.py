from pathlib import Path

from harness.config_loader.skills import _parse_frontmatter, discover_skills


def test_built_in_skill_files_exist_and_have_expected_frontmatter():
    skills_root = Path(__file__).resolve().parents[2] / "src" / "harness" / "skills"
    expected = {
        "harness-conventions",
        "code-review",
        "test-writing",
        "git-workflow",
        "debugging",
    }

    for name in expected:
        skill_file = skills_root / name / "SKILL.md"
        assert skill_file.exists()
        raw = skill_file.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        assert meta.get("name") == name
        assert isinstance(meta.get("description", ""), str)
        assert meta.get("description", "").strip()
        assert isinstance(meta.get("triggers", []), list)
        assert len(body) >= 50
        words = len(body.split())
        assert 150 <= words <= 500


def test_discover_skills_includes_builtins_when_enabled(tmp_path):
    discovered = discover_skills(tmp_path, include_builtin=True)
    names = {skill.name for skill in discovered}

    assert "harness-conventions" in names
    assert "code-review" in names
    assert "test-writing" in names
    assert "git-workflow" in names
    assert "debugging" in names
