from __future__ import annotations

from pathlib import Path

from harness.models.skill import SkillDefinition


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content
    end = content.find("---", 3)
    if end == -1:
        return {}, content
    frontmatter_text = content[3:end].strip()
    body = content[end + 3 :].strip()
    meta: dict = {}
    for line in frontmatter_text.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            value = value.strip().strip('"').strip("'")
            if key.strip() == "triggers":
                meta[key.strip()] = [t.strip() for t in value.split(",") if t.strip()]
            else:
                meta[key.strip()] = value
    return meta, body


def discover_skills(workspace_root: str | Path) -> list[SkillDefinition]:
    workspace_root = Path(workspace_root).resolve()
    home = Path.home()

    search_dirs = [
        workspace_root / ".omp" / "skills",
        workspace_root / ".claude" / "skills",
        workspace_root / "skills",
        home / ".omp" / "skills",
        home / ".claude" / "skills",
    ]

    skills: list[SkillDefinition] = []
    seen_names: set[str] = set()

    for skills_dir in search_dirs:
        if not skills_dir.is_dir():
            continue
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.is_file():
                continue

            content = skill_md.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(content)

            name = meta.get("name", skill_dir.name)
            if name in seen_names:
                continue
            seen_names.add(name)

            skills.append(
                SkillDefinition(
                    name=name,
                    description=meta.get("description", ""),
                    triggers=meta.get("triggers", []),
                    content=body,
                    source_path=str(skill_md),
                )
            )

    return skills


class SkillLoader:
    def __init__(self, skills: list[SkillDefinition] | None = None):
        self._skills = {s.name: s for s in (skills or [])}

    def match_task(self, task_description: str) -> list[SkillDefinition]:
        matched: list[SkillDefinition] = []
        desc_lower = task_description.lower()
        for skill in self._skills.values():
            for trigger in skill.triggers:
                if trigger.lower() in desc_lower:
                    matched.append(skill)
                    break
        return matched

    def get_skill(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())
