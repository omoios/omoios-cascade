from __future__ import annotations

import subprocess
from typing import Callable

from pydantic import BaseModel, Field


class ReconciliationReport(BaseModel):
    rounds: int = 0
    final_verdict: str = "pending"
    green_commit: str | None = None
    failures_found: list[str] = Field(default_factory=list)
    fixes_attempted: int = 0


def _collect_failures(stdout: str, stderr: str) -> list[str]:
    output = f"{stdout}\n{stderr}".strip()
    if not output:
        return ["unknown failure"]
    return [line.strip() for line in output.splitlines() if line.strip()]


def reconcile(
    repo_path: str,
    test_command: str,
    max_rounds: int = 3,
    spawn_fixer_fn: Callable[[list[str]], None] | None = None,
) -> ReconciliationReport:
    report = ReconciliationReport()

    for round_num in range(1, max_rounds + 1):
        result = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=repo_path,
        )
        report.rounds = round_num

        if result.returncode == 0:
            report.final_verdict = "pass"
            report.green_commit = f"green-{round_num}"
            return report

        failures = _collect_failures(result.stdout, result.stderr)
        report.failures_found.extend(failures)

        if spawn_fixer_fn is not None:
            spawn_fixer_fn(report.failures_found)
            report.fixes_attempted += 1

    report.final_verdict = "fail"
    return report
