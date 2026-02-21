from __future__ import annotations

import asyncio
from typing import Any, Callable

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


async def reconcile(
    repo_path: str,
    test_command: str,
    max_rounds: int = 3,
    spawn_fixer_fn: Callable[[list[str]], Any] | None = None,
) -> ReconciliationReport:
    report = ReconciliationReport()

    for round_num in range(1, max_rounds + 1):
        proc = await asyncio.create_subprocess_shell(
            test_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_path,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        result_stdout = stdout_bytes.decode() if stdout_bytes else ""
        result_stderr = stderr_bytes.decode() if stderr_bytes else ""
        report.rounds = round_num

        if proc.returncode == 0:
            report.final_verdict = "pass"
            report.green_commit = f"green-{round_num}"
            return report

        failures = _collect_failures(result_stdout, result_stderr)
        report.failures_found.extend(failures)

        if spawn_fixer_fn is not None:
            result = spawn_fixer_fn(report.failures_found)
            if asyncio.iscoroutine(result):
                await result
            report.fixes_attempted += 1

    report.final_verdict = "fail"
    return report
