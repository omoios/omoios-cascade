#!/usr/bin/env python3
"""Headless stress test for the harness with MiniMax M2.5."""

import asyncio
import os
import subprocess
import sys

# Ensure .env is loaded
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)

from harness.config import HarnessConfig
from harness.runner import HarnessRunner


STRESS_REPO = "/tmp/harness-stress-repo"

INSTRUCTIONS = """\
Add a 'search' feature to the task tracker app.

1. In app/store.py, add a `search(self, keyword: str) -> list[Task]` method 
   that returns all tasks whose title contains the keyword (case-insensitive).
2. In tests/test_models.py, add a test `test_search_tasks` that:
   - Creates a TaskStore with 3 tasks: "Buy groceries", "Read book", "Buy gifts"  
   - Searches for "buy" and asserts it returns exactly 2 tasks
   - Searches for "read" and asserts it returns exactly 1 task
   - Searches for "xyz" and asserts it returns 0 tasks
3. Run `python -m pytest tests/ -v` to verify all tests pass.
"""


async def main():
    # Reset the stress repo
    subprocess.run(["git", "checkout", "--", "."], cwd=STRESS_REPO, check=True)
    print(f"Reset {STRESS_REPO} to clean state")

    config = HarnessConfig(
        repos=[STRESS_REPO],
        instructions=INSTRUCTIONS,
        test_command=f"cd {STRESS_REPO} && python -m pytest tests/ -v",
    )
    # Override agent limits for MiniMax
    config.agents.worker_timeout_seconds = 120
    config.workspace.cleanup_on_success = False

    runner = HarnessRunner(config)
    print("=" * 60)
    print("HEADLESS STRESS TEST - MiniMax M2.5")
    print("=" * 60)
    print(f"Model: {config.llm.model}")
    print(f"Base URL: {config.llm.base_url}")
    print(f"Worker token budget: {config.agents.worker_token_budget:,}")
    print(f"Worker timeout: {config.agents.worker_timeout_seconds}s")
    print(f"Repos: {config.repos}")
    print(f"Test command: {config.test_command}")
    print("=" * 60)
    print()

    result = await runner.run(INSTRUCTIONS)

    print()
    print("=" * 60)
    print("RESULT:")
    print("=" * 60)
    print(result[:2000] if result else "(empty)")
    print()

    # Verify final state
    proc = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-v"],
        cwd=STRESS_REPO,
        capture_output=True,
        text=True,
    )
    print("=" * 60)
    print(f"FINAL TEST RESULT: {'PASS' if proc.returncode == 0 else 'FAIL'}")
    print("=" * 60)
    print(proc.stdout[-1000:] if proc.stdout else "")
    if proc.returncode != 0:
        print("STDERR:", proc.stderr[-500:] if proc.stderr else "")

    # Show what changed
    diff = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=STRESS_REPO,
        capture_output=True,
        text=True,
    )
    print()
    print("FILES CHANGED:")
    print(diff.stdout or "(none)")

    return proc.returncode


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
