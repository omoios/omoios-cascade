from __future__ import annotations

from pathlib import Path
from typing import Any

from harness.config_loader.skills import SkillRegistry, discover_skills
from harness.events import EventBus, SkillCreated
from harness.models.skill import SkillDefinition


def _validate_create_input(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload.get("name", ""), str) or not payload["name"].strip():
        errors.append("name must be a non-empty string")
    if not isinstance(payload.get("description", ""), str) or not payload["description"].strip():
        errors.append("description must be a non-empty string")
    if not isinstance(payload.get("content", ""), str) or not payload["content"].strip():
        errors.append("content must be a non-empty string")
    triggers = payload.get("triggers", [])
    if triggers is not None:
        if not isinstance(triggers, list):
            errors.append("triggers must be a list of strings")
        elif any(not isinstance(trigger, str) or not trigger.strip() for trigger in triggers):
            errors.append("triggers must only contain non-empty strings")
    return errors


async def create_skill_handler(
    input: dict,
    workspace_path: str,
    event_bus: EventBus | None = None,
) -> dict[str, Any]:
    payload = dict(input)
    errors = _validate_create_input(payload)
    if errors:
        return {"error": "; ".join(errors)}

    skill_name = payload["name"].strip()
    target = Path(workspace_path) / ".omp" / "skills" / skill_name / "SKILL.md"
    triggers = payload.get("triggers", []) or []

    skills = discover_skills(workspace_path, event_bus=event_bus, include_builtin=True)
    registry = SkillRegistry(skills=skills, workspace_root=workspace_path, event_bus=event_bus)
    candidate = SkillDefinition(
        name=skill_name,
        description=payload["description"].strip(),
        triggers=[trigger.strip() for trigger in triggers],
        content=payload["content"].strip(),
        source_path=str(target),
    )
    validation_errors = registry.validate_skill(candidate)
    if validation_errors:
        return {"error": "; ".join(validation_errors)}

    target.parent.mkdir(parents=True, exist_ok=True)
    frontmatter_lines = [
        "---",
        f"name: {candidate.name}",
        f"description: {candidate.description}",
        f"triggers: {', '.join(candidate.triggers)}",
        "---",
        "",
        candidate.content,
        "",
    ]
    target.write_text("\n".join(frontmatter_lines), encoding="utf-8")

    if event_bus:
        await event_bus.emit(
            SkillCreated(
                agent_id="skill-tools",
                skill_name=candidate.name,
                path=str(target),
                details={"skill_name": candidate.name, "path": str(target)},
            )
        )

    return {"status": "created", "path": str(target)}


async def load_skill_handler(
    input: dict,
    workspace_path: str,
    loaded_skills: set[str] | None = None,
    registry: SkillRegistry | None = None,
) -> dict[str, Any]:
    name = str(input.get("name", "")).strip()
    if not name:
        return {"error": "name is required"}

    injected = loaded_skills if loaded_skills is not None else set()
    if name in injected:
        return {"status": "already_loaded", "name": name}

    active_registry = registry
    if active_registry is None:
        active_registry = SkillRegistry(
            skills=discover_skills(workspace_path, include_builtin=True),
            workspace_root=workspace_path,
        )

    skill = active_registry.get_skill(name)
    if not skill:
        return {"error": f"Skill not found: {name}"}

    injected.add(name)
    return {"status": "loaded", "name": skill.name, "content": skill.content}
