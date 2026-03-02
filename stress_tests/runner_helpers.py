"""Shared runner utilities for stress tests.

Handles .env loading, config creation, result verification, and reporting.
"""

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=True)

from harness.config import HarnessConfig
from harness.runner import HarnessRunner


@dataclass
class TierResult:
    """Result of a single stress test tier run."""

    tier: int
    name: str
    passed: bool
    workers_spawned: int = 0
    files_changed: int = 0
    tests_passed: int = 0
    tests_total: int = 0
    wall_time_seconds: float = 0.0
    harness_output: str = ""
    error: str = ""


async def run_tier(
    tier: int,
    name: str,
    repo_path: str,
    instructions: str,
    test_command: str,
    worker_timeout: int = 180,
    expected_test_count: int | None = None,
    max_planner_turns: int = 80,
    max_planner_wall_time: int = 900,
) -> TierResult:
    """Run a single stress test tier and return results.

    Args:
        tier: Tier number (1-5)
        name: Human-readable tier name
        repo_path: Path to the target repo
        instructions: Harness instructions for this tier
        test_command: pytest command for verification
        worker_timeout: Per-worker timeout in seconds
        expected_test_count: If set, verify this many tests pass

    Returns:
        TierResult with pass/fail and metrics
    """
    result = TierResult(tier=tier, name=name, passed=False)

    print()
    print("=" * 70)
    print(f"  TIER {tier}: {name}")
    print("=" * 70)

    config = HarnessConfig(
        repos=[repo_path],
        instructions=instructions,
        test_command=test_command,
    )
    config.agents.worker_timeout_seconds = worker_timeout
    config.agents.max_planner_turns = max_planner_turns
    config.agents.max_planner_wall_time = max_planner_wall_time
    config.workspace.cleanup_on_success = False

    print(f"  Model: {config.llm.model}")
    print(f"  Repo: {repo_path}")
    print(f"  Worker timeout: {worker_timeout}s")
    print()

    start = time.monotonic()
    try:
        runner = HarnessRunner(config)
        harness_result = await runner.run(instructions)
        result.harness_output = harness_result[:3000] if harness_result else ""
    except Exception as e:
        result.error = str(e)
        result.wall_time_seconds = time.monotonic() - start
        print(f"  HARNESS ERROR: {e}")
        return result

    result.wall_time_seconds = time.monotonic() - start

    # Verify final state
    proc = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Parse test results
    for line in proc.stdout.splitlines():
        if "passed" in line:
            # e.g. "8 passed in 0.05s" or "7 passed, 1 failed"
            import re

            m = re.search(r"(\d+) passed", line)
            if m:
                result.tests_passed = int(m.group(1))
            m = re.search(r"(\d+) (?:passed|failed|error)", line)

    result.tests_total = result.tests_passed

    # Count files changed
    diff = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    changed_lines = [l for l in diff.stdout.strip().splitlines() if l.strip() and "|" in l]
    new_files = [l for l in untracked.stdout.strip().splitlines() if l.strip()]
    result.files_changed = len(changed_lines) + len(new_files)

    result.passed = proc.returncode == 0
    if expected_test_count and result.tests_passed < expected_test_count:
        result.passed = False
        result.error = f"Expected >= {expected_test_count} tests, got {result.tests_passed}"

    # Print summary
    status = "✅ PASS" if result.passed else "❌ FAIL"
    print()
    print(f"  {status}")
    print(f"  Tests: {result.tests_passed} passed")
    print(f"  Files changed: {result.files_changed}")
    print(f"  Wall time: {result.wall_time_seconds:.1f}s")
    if result.error:
        print(f"  Error: {result.error}")
    print()

    # Show test output
    stdout_tail = proc.stdout[-1500:] if proc.stdout else ""
    if stdout_tail:
        print(stdout_tail)
    if proc.returncode != 0 and proc.stderr:
        print("  STDERR:", proc.stderr[-500:])

    # Show file diff stat
    if diff.stdout:
        print("\n  FILES CHANGED:")
        print(diff.stdout)

    return result


def print_summary(results: list[TierResult]) -> int:
    """Print final summary of all tier results. Returns exit code."""
    print()
    print("=" * 70)
    print("  STRESS TEST SUMMARY")
    print("=" * 70)
    print()
    print(f"  {'Tier':<6} {'Name':<30} {'Status':<8} {'Tests':<8} {'Files':<7} {'Time':<8}")
    print(f"  {'─' * 6} {'─' * 30} {'─' * 8} {'─' * 8} {'─' * 7} {'─' * 8}")

    all_passed = True
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        if not r.passed:
            all_passed = False
        print(
            f"  {r.tier:<6} {r.name:<30} {status:<8} {r.tests_passed:<8} "
            f"{r.files_changed:<7} {r.wall_time_seconds:.1f}s"
        )

    print()
    overall = "ALL PASSED ✅" if all_passed else "SOME FAILED ❌"
    print(f"  Overall: {overall}")
    print("=" * 70)

    return 0 if all_passed else 1
