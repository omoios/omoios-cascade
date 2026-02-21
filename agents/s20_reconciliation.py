#!/usr/bin/env python3
"""
s20_reconciliation.py - Reconciliation Pass

Capstone session:
- Root planner enters RECONCILE after orchestration.
- ReconciliationPass runs full suite on canonical repo state.
- Each failure spawns targeted fixer workers.
- Loop is capped by max rounds.
- Final verdict is PASS or FAIL.

Reference: docs/reference/cursor-harness-notes.md section 4
Lifecycle: INIT -> DECOMPOSE -> ORCHESTRATE -> RECONCILE -> DONE
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

WORKDIR = Path.cwd().resolve()
TEAM_DIR = WORKDIR / ".team"
TASKS_DIR = WORKDIR / ".tasks"
REPORT_DIR = WORKDIR / ".reconcile"
GREEN_BRANCH_DIR = WORKDIR / ".green-branch"
WORKSPACES_ROOT = WORKDIR / ".workspaces"

DEFAULT_MAX_ROUNDS = 3
DEFAULT_FIXER_TIMEOUT_SECONDS = 300

IGNORE_DIRS: Set[str] = {
    ".git",
    ".team",
    ".tasks",
    ".reconcile",
    ".green-branch",
    ".workspaces",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".next",
    ".turbo",
}
IGNORE_SUFFIXES = (".pyc", ".pyo", ".swp", ".tmp")


class PlannerPhase(str, Enum):
    INIT = "INIT"
    DECOMPOSE = "DECOMPOSE"
    ORCHESTRATE = "ORCHESTRATE"
    RECONCILE = "RECONCILE"
    DONE = "DONE"


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FixerStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TestCommand:
    name: str
    command: str
    cwd: str


@dataclass
class TestCommandResult:
    name: str
    command: str
    cwd: str
    returncode: int
    output: str
    duration_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TestRunResult:
    started_at: float
    ended_at: float
    results: List[TestCommandResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(item.returncode == 0 for item in self.results)

    @property
    def failed(self) -> List[TestCommandResult]:
        return [item for item in self.results if item.returncode != 0]

    @property
    def duration_seconds(self) -> float:
        return max(self.ended_at - self.started_at, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "all_passed": self.all_passed,
            "results": [item.to_dict() for item in self.results],
        }


@dataclass
class Failure:
    failure_id: str
    kind: str
    signature: str
    source_command: str
    message: str
    related_path: Optional[str] = None
    line: Optional[int] = None
    output_excerpt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FixerTask:
    fixer_id: str
    failure: Failure
    task_id: Optional[int] = None
    workspace_path: Optional[str] = None
    status: FixerStatus = FixerStatus.PENDING
    started_at: float = 0.0
    ended_at: float = 0.0
    attempted_commands: List[str] = field(default_factory=list)
    output: str = ""

    @property
    def duration_seconds(self) -> float:
        if self.started_at <= 0 or self.ended_at <= 0:
            return 0.0
        return max(self.ended_at - self.started_at, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["duration_seconds"] = self.duration_seconds
        payload["failure"] = self.failure.to_dict()
        return payload


@dataclass
class GreenSnapshot:
    snapshot_id: str
    created_at: float
    source_root: str
    snapshot_path: str
    file_count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciliationRound:
    round_number: int
    started_at: float
    ended_at: float = 0.0
    test_run: Optional[TestRunResult] = None
    parsed_failures: List[Failure] = field(default_factory=list)
    spawned_fixers: List[FixerTask] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return max(self.ended_at - self.started_at, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "round_number": self.round_number,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "test_run": self.test_run.to_dict() if self.test_run else None,
            "parsed_failures": [item.to_dict() for item in self.parsed_failures],
            "spawned_fixers": [item.to_dict() for item in self.spawned_fixers],
            "notes": self.notes,
        }


@dataclass
class ReconciliationReport:
    report_id: str
    started_at: float
    ended_at: float = 0.0
    max_rounds: int = DEFAULT_MAX_ROUNDS
    rounds: List[ReconciliationRound] = field(default_factory=list)
    verdict: Verdict = Verdict.FAIL
    green_snapshot: Optional[GreenSnapshot] = None
    remaining_failures: List[Failure] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return max(self.ended_at - self.started_at, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "max_rounds": self.max_rounds,
            "verdict": self.verdict.value,
            "green_snapshot": self.green_snapshot.to_dict() if self.green_snapshot else None,
            "remaining_failures": [item.to_dict() for item in self.remaining_failures],
            "rounds": [item.to_dict() for item in self.rounds],
        }


class TaskBoard:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        values: List[int] = []
        for fp in self.root.glob("task_*.json"):
            try:
                values.append(int(fp.stem.split("_")[1]))
            except Exception:
                continue
        return max(values) if values else 0

    def _path(self, task_id: int) -> Path:
        return self.root / f"task_{task_id}.json"

    def _load(self, task_id: int) -> Dict[str, Any]:
        path = self._path(task_id)
        if not path.exists():
            raise ValueError(f"Task {task_id} not found")
        return json.loads(path.read_text())

    def _save(self, task: Dict[str, Any]) -> None:
        self._path(task["id"]).write_text(json.dumps(task, indent=2))

    def create(
        self,
        subject: str,
        description: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        task_type: str = "feature",
    ) -> Dict[str, Any]:
        with self.lock:
            task_id = self._next_id
            self._next_id += 1
            task = {
                "id": task_id,
                "subject": subject,
                "description": description,
                "status": "pending",
                "priority": priority.value,
                "task_type": task_type,
                "owner": "",
                "created_at": time.time(),
                "updated_at": time.time(),
                "notes": [],
            }
            self._save(task)
            return task

    def update_status(self, task_id: int, status: str) -> Dict[str, Any]:
        with self.lock:
            task = self._load(task_id)
            task["status"] = status
            task["updated_at"] = time.time()
            self._save(task)
            return task

    def assign_owner(self, task_id: int, owner: str) -> Dict[str, Any]:
        with self.lock:
            task = self._load(task_id)
            task["owner"] = owner
            task["updated_at"] = time.time()
            self._save(task)
            return task

    def add_note(self, task_id: int, note: str) -> Dict[str, Any]:
        with self.lock:
            task = self._load(task_id)
            task.setdefault("notes", []).append(note)
            task["updated_at"] = time.time()
            self._save(task)
            return task

    def list_tasks(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for fp in sorted(self.root.glob("task_*.json")):
            try:
                out.append(json.loads(fp.read_text()))
            except Exception:
                continue
        return out


class FailureParser:
    @staticmethod
    def _excerpt(text: str, max_len: int = 1200) -> str:
        compact = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
        return compact[:max_len]

    @staticmethod
    def _parse_pytest(result: TestCommandResult) -> List[Failure]:
        out: List[Failure] = []
        pattern = re.compile(r"FAILED\s+([^\s:]+)(?:::(\S+))?")
        for match in pattern.finditer(result.output):
            file_path = match.group(1)
            test_name = match.group(2) or "unknown_test"
            signature = f"pytest:{file_path}::{test_name}"
            out.append(
                Failure(
                    failure_id=f"f-{uuid.uuid4().hex[:10]}",
                    kind="pytest",
                    signature=signature,
                    source_command=result.name,
                    message=f"Pytest failure in {file_path}::{test_name}",
                    related_path=file_path,
                    output_excerpt=FailureParser._excerpt(result.output),
                )
            )
        return out

    @staticmethod
    def _parse_tsc(result: TestCommandResult) -> List[Failure]:
        out: List[Failure] = []
        pattern = re.compile(r"^([^\s][^:(]+)\((\d+),(\d+)\):\s+error\s+TS\d+:\s+(.+)$", re.MULTILINE)
        for match in pattern.finditer(result.output):
            file_path = match.group(1)
            line = int(match.group(2))
            msg = match.group(4)
            signature = f"tsc:{file_path}:{line}:{msg[:80]}"
            out.append(
                Failure(
                    failure_id=f"f-{uuid.uuid4().hex[:10]}",
                    kind="typescript",
                    signature=signature,
                    source_command=result.name,
                    message=f"TypeScript error at {file_path}:{line} - {msg}",
                    related_path=file_path,
                    line=line,
                    output_excerpt=FailureParser._excerpt(result.output),
                )
            )
        return out

    @staticmethod
    def _parse_traceback(result: TestCommandResult) -> List[Failure]:
        out: List[Failure] = []
        pattern = re.compile(r'File "([^"]+)", line (\d+)')
        for match in pattern.finditer(result.output):
            file_path = match.group(1)
            line = int(match.group(2))
            signature = f"traceback:{file_path}:{line}"
            out.append(
                Failure(
                    failure_id=f"f-{uuid.uuid4().hex[:10]}",
                    kind="traceback",
                    signature=signature,
                    source_command=result.name,
                    message=f"Traceback at {file_path}:{line}",
                    related_path=file_path,
                    line=line,
                    output_excerpt=FailureParser._excerpt(result.output),
                )
            )
        return out

    @staticmethod
    def _parse_generic(result: TestCommandResult) -> List[Failure]:
        lines = [line for line in result.output.splitlines() if line.strip()]
        summary = lines[-1] if lines else "Command failed"
        return [
            Failure(
                failure_id=f"f-{uuid.uuid4().hex[:10]}",
                kind="generic",
                signature=f"generic:{result.name}:{summary[:120]}",
                source_command=result.name,
                message=f"Command '{result.name}' failed: {summary[:300]}",
                output_excerpt=FailureParser._excerpt(result.output),
            )
        ]

    @staticmethod
    def parse(test_run: TestRunResult) -> List[Failure]:
        out: List[Failure] = []
        seen: Set[str] = set()

        for result in test_run.failed:
            parsed: List[Failure] = []

            if "vitest" in result.command or "pytest" in result.output.lower():
                parsed.extend(FailureParser._parse_pytest(result))
            if "tsc" in result.command:
                parsed.extend(FailureParser._parse_tsc(result))

            parsed.extend(FailureParser._parse_traceback(result))

            if not parsed:
                parsed.extend(FailureParser._parse_generic(result))

            for item in parsed:
                if item.signature in seen:
                    continue
                seen.add(item.signature)
                out.append(item)

        return out


class FixerWorker:
    def __init__(self, pass_owner: "ReconciliationPass", fixer: FixerTask):
        self.pass_owner = pass_owner
        self.fixer = fixer

    def run(self) -> None:
        self.fixer.status = FixerStatus.RUNNING
        self.fixer.started_at = time.time()
        try:
            workspace = self.pass_owner._prepare_fixer_workspace(self.fixer)
            self.fixer.workspace_path = str(workspace)

            commands = self.pass_owner._fixer_commands_for_failure(self.fixer.failure)
            self.fixer.attempted_commands.extend(commands)

            outputs: List[str] = []
            status = FixerStatus.SUCCEEDED
            for command in commands:
                proc = subprocess.run(
                    command,
                    shell=True,
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                out = (proc.stdout + "\n" + proc.stderr).strip()
                outputs.append(f"$ {command}\nreturncode={proc.returncode}\n{out}")
                if proc.returncode != 0:
                    status = FixerStatus.FAILED

            self.fixer.output = "\n\n".join(outputs)[:20000]
            self.fixer.status = status
        except subprocess.TimeoutExpired:
            self.fixer.status = FixerStatus.TIMED_OUT
            self.fixer.output = "Fixer timed out"
        except Exception as exc:
            self.fixer.status = FixerStatus.FAILED
            self.fixer.output = f"Fixer exception: {exc}"
        finally:
            self.fixer.ended_at = time.time()
            self.pass_owner._finalize_fixer_workspace(self.fixer)


class ReconciliationPass:
    def __init__(
        self,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        fixer_timeout_seconds: int = DEFAULT_FIXER_TIMEOUT_SECONDS,
    ):
        self.max_rounds = max(1, max_rounds)
        self.fixer_timeout_seconds = max(30, fixer_timeout_seconds)
        self.phase = PlannerPhase.INIT

        self.task_board = TaskBoard(TASKS_DIR)
        self.test_commands = self._detect_full_suite_commands()

        self.active_threads: Dict[str, threading.Thread] = {}
        self.active_fixers: Dict[str, FixerTask] = {}
        self.reports: List[ReconciliationReport] = []

        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        GREEN_BRANCH_DIR.mkdir(parents=True, exist_ok=True)
        WORKSPACES_ROOT.mkdir(parents=True, exist_ok=True)

    def _detect_full_suite_commands(self) -> List[TestCommand]:
        env_override = os.getenv("RECONCILE_TEST_COMMANDS", "").strip()
        if env_override:
            commands: List[TestCommand] = []
            for idx, raw in enumerate(env_override.split(";;"), start=1):
                command = raw.strip()
                if not command:
                    continue
                commands.append(TestCommand(name=f"env_cmd_{idx}", command=command, cwd=str(WORKDIR)))
            if commands:
                return commands

        commands: List[TestCommand] = []
        if (WORKDIR / "web" / "package.json").exists():
            commands.extend(
                [
                    TestCommand(name="web_vitest", command="npx vitest run", cwd=str(WORKDIR / "web")),
                    TestCommand(name="web_tsc", command="npx tsc --noEmit", cwd=str(WORKDIR / "web")),
                    TestCommand(name="web_build", command="npm run build", cwd=str(WORKDIR / "web")),
                ]
            )

        if (WORKDIR / "agents").exists():
            commands.append(TestCommand(name="python_compile_agents", command="python3 -m compileall -q agents", cwd=str(WORKDIR)))

        if not commands:
            commands.append(TestCommand(name="fallback_compile", command="python3 -m py_compile agents/s20_reconciliation.py", cwd=str(WORKDIR)))

        return commands

    def _run_one_command(self, command: TestCommand) -> TestCommandResult:
        started = time.time()
        try:
            proc = subprocess.run(
                command.command,
                shell=True,
                cwd=command.cwd,
                capture_output=True,
                text=True,
                timeout=900,
            )
            output = (proc.stdout + "\n" + proc.stderr).strip()
            return TestCommandResult(
                name=command.name,
                command=command.command,
                cwd=command.cwd,
                returncode=proc.returncode,
                output=output[:20000],
                duration_seconds=max(time.time() - started, 0.0),
            )
        except subprocess.TimeoutExpired as exc:
            return TestCommandResult(
                name=command.name,
                command=command.command,
                cwd=command.cwd,
                returncode=124,
                output=f"Timeout after {exc.timeout}s",
                duration_seconds=max(time.time() - started, 0.0),
            )
        except Exception as exc:
            return TestCommandResult(
                name=command.name,
                command=command.command,
                cwd=command.cwd,
                returncode=1,
                output=f"Command execution error: {exc}",
                duration_seconds=max(time.time() - started, 0.0),
            )

    def run_full_test_suite(self) -> TestRunResult:
        started = time.time()
        results = [self._run_one_command(command) for command in self.test_commands]
        ended = time.time()
        return TestRunResult(started_at=started, ended_at=ended, results=results)

    @staticmethod
    def _safe_rel_path(path: str) -> Optional[str]:
        if not path:
            return None
        candidate = Path(path)
        target = candidate.resolve() if candidate.is_absolute() else (WORKDIR / candidate).resolve()
        if not target.exists() or not target.is_file():
            return None
        if not target.is_relative_to(WORKDIR):
            return None
        return str(target.relative_to(WORKDIR))

    def _failure_file_excerpt(self, failure: Failure) -> str:
        rel = self._safe_rel_path(failure.related_path or "")
        if not rel:
            return ""
        path = (WORKDIR / rel).resolve()
        try:
            lines = path.read_text().splitlines()
        except Exception:
            return ""

        if not lines:
            return ""

        if failure.line is None:
            return "\n".join(lines[:120])

        center = max(1, failure.line)
        start = max(center - 20, 1)
        end = min(center + 20, len(lines))
        window = lines[start - 1 : end]
        numbered = [f"{i + start}: {txt}" for i, txt in enumerate(window)]
        return "\n".join(numbered)

    def _fixer_task_description(self, failure: Failure) -> str:
        excerpt = self._failure_file_excerpt(failure)
        return (
            f"Failure ID: {failure.failure_id}\n"
            f"Kind: {failure.kind}\n"
            f"Signature: {failure.signature}\n"
            f"Source Command: {failure.source_command}\n"
            f"Message: {failure.message}\n\n"
            "Output Excerpt:\n"
            f"{failure.output_excerpt[:3000]}\n\n"
            "Relevant File Excerpt:\n"
            f"{excerpt[:3000] if excerpt else '(none)'}\n\n"
            "Goal:\n"
            "- Apply the minimal targeted fix for this failure.\n"
            "- Keep unrelated files unchanged.\n"
            "- Run focused validation in fixer workspace.\n"
        )

    def _fixer_commands_for_failure(self, failure: Failure) -> List[str]:
        rel = self._safe_rel_path(failure.related_path or "")

        if failure.kind == "typescript" and rel:
            return ["npx tsc --noEmit"]

        if failure.kind == "pytest" and rel:
            if "web/" in rel:
                return ["npx vitest run"]
            return [f"python3 -m py_compile '{rel}'"]

        if failure.kind == "traceback" and rel:
            return [f"python3 -m py_compile '{rel}'"]

        if rel and rel.endswith(".py"):
            return [f"python3 -m py_compile '{rel}'"]

        return ["python3 -m compileall -q ."]

    def _prepare_fixer_workspace(self, fixer: FixerTask) -> Path:
        workspace_id = f"{fixer.fixer_id}-{int(time.time())}"
        target = (WORKSPACES_ROOT / workspace_id).resolve()
        if target.exists():
            shutil.rmtree(target)

        shutil.copytree(
            WORKDIR,
            target,
            dirs_exist_ok=False,
            ignore=self._ignore_filter,
        )
        return target

    @staticmethod
    def _ignore_filter(_dir: str, names: List[str]) -> Set[str]:
        ignored: Set[str] = set()
        for name in names:
            if name in IGNORE_DIRS:
                ignored.add(name)
                continue
            if any(name.endswith(suffix) for suffix in IGNORE_SUFFIXES):
                ignored.add(name)
        return ignored

    def _finalize_fixer_workspace(self, fixer: FixerTask) -> None:
        if not fixer.workspace_path:
            return
        path = Path(fixer.workspace_path)
        if path.exists():
            shutil.rmtree(path)

    def _spawn_fixer(self, failure: Failure) -> FixerTask:
        subject = f"Reconcile fix: {failure.message[:120]}"
        description = self._fixer_task_description(failure)
        task = self.task_board.create(subject=subject, description=description, priority=TaskPriority.CRITICAL, task_type="reconcile_fixer")

        fixer = FixerTask(
            fixer_id=f"fixer-{uuid.uuid4().hex[:10]}",
            failure=failure,
            task_id=int(task["id"]),
            status=FixerStatus.PENDING,
        )
        self.active_fixers[fixer.fixer_id] = fixer

        self.task_board.assign_owner(fixer.task_id or 0, fixer.fixer_id)
        self.task_board.update_status(fixer.task_id or 0, "in_progress")

        worker = FixerWorker(self, fixer)
        thread = threading.Thread(target=worker.run, daemon=True)
        self.active_threads[fixer.fixer_id] = thread
        thread.start()

        return fixer

    def _wait_for_fixers(self, timeout_seconds: int) -> None:
        deadline = time.time() + max(timeout_seconds, 1)
        while time.time() < deadline:
            alive = False
            for fixer_id, thread in list(self.active_threads.items()):
                if thread.is_alive():
                    alive = True
                    continue

                fixer = self.active_fixers.get(fixer_id)
                if fixer and fixer.task_id:
                    if fixer.status == FixerStatus.SUCCEEDED:
                        self.task_board.update_status(fixer.task_id, "completed")
                    else:
                        self.task_board.update_status(fixer.task_id, "failed")

            if not alive:
                return
            time.sleep(1)

    def _snapshot_green_branch(self) -> GreenSnapshot:
        snapshot_id = f"green-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        target = GREEN_BRANCH_DIR / snapshot_id
        if target.exists():
            shutil.rmtree(target)

        shutil.copytree(
            WORKDIR,
            target,
            dirs_exist_ok=False,
            ignore=self._ignore_filter,
        )

        files = 0
        for fp in target.rglob("*"):
            if fp.is_file():
                files += 1

        return GreenSnapshot(
            snapshot_id=snapshot_id,
            created_at=time.time(),
            source_root=str(WORKDIR),
            snapshot_path=str(target),
            file_count=files,
        )

    def _persist_report(self, report: ReconciliationReport) -> Path:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORT_DIR / f"reconcile_{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2))
        return path

    def _clear_active_fixers(self) -> None:
        self.active_threads = {}
        self.active_fixers = {}

    def run_reconciliation(self, max_rounds: Optional[int] = None) -> ReconciliationReport:
        rounds_limit = max(1, max_rounds if max_rounds is not None else self.max_rounds)
        report = ReconciliationReport(
            report_id=f"r-{uuid.uuid4().hex[:10]}",
            started_at=time.time(),
            max_rounds=rounds_limit,
            verdict=Verdict.FAIL,
        )

        self.phase = PlannerPhase.RECONCILE

        for round_number in range(1, rounds_limit + 1):
            self._clear_active_fixers()
            round_report = ReconciliationRound(round_number=round_number, started_at=time.time())
            report.rounds.append(round_report)

            test_run = self.run_full_test_suite()
            round_report.test_run = test_run

            if test_run.all_passed:
                round_report.notes.append("Full suite passed")
                round_report.ended_at = time.time()
                report.verdict = Verdict.PASS
                report.green_snapshot = self._snapshot_green_branch()
                report.ended_at = time.time()
                self.reports.append(report)
                self._persist_report(report)
                self.phase = PlannerPhase.DONE
                return report

            failures = FailureParser.parse(test_run)
            round_report.parsed_failures = failures

            if not failures:
                round_report.notes.append("Suite failed but parser found no discrete failures")
                round_report.ended_at = time.time()
                report.remaining_failures = []
                break

            spawned = [self._spawn_fixer(item) for item in failures]
            round_report.spawned_fixers = spawned
            round_report.notes.append(f"Spawned {len(spawned)} targeted fixers")

            self._wait_for_fixers(timeout_seconds=self.fixer_timeout_seconds)

            succeeded = len([item for item in spawned if item.status == FixerStatus.SUCCEEDED])
            failed = len([item for item in spawned if item.status in (FixerStatus.FAILED, FixerStatus.TIMED_OUT)])
            round_report.notes.append(f"Fixers succeeded={succeeded} failed={failed}")
            round_report.ended_at = time.time()

        final_test = self.run_full_test_suite()
        report.remaining_failures = FailureParser.parse(final_test)
        report.verdict = Verdict.FAIL
        report.ended_at = time.time()

        self.reports.append(report)
        self._persist_report(report)
        self.phase = PlannerPhase.DONE
        return report

    def latest_report(self) -> Optional[ReconciliationReport]:
        if not self.reports:
            return None
        return self.reports[-1]

    def round_summary(self, report: Optional[ReconciliationReport] = None) -> str:
        target = report or self.latest_report()
        if not target:
            return "No reconciliation reports"

        lines: List[str] = []
        lines.append(
            f"report={target.report_id} verdict={target.verdict.value} rounds={len(target.rounds)} duration={target.duration_seconds:.2f}s"
        )
        for item in target.rounds:
            failures = len(item.parsed_failures)
            fixers = len(item.spawned_fixers)
            failed_commands = len(item.test_run.failed) if item.test_run else 0
            lines.append(
                f"- round {item.round_number}: cmd_failures={failed_commands} parsed_failures={failures} spawned_fixers={fixers} duration={item.duration_seconds:.2f}s"
            )
        if target.green_snapshot:
            lines.append(f"green_snapshot={target.green_snapshot.snapshot_path}")
        if target.remaining_failures:
            lines.append(f"remaining_failures={len(target.remaining_failures)}")
        return "\n".join(lines)


RECONCILIATION = ReconciliationPass()


def _print_task_board() -> None:
    tasks = RECONCILIATION.task_board.list_tasks()
    if not tasks:
        print("No tasks")
        return
    for task in tasks[-40:]:
        print(
            f"- #{task.get('id')} [{task.get('status')}] ({task.get('priority')}) "
            f"{task.get('subject', '')} owner={task.get('owner') or '(none)'}"
        )


def _print_latest_report() -> None:
    report = RECONCILIATION.latest_report()
    if not report:
        print("No reconciliation reports")
        return
    print(json.dumps(report.to_dict(), indent=2))


def _run_reconcile(rounds: Optional[int]) -> None:
    report = RECONCILIATION.run_reconciliation(max_rounds=rounds)
    print(RECONCILIATION.round_summary(report))


def _demo() -> None:
    report = RECONCILIATION.run_reconciliation()
    print(json.dumps({
        "report_id": report.report_id,
        "verdict": report.verdict.value,
        "rounds": len(report.rounds),
        "green_snapshot": report.green_snapshot.to_dict() if report.green_snapshot else None,
        "remaining_failures": [item.to_dict() for item in report.remaining_failures],
    }, indent=2))


if __name__ == "__main__":
    print("s20 reconciliation pass")
    print("Commands: /phase /reconcile [n] /report /summary /tasks /demo /q")

    while True:
        try:
            query = input("\033[36ms20 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        q = query.strip()
        if q.lower() in ("q", "exit", "/q", ""):
            break

        if q == "/phase":
            print(f"planner_phase={RECONCILIATION.phase.value}")
            continue

        if q.startswith("/reconcile"):
            parts = q.split(" ", 1)
            rounds: Optional[int] = None
            if len(parts) == 2 and parts[1].strip().isdigit():
                rounds = int(parts[1].strip())
            _run_reconcile(rounds)
            continue

        if q == "/report":
            _print_latest_report()
            continue

        if q == "/summary":
            print(RECONCILIATION.round_summary())
            continue

        if q == "/tasks":
            _print_task_board()
            continue

        if q == "/demo":
            _demo()
            continue

        print("Unknown command")
