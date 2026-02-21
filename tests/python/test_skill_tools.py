from pathlib import Path

from harness.tools.skill_tools import create_skill_handler, load_skill_handler


async def test_create_skill_handler_writes_project_skill(tmp_path):
    result = await create_skill_handler(
        {
            "name": "local-skill",
            "description": "Local helper",
            "triggers": ["local", "helper"],
            "content": "Use this local skill to apply repo conventions and verify outputs before handoff.",
        },
        workspace_path=str(tmp_path),
    )

    assert result["status"] == "created"
    created_path = Path(result["path"])
    assert created_path.exists()
    text = created_path.read_text(encoding="utf-8")
    assert "name: local-skill" in text
    assert "description: Local helper" in text
    assert "triggers: local, helper" in text


async def test_create_skill_handler_rejects_invalid_payload(tmp_path):
    result = await create_skill_handler(
        {
            "name": "",
            "description": "",
            "content": "",
            "triggers": ["", 1],
        },
        workspace_path=str(tmp_path),
    )

    assert "error" in result
    assert "name must be a non-empty string" in result["error"]


async def test_load_skill_handler_returns_already_loaded_for_duplicate(tmp_path):
    skill_dir = tmp_path / ".omp" / "skills" / "helper"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: helper\ndescription: helper skill\ntriggers: helper\n---\n"
        "This helper skill content is long enough for validation checks in tests.",
        encoding="utf-8",
    )

    loaded = set()
    first = await load_skill_handler({"name": "helper"}, workspace_path=str(tmp_path), loaded_skills=loaded)
    second = await load_skill_handler({"name": "helper"}, workspace_path=str(tmp_path), loaded_skills=loaded)

    assert first["status"] == "loaded"
    assert "content" in first
    assert second == {"status": "already_loaded", "name": "helper"}
