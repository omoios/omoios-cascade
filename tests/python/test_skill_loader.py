from pathlib import Path

from harness.config_loader.skills import SkillLoader, discover_skills
from harness.models.skill import SkillDefinition

VALID_BODY = "A" * 60


def test_discover_skills_finds_skill_md_in_skills_directory(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills" / "lint"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: lint\ndescription: Lint checker\n---\n{VALID_BODY}",
        encoding="utf-8",
    )

    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].name == "lint"


def test_discover_skills_parses_yaml_frontmatter(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills" / "tester"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: test-skill\ndescription: testing helper\ntriggers: test, pytest\n---\n{VALID_BODY}",
        encoding="utf-8",
    )

    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].name == "test-skill"
    assert skills[0].description == "testing helper"
    assert skills[0].triggers == ["test", "pytest"]
    assert skills[0].content == VALID_BODY


def test_discover_skills_handles_missing_frontmatter(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills" / "plain"
    skill_dir.mkdir(parents=True)
    body = "No frontmatter content but long enough to pass fifty character validation check"
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    skills = discover_skills(tmp_path)

    # Without frontmatter there is no description, so SkillRegistry validation
    # rejects the skill.  Verify graceful handling (no crash, empty list).
    assert len(skills) == 0


def test_skill_loader_match_task_matches_trigger_keywords():
    loader = SkillLoader(
        [
            SkillDefinition(name="lint", description="Lint rules", triggers=["lint"], content=VALID_BODY),
            SkillDefinition(
                name="tests", description="Test rules", triggers=["pytest", "unit test"], content=VALID_BODY
            ),
        ]
    )

    matched = loader.match_task("Please run pytest and fix failures")

    assert [skill.name for skill in matched] == ["tests"]


def test_skill_loader_match_task_returns_empty_for_no_match():
    loader = SkillLoader(
        [SkillDefinition(name="lint", description="Lint rules", triggers=["lint"], content=VALID_BODY)]
    )

    matched = loader.match_task("refactor this module")

    assert matched == []


def test_skill_loader_get_skill_returns_by_name():
    skill = SkillDefinition(name="deploy", description="Deploy tool", triggers=["deploy"], content=VALID_BODY)
    loader = SkillLoader([skill])

    result = loader.get_skill("deploy")

    assert result == skill


def test_skill_loader_list_skills_returns_all_skills():
    skill_one = SkillDefinition(name="one", description="First skill", content=VALID_BODY)
    skill_two = SkillDefinition(name="two", description="Second skill", content=VALID_BODY)
    loader = SkillLoader([skill_one, skill_two])

    listed = loader.list_skills()

    assert {skill.name for skill in listed} == {"one", "two"}


def test_skill_definition_model():
    skill = SkillDefinition(
        name="format",
        description="Formatting helper",
        triggers=["format", "ruff"],
        content="Run formatter",
        source_path="/tmp/skills/format/SKILL.md",
    )

    assert skill.name == "format"
    assert skill.description == "Formatting helper"
    assert skill.triggers == ["format", "ruff"]
    assert skill.content == "Run formatter"
    assert skill.source_path.endswith("SKILL.md")
