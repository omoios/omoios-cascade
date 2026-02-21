from pathlib import Path

from harness.config import HarnessConfig, LLMConfig
from harness.runner import HarnessRunner


def _prompt_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "harness" / "prompts" / filename


def test_prompt_files_exist():
    for filename in ["worker.md", "planner.md", "sub_planner.md", "watchdog.md"]:
        assert _prompt_path(filename).exists()


def test_prompt_files_contain_constraints_keywords():
    for filename in ["worker.md", "planner.md", "sub_planner.md", "watchdog.md"]:
        content = _prompt_path(filename).read_text(encoding="utf-8")
        assert "NEVER" in content
        assert "ALWAYS" in content


def test_runner_loads_prompt_files():
    runner = HarnessRunner(config=HarnessConfig(llm=LLMConfig(api_key="test-key")))

    assert "NEVER" in runner._prompt_texts["worker"]
    assert "ALWAYS" in runner._prompt_texts["planner"]
    assert "Sub-Planner" in runner._prompt_texts["sub_planner"]
    assert "Watchdog" in runner._prompt_texts["watchdog"]
