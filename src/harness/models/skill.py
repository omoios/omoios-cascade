from pydantic import BaseModel, Field


class SkillDefinition(BaseModel):
    name: str = Field(description="Skill name")
    description: str = Field(default="", description="What the skill does")
    triggers: list[str] = Field(default_factory=list, description="Keywords that activate the skill")
    content: str = Field(default="", description="Full skill instructions text")
    source_path: str = Field(default="", description="Path to SKILL.md file")
