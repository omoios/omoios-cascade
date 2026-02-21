from pydantic import BaseModel, Field


class TaskSpec(BaseModel):
    objective: str = Field(description="What to accomplish")
    scope: list[str] = Field(default_factory=list, description="Files/modules in scope")
    non_goals: list[str] = Field(default_factory=list, description="What NOT to do")
    success_criteria: list[str] = Field(default_factory=list, description="How to verify completion")
    performance_bounds: dict = Field(default_factory=dict, description="Latency, memory, throughput limits")
    dependency_philosophy: dict = Field(default_factory=dict, description="Libraries allowed/forbidden")
    architectural_constraints: list[str] = Field(
        default_factory=list,
        description="Patterns to follow/avoid",
    )
    priority: str = Field(default="medium", description="high, medium, low")
    estimated_complexity: str = Field(default="medium", description="simple, medium, complex")
