from __future__ import annotations

import asyncio
import re
from fnmatch import fnmatch
from pathlib import Path

from harness.events import EventBus, SkillValidationError
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
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in {"triggers", "file_patterns"}:
            meta[key] = [t.strip() for t in value.split(",") if t.strip()]
        else:
            meta[key] = value
    return meta, body


def _source_priority(source_path: str, workspace_root: Path) -> int:
    path = Path(source_path).resolve()
    home = Path.home().resolve()
    builtin_root = Path(__file__).resolve().parents[1] / "skills"

    project_dirs = [
        workspace_root / ".omp" / "skills",
        workspace_root / ".claude" / "skills",
        workspace_root / "skills",
    ]
    user_dirs = [
        home / ".omp" / "skills",
        home / ".claude" / "skills",
    ]

    for root in project_dirs:
        try:
            path.relative_to(root.resolve())
            return 3
        except ValueError:
            continue

    for root in user_dirs:
        try:
            path.relative_to(root.resolve())
            return 2
        except ValueError:
            continue

    try:
        path.relative_to(builtin_root.resolve())
        return 1
    except ValueError:
        return 0


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "to", "of", "in",
    "for", "on", "with", "at", "by", "from", "as", "into", "through",
    "during", "before", "after", "above", "below", "between", "out",
    "off", "up", "down", "and", "but", "or", "nor", "not", "so", "yet",
    "both", "either", "neither", "each", "every", "all", "any", "few",
    "more", "most", "other", "some", "such", "no", "only", "own", "same",
    "than", "too", "very", "just", "because", "if", "when", "where",
    "how", "what", "which", "who", "whom", "this", "that", "these",
    "those", "it", "its", "he", "she", "they", "them", "we", "you",
    "i", "me", "my", "your", "his", "her", "our", "their",
})


def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_\-]+", text.lower())) - _STOPWORDS


class SkillRegistry:
    def __init__(
        self,
        skills: list[SkillDefinition] | None = None,
        workspace_root: str | Path | None = None,
        event_bus: EventBus | None = None,
    ):
        self._workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._event_bus = event_bus
        self._skills: dict[str, SkillDefinition] = {}
        for skill in skills or []:
            self.register(skill)

    def _emit_validation_error(self, skill_name: str, errors: list[str]) -> None:
        if not self._event_bus:
            return
        event = SkillValidationError(
            agent_id="skill-registry",
            skill_name=skill_name,
            errors=errors,
            details={"skill_name": skill_name, "errors": errors},
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._event_bus.emit(event))
        except RuntimeError:
            asyncio.run(self._event_bus.emit(event))

    def validate_skill(self, skill: SkillDefinition) -> list[str]:
        errors: list[str] = []
        if not skill.name.strip():
            errors.append("Missing required field: name")
        if not skill.description.strip():
            errors.append("Missing required field: description")
        if len(skill.content.strip()) < 50:
            errors.append("Skill body content must be at least 50 characters")
        for trigger in skill.triggers:
            if not isinstance(trigger, str) or not trigger.strip():
                errors.append("Triggers must be non-empty strings")
                break
        existing = self._skills.get(skill.name)
        if existing and existing.source_path != skill.source_path:
            existing_priority = _source_priority(existing.source_path, self._workspace_root)
            incoming_priority = _source_priority(skill.source_path, self._workspace_root)
            if incoming_priority == existing_priority:
                errors.append(f"Duplicate skill name: {skill.name}")
        return errors

    def register(self, skill: SkillDefinition) -> None:
        validation_errors = self.validate_skill(skill)
        if validation_errors:
            self._emit_validation_error(skill.name or "(unnamed)", validation_errors)
            return

        existing = self._skills.get(skill.name)
        if not existing:
            self._skills[skill.name] = skill
            return

        existing_priority = _source_priority(existing.source_path, self._workspace_root)
        incoming_priority = _source_priority(skill.source_path, self._workspace_root)
        if incoming_priority > existing_priority:
            self._skills[skill.name] = skill

    def match_task(self, description: str) -> list[SkillDefinition]:
        description_lower = description.lower()
        description_words = _word_set(description)
        scored: list[tuple[int, int, SkillDefinition]] = []

        for skill in self._skills.values():
            trigger_exact = any(trigger.lower() in description_lower for trigger in skill.triggers)
            overlap = len(description_words.intersection(_word_set(skill.description)))

            file_score = 0
            for token in description.split():
                clean = token.strip(".,:;()[]{}<>\"'")
                if "/" in clean or "." in clean:
                    for pattern in skill.file_patterns:
                        if fnmatch(clean, pattern):
                            file_score = max(file_score, 1)

            if trigger_exact or overlap >= 2 or file_score > 0:
                score = (300 if trigger_exact else 0) + (100 * file_score) + overlap
                scored.append((score, _source_priority(skill.source_path, self._workspace_root), skill))

        scored.sort(key=lambda item: (item[0], item[1], item[2].name), reverse=True)
        return [item[2] for item in scored]

    def get_skill(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())


def discover_skills(
    workspace_root: str | Path,
    event_bus: EventBus | None = None,
    include_builtin: bool = False,
) -> list[SkillDefinition]:
    workspace_root = Path(workspace_root).resolve()
    home = Path.home()
    builtin_root = Path(__file__).resolve().parents[1] / "skills"

    search_dirs = [
        workspace_root / ".omp" / "skills",
        workspace_root / ".claude" / "skills",
        workspace_root / "skills",
        home / ".omp" / "skills",
        home / ".claude" / "skills",
    ]
    if include_builtin:
        search_dirs.append(builtin_root)

    registry = SkillRegistry(workspace_root=workspace_root, event_bus=event_bus)

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

            skill = SkillDefinition(
                name=meta.get("name", skill_dir.name),
                description=meta.get("description", ""),
                triggers=meta.get("triggers", []),
                file_patterns=meta.get("file_patterns", []),
                content=body,
                source_path=str(skill_md),
            )
            registry.register(skill)

    return registry.list_skills()


class SkillLoader:
    def __init__(
        self,
        skills: list[SkillDefinition] | None = None,
        workspace_root: str | Path | None = None,
        event_bus: EventBus | None = None,
    ):
        self._registry = SkillRegistry(skills=skills, workspace_root=workspace_root, event_bus=event_bus)

    def register(self, skill: SkillDefinition) -> None:
        self._registry.register(skill)

    def validate_skill(self, skill: SkillDefinition) -> list[str]:
        return self._registry.validate_skill(skill)

    def match_task(self, task_description: str) -> list[SkillDefinition]:
        return self._registry.match_task(task_description)

    def get_skill(self, name: str) -> SkillDefinition | None:
        return self._registry.get_skill(name)

    def list_skills(self) -> list[SkillDefinition]:
        return self._registry.list_skills()
