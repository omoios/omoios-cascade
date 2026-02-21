from pathlib import Path

from harness.config_loader.skills import SkillRegistry
from harness.models.skill import SkillDefinition


def test_skill_registry_register_prefers_higher_priority_source(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    workspace = tmp_path / "repo"
    project_skill_path = workspace / ".omp" / "skills" / "lint" / "SKILL.md"
    builtin_skill_path = tmp_path / "builtin" / "skills" / "lint" / "SKILL.md"

    registry = SkillRegistry(workspace_root=workspace)
    registry.register(
        SkillDefinition(
            name="lint",
            description="builtin",
            triggers=["lint"],
            content="x" * 80,
            source_path=str(builtin_skill_path),
        )
    )
    registry.register(
        SkillDefinition(
            name="lint",
            description="project",
            triggers=["lint"],
            content="y" * 80,
            source_path=str(project_skill_path),
        )
    )

    skill = registry.get_skill("lint")
    assert skill is not None
    assert skill.description == "project"


def test_skill_registry_match_task_uses_trigger_overlap_and_file_pattern(tmp_path):
    registry = SkillRegistry(workspace_root=tmp_path)
    registry.register(
        SkillDefinition(
            name="pytest-skill",
            description="testing helper for async pytest",
            triggers=["pytest"],
            content="a" * 80,
            source_path=str(tmp_path / "skills" / "pytest" / "SKILL.md"),
        )
    )
    registry.register(
        SkillDefinition(
            name="typescript-skill",
            description="TypeScript naming and import rules",
            triggers=["tsx"],
            file_patterns=["**/*.ts", "**/*.tsx", "src/*.ts"],
            content="b" * 80,
            source_path=str(tmp_path / "skills" / "ts" / "SKILL.md"),
        )
    )

    matched = registry.match_task("Run pytest for src/app.ts and update failing tests")

    assert [skill.name for skill in matched] == ["pytest-skill", "typescript-skill"]


def test_skill_registry_validate_skill_reports_required_field_errors(tmp_path):
    registry = SkillRegistry(workspace_root=tmp_path)
    errors = registry.validate_skill(
        SkillDefinition(
            name="",
            description="",
            triggers=["ok", ""],
            content="short",
            source_path=str(tmp_path / "skills" / "invalid" / "SKILL.md"),
        )
    )

    assert "Missing required field: name" in errors
    assert "Missing required field: description" in errors
    assert "Skill body content must be at least 50 characters" in errors
    assert "Triggers must be non-empty strings" in errors


def test_skill_registry_validate_skill_reports_duplicate_names_for_same_priority(tmp_path):
    registry = SkillRegistry(workspace_root=tmp_path)
    registry.register(
        SkillDefinition(
            name="duplicate",
            description="one",
            triggers=["dup"],
            content="a" * 80,
            source_path=str(tmp_path / "skills" / "dup-one" / "SKILL.md"),
        )
    )

    errors = registry.validate_skill(
        SkillDefinition(
            name="duplicate",
            description="two",
            triggers=["dup"],
            content="b" * 80,
            source_path=str(tmp_path / "skills" / "dup-two" / "SKILL.md"),
        )
    )

    assert errors == ["Duplicate skill name: duplicate"]
