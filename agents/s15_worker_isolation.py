#!/usr/bin/env python3
"""
s15_worker_isolation.py - Worker Isolation (Per-Worker Workspaces)

Session concept:
- Each worker gets a private copy of the repository.
- Worker tools operate only within that private workspace.
- Handoff diffs are computed against canonical repo on submit.
- Workspace is cleaned up after worker completion.

Non-goal:
- No merge/reconciliation logic (reserved for s16).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd().resolve()
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-5-20250929")
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
SCRATCHPAD_DIR = WORKDIR / ".scratchpad"
WORKSPACES_ROOT = WORKDIR / ".workspaces"

POLL_INTERVAL = 3
MAX_WORKER_TURNS = 40
MAX_INLINE_OUTPUT = 50000
MAX_SCRATCHPAD_CHARS = 8000

IGNORE_DIRS: Set[str] = {
    ".git",
    ".workspaces",
    ".team",
    ".transcripts",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".next",
    ".turbo",
}
IGNORE_SUFFIXES = (".pyc", ".pyo", ".swp", ".tmp")

VALID_MSG_TYPES = {"message", "broadcast", "handoff"}

PLANNER_SYSTEM = (
    f"You are a PLANNER at {WORKDIR}. "
    "You decompose and delegate only. You NEVER write code. "
    "Use isolated workers for implementation."
)

WORKER_SYSTEM_TEMPLATE = (
    "You are WORKER '{name}' on planner '{planner}'. "
    "Execute one task inside your private workspace only. "
    "Do NOT decompose or spawn. Submit handoff when done."
)


class Role(str, Enum):
    PLANNER = "planner"
    WORKER = "worker"


class HandoffStatus(str, Enum):
    SUCCESS = "Success"
    PARTIAL_FAILURE = "PartialFailure"
    FAILED = "Failed"
    BLOCKED = "Blocked"


@dataclass
class HandoffMetrics:
    wall_time: float = 0.0
    tokens_used: int = 0
    attempts: int = 0
    files_modified: int = 0


@dataclass
class Handoff:
    agent_id: str
    task_id: str
    status: HandoffStatus
    diff: Dict[str, Dict[str, str]] = field(default_factory=dict)
    narrative: str = ""
    artifacts: List[str] = field(default_factory=list)
    metrics: HandoffMetrics = field(default_factory=HandoffMetrics)
    workspace_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        out["status"] = self.status.value
        return out


@dataclass
class WorkerRuntime:
    worker: str
    task_id: str = "none"
    task_started_at: float = field(default_factory=time.time)
    attempts: int = 0
    turns: int = 0
    tokens_used: int = 0
    errors: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    last_text: str = ""
    handoff_submitted: bool = False
    workspace_path: str = ""
    workspace_cleaned: bool = False


class ScratchpadManager:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def read(self, name: str) -> str:
        path = self._path(name)
        if not path.exists():
            return ""
        return path.read_text()[:MAX_SCRATCHPAD_CHARS]

    def rewrite(self, name: str, content: str) -> str:
        text = content[:MAX_SCRATCHPAD_CHARS]
        path = self._path(name)
        path.write_text(text)
        return f"Scratchpad rewritten: {path} ({len(text)} chars)"


class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.dir / f"{name}.jsonl"

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {sorted(VALID_MSG_TYPES)}"

        payload: Dict[str, Any] = {
            "type": msg_type,
            "from": sender,
            "to": to,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            payload.update(extra)

        with open(self._path(to), "a") as f:
            f.write(json.dumps(payload) + "\n")

        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> List[Dict[str, Any]]:
        path = self._path(name)
        if not path.exists():
            return []
        raw = path.read_text().strip()
        if not raw:
            path.write_text("")
            return []

        items: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            if line.strip():
                items.append(json.loads(line))

        path.write_text("")
        return items

    def count_pending(self, name: str) -> int:
        path = self._path(name)
        if not path.exists():
            return 0
        raw = path.read_text().strip()
        if not raw:
            return 0
        return len([ln for ln in raw.splitlines() if ln.strip()])


class WorkerWorkspace:
    """Per-worker copy-on-write workspace at .workspaces/{worker_id}"""

    def __init__(self, worker_id: str, canonical_root: Path, workspace_root: Path):
        self.worker_id = worker_id
        self.canonical_root = canonical_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.path = (self.workspace_root / worker_id).resolve()

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

    def create(self) -> Path:
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            shutil.rmtree(self.path)
        shutil.copytree(
            self.canonical_root,
            self.path,
            dirs_exist_ok=False,
            ignore=self._ignore_filter,
        )
        return self.path

    def cleanup(self) -> None:
        if self.path.exists():
            shutil.rmtree(self.path)

    def _resolve_relative(self, rel_path: str) -> Path:
        if not rel_path.strip():
            raise ValueError("Path is empty")
        candidate = Path(rel_path)
        if candidate.is_absolute():
            raise ValueError("Absolute paths are not allowed")
        resolved = (self.path / candidate).resolve()
        if not resolved.is_relative_to(self.path):
            raise ValueError(f"Path escapes worker workspace: {rel_path}")
        return resolved

    def read_file(self, rel_path: str, limit: Optional[int] = None) -> str:
        fp = self._resolve_relative(rel_path)
        if not fp.exists() or not fp.is_file():
            raise FileNotFoundError(f"File not found: {rel_path}")
        lines = fp.read_text().splitlines()
        if limit is not None and limit > 0 and len(lines) > limit:
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)

    def write_file(self, rel_path: str, content: str) -> None:
        fp = self._resolve_relative(rel_path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)

    def edit_file(self, rel_path: str, old_text: str, new_text: str) -> None:
        fp = self._resolve_relative(rel_path)
        if not fp.exists() or not fp.is_file():
            raise FileNotFoundError(f"File not found: {rel_path}")
        before = fp.read_text()
        if old_text not in before:
            raise ValueError(f"Text not found in {rel_path}")
        fp.write_text(before.replace(old_text, new_text, 1))

    def run_bash(self, command: str, timeout: int = 120) -> str:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (proc.stdout + proc.stderr).strip()
        return out if out else "(no output)"

    def _iter_text_files(self, root: Path) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for fp in root.rglob("*"):
            if not fp.is_file():
                continue
            rel = fp.relative_to(root)
            if any(part in IGNORE_DIRS for part in rel.parts):
                continue
            rel_str = str(rel)
            if any(rel_str.endswith(suffix) for suffix in IGNORE_SUFFIXES):
                continue
            try:
                out[rel_str] = fp.read_text()
            except Exception:
                out[rel_str] = "<binary-or-unreadable>"
        return out

    def compute_diff_against_canonical(self) -> Dict[str, Dict[str, str]]:
        canonical = self._iter_text_files(self.canonical_root)
        workspace = self._iter_text_files(self.path)
        paths = sorted(set(canonical.keys()) | set(workspace.keys()))

        diff: Dict[str, Dict[str, str]] = {}
        for rel_path in paths:
            before = canonical.get(rel_path, "")
            after = workspace.get(rel_path, "")
            if before == after:
                continue
            diff[rel_path] = {"before": before, "after": after}
        return diff


BUS = MessageBus(INBOX_DIR)
SCRATCHPADS = ScratchpadManager(SCRATCHPAD_DIR)
HANDOFFS: List[Handoff] = []


class PlannerWorkerIsolationHarness:
    def __init__(self, planner_name: str = "planner"):
        self.planner_name = planner_name
        self.workers: Dict[str, Dict[str, Any]] = {}
        self.worker_threads: Dict[str, threading.Thread] = {}
        self.worker_runtime: Dict[str, WorkerRuntime] = {}
        self.worker_workspaces: Dict[str, WorkerWorkspace] = {}
        self._bootstrap_planner_scratchpad()

    def _bootstrap_planner_scratchpad(self):
        existing = SCRATCHPADS.read(self.planner_name)
        if existing:
            return
        SCRATCHPADS.rewrite(
            self.planner_name,
            (
                f"# Planner Scratchpad ({self.planner_name})\n\n"
                "## Role Constraint\n"
                "- I NEVER write code. I decompose and delegate only.\n\n"
                "## Isolation Constraint\n"
                "- Each worker runs in .workspaces/{worker_id}.\n"
                "- Worker operations are workspace-local only.\n"
                "- Handoff diff is against canonical repo.\n"
            ),
        )

    def _runtime(self, worker: str) -> WorkerRuntime:
        if worker not in self.worker_runtime:
            self.worker_runtime[worker] = WorkerRuntime(worker=worker)
        return self.worker_runtime[worker]

    def _workspace(self, worker: str) -> WorkerWorkspace:
        if worker not in self.worker_workspaces:
            self.worker_workspaces[worker] = WorkerWorkspace(worker, WORKDIR, WORKSPACES_ROOT)
        return self.worker_workspaces[worker]

    def _set_worker_status(self, name: str, status: str):
        meta = self.workers.get(name)
        if meta:
            meta["status"] = status

    def _record_error(self, worker: str, message: str):
        self._runtime(worker).errors.append(message)

    def _record_artifact(self, worker: str, path: str):
        self._runtime(worker).artifacts.append(path)

    def _next_worker_name(self) -> str:
        n = len(self.workers) + 1
        while f"worker-{n}" in self.workers:
            n += 1
        return f"worker-{n}"

    def _dedupe(self, items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out

    def _status_from_string(self, raw: Optional[str]) -> Optional[HandoffStatus]:
        if not raw:
            return None
        for status in HandoffStatus:
            if status.value == raw.strip():
                return status
        return None

    def _resolve_handoff_status(
        self,
        worker: str,
        requested: Optional[HandoffStatus],
        diff_count: int,
    ) -> HandoffStatus:
        if requested:
            return requested
        rt = self._runtime(worker)
        if not rt.errors:
            return HandoffStatus.SUCCESS
        if rt.errors and diff_count > 0:
            return HandoffStatus.PARTIAL_FAILURE
        lower = "\n".join(rt.errors).lower()
        if any(k in lower for k in ("blocked", "permission", "not found", "escape")):
            return HandoffStatus.BLOCKED
        return HandoffStatus.FAILED

    def _compose_handoff_narrative(self, worker: str, handoff: Handoff, final_text: str) -> str:
        rt = self._runtime(worker)
        payload = {
            "worker": worker,
            "task_id": handoff.task_id,
            "status": handoff.status.value,
            "workspace_path": handoff.workspace_path,
            "files_modified": handoff.metrics.files_modified,
            "artifacts": handoff.artifacts,
            "errors": rt.errors[-5:],
            "scratchpad": SCRATCHPADS.read(worker),
            "assistant_final_text": final_text,
            "diff_files": list(handoff.diff.keys()),
        }

        try:
            response = client.messages.create(
                model=MODEL,
                system=(
                    "Write concise worker handoff narrative for planner. "
                    "Include what changed, what did not, risks, and one next step. "
                    "Keep <=10 lines plain text."
                ),
                messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
                max_tokens=500,
            )
            rt.tokens_used += getattr(response.usage, "input_tokens", 0)
            rt.tokens_used += getattr(response.usage, "output_tokens", 0)
            text = "\n".join(
                blk.text for blk in response.content if getattr(blk, "type", None) == "text"
            ).strip()
            if text:
                return text
        except Exception as e:
            self._record_error(worker, f"narrative_generation: {e}")

        changed = ", ".join(handoff.diff.keys()) if handoff.diff else "no files"
        fallback = [
            f"Worker {worker} completed task {handoff.task_id} with status {handoff.status.value}.",
            f"Workspace: {handoff.workspace_path or '(unknown)'}.",
            f"Changed: {changed}.",
        ]
        if rt.errors:
            fallback.append(f"Latest error: {rt.errors[-1]}")
        if final_text:
            fallback.append(f"Final output: {final_text[:240]}")
        fallback.append("Next step: planner reviews canonical diff and delegates follow-up.")
        return "\n".join(fallback)

    def _build_handoff(
        self,
        worker: str,
        requested_status: Optional[HandoffStatus],
        task_id_override: Optional[str],
        narrative_override: Optional[str],
        extra_artifacts: Optional[List[str]],
        final_text: str,
    ) -> Handoff:
        rt = self._runtime(worker)
        workspace = self._workspace(worker)
        diff = workspace.compute_diff_against_canonical()

        artifacts = list(rt.artifacts)
        if extra_artifacts:
            artifacts.extend(extra_artifacts)
        artifacts = self._dedupe(artifacts)

        task_id = task_id_override or rt.task_id or "none"
        status = self._resolve_handoff_status(worker, requested_status, len(diff))

        handoff = Handoff(
            agent_id=worker,
            task_id=str(task_id),
            status=status,
            diff=diff,
            artifacts=artifacts,
            metrics=HandoffMetrics(
                wall_time=max(time.time() - float(rt.task_started_at), 0.0),
                tokens_used=int(rt.tokens_used),
                attempts=int(rt.attempts),
                files_modified=len(diff),
            ),
            workspace_path=str(workspace.path),
        )

        handoff.narrative = (
            narrative_override if narrative_override else self._compose_handoff_narrative(worker, handoff, final_text)
        )
        return handoff

    def _submit_handoff(self, worker: str, args: Optional[Dict[str, Any]] = None, final_text: str = "") -> str:
        args = args or {}
        rt = self._runtime(worker)
        if rt.handoff_submitted:
            return f"Handoff already submitted for task {rt.task_id}"

        requested_status = self._status_from_string(args.get("status"))
        narrative_override = args.get("narrative") if isinstance(args.get("narrative"), str) else None
        task_override = str(args.get("task_id")) if args.get("task_id") is not None else None
        extra_artifacts = (
            [a for a in args.get("artifacts", []) if isinstance(a, str)]
            if isinstance(args.get("artifacts"), list)
            else []
        )

        handoff = self._build_handoff(
            worker=worker,
            requested_status=requested_status,
            task_id_override=task_override,
            narrative_override=narrative_override,
            extra_artifacts=extra_artifacts,
            final_text=final_text or rt.last_text,
        )

        HANDOFFS.append(handoff)
        rt.handoff_submitted = True

        BUS.send(
            sender=worker,
            to=self.planner_name,
            content=handoff.narrative,
            msg_type="handoff",
            extra={"handoff": handoff.to_dict()},
        )

        return f"Submitted handoff for task {handoff.task_id} ({handoff.status.value})"

    def _cleanup_workspace(self, worker: str):
        rt = self._runtime(worker)
        workspace = self._workspace(worker)
        try:
            workspace.cleanup()
            rt.workspace_cleaned = True
        except Exception as e:
            self._record_error(worker, f"workspace_cleanup: {e}")

    def list_workers(self) -> str:
        if not self.workers:
            return "No workers."

        lines = []
        for name in sorted(self.workers.keys()):
            meta = self.workers[name]
            rt = self._runtime(name)
            pending = BUS.count_pending(name)
            lines.append(
                f"- {name}: status={meta.get('status', 'unknown')} "
                f"task={meta.get('task_id', 'none')} "
                f"workspace={rt.workspace_path or '(none)'} cleaned={rt.workspace_cleaned} inbox={pending}"
            )
        return "\n".join(lines)

    def review_handoffs(
        self,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        include_diff: bool = False,
    ) -> str:
        selected: List[Handoff] = []
        for handoff in HANDOFFS:
            if task_id and handoff.task_id != str(task_id):
                continue
            if agent_id and handoff.agent_id != str(agent_id):
                continue
            selected.append(handoff)

        if not selected:
            return "No handoffs found."

        payload = []
        for handoff in selected:
            item: Dict[str, Any] = {
                "agent_id": handoff.agent_id,
                "task_id": handoff.task_id,
                "status": handoff.status.value,
                "narrative": handoff.narrative,
                "artifacts": handoff.artifacts,
                "workspace_path": handoff.workspace_path,
                "metrics": asdict(handoff.metrics),
            }
            if include_diff:
                item["diff"] = handoff.diff
            payload.append(item)
        return json.dumps(payload, indent=2)

    def _planner_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "spawn_worker",
                "description": "Spawn isolated worker with one concrete task.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "task": {"type": "string"},
                        "task_id": {"type": "string"},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "review_handoff",
                "description": "Review worker handoffs and canonical diffs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "include_diff": {"type": "boolean"},
                    },
                },
            },
            {
                "name": "rewrite_scratchpad",
                "description": "Rewrite planner scratchpad.",
                "input_schema": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
            },
            {
                "name": "send_message",
                "description": "Send message to worker.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "content": {"type": "string"},
                        "msg_type": {"type": "string", "enum": ["message", "broadcast"]},
                    },
                    "required": ["to", "content"],
                },
            },
            {
                "name": "read_inbox",
                "description": "Read and drain planner inbox.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_workers",
                "description": "List worker + workspace status.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    def _worker_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "bash",
                "description": "Run shell command in workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            {
                "name": "read_file",
                "description": "Read file from workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write/create file in workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Replace exact text in workspace file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
            {
                "name": "submit_handoff",
                "description": "Submit handoff with canonical diff.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "status": {"type": "string", "enum": [s.value for s in HandoffStatus]},
                        "narrative": {"type": "string"},
                        "artifacts": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            {
                "name": "rewrite_scratchpad",
                "description": "Rewrite worker scratchpad.",
                "input_schema": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
            },
        ]

    def _run_worker_bash(self, worker: str, command: str) -> str:
        blocked = ["rm -rf /", "sudo", "shutdown", "reboot"]
        if any(fragment in command for fragment in blocked):
            self._record_error(worker, f"bash blocked: {command}")
            return "Error: Dangerous command blocked"

        try:
            out = self._workspace(worker).run_bash(command, timeout=120)
            return out[:MAX_INLINE_OUTPUT]
        except subprocess.TimeoutExpired:
            self._record_error(worker, f"bash timeout: {command}")
            return "Error: Timeout (120s)"
        except Exception as e:
            self._record_error(worker, f"bash error: {e}")
            return f"Error: {e}"

    def _run_worker_read(self, worker: str, path: str, limit: Optional[int] = None) -> str:
        try:
            out = self._workspace(worker).read_file(path, limit=limit)
            return out[:MAX_INLINE_OUTPUT]
        except Exception as e:
            self._record_error(worker, f"read_file({path}): {e}")
            return f"Error: {e}"

    def _run_worker_write(self, worker: str, path: str, content: str) -> str:
        try:
            self._workspace(worker).write_file(path, content)
            self._record_artifact(worker, path)
            return f"Wrote {len(content)} bytes"
        except Exception as e:
            self._record_error(worker, f"write_file({path}): {e}")
            return f"Error: {e}"

    def _run_worker_edit(self, worker: str, path: str, old_text: str, new_text: str) -> str:
        try:
            self._workspace(worker).edit_file(path, old_text, new_text)
            self._record_artifact(worker, path)
            return f"Edited {path}"
        except Exception as e:
            self._record_error(worker, f"edit_file({path}): {e}")
            return f"Error: {e}"

    def _worker_exec(self, worker: str, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "bash":
            return self._run_worker_bash(worker, str(args.get("command", "")))
        if tool_name == "read_file":
            return self._run_worker_read(worker, str(args.get("path", "")), args.get("limit"))
        if tool_name == "write_file":
            return self._run_worker_write(worker, str(args.get("path", "")), str(args.get("content", "")))
        if tool_name == "edit_file":
            return self._run_worker_edit(
                worker,
                str(args.get("path", "")),
                str(args.get("old_text", "")),
                str(args.get("new_text", "")),
            )
        if tool_name == "submit_handoff":
            return self._submit_handoff(worker, args)
        if tool_name == "rewrite_scratchpad":
            return SCRATCHPADS.rewrite(worker, str(args.get("content", "")))
        return f"Unknown tool: {tool_name}"

    def spawn_worker(self, task: str, name: Optional[str] = None, task_id: Optional[str] = None) -> str:
        worker_name = name.strip() if isinstance(name, str) and name.strip() else self._next_worker_name()
        if worker_name in self.workers:
            state = self.workers[worker_name].get("status", "unknown")
            if state not in ("idle", "shutdown"):
                return f"Error: '{worker_name}' is currently {state}"

        worker_task_id = task_id or str(uuid.uuid4())[:8]
        workspace = self._workspace(worker_name)
        try:
            created = workspace.create()
        except Exception as e:
            return f"Error: failed to create workspace for {worker_name}: {e}"

        self.workers[worker_name] = {
            "name": worker_name,
            "role": Role.WORKER.value,
            "status": "working",
            "task_id": worker_task_id,
            "assigned_task": task,
            "started_at": time.time(),
        }

        self.worker_runtime[worker_name] = WorkerRuntime(
            worker=worker_name,
            task_id=worker_task_id,
            task_started_at=time.time(),
            workspace_path=str(created),
        )

        SCRATCHPADS.rewrite(
            worker_name,
            (
                f"# Worker Scratchpad ({worker_name})\n\n"
                "## Role Constraint\n"
                "- I execute task and submit handoff.\n"
                "- I do NOT decompose or delegate.\n\n"
                "## Workspace Constraint\n"
                f"- Workspace: {created}\n"
                "- I can only read/write inside this workspace.\n"
                "- Canonical repo remains unchanged until future merge phase.\n\n"
                "## Assigned Task\n"
                f"- {task}\n"
            ),
        )

        thread = threading.Thread(
            target=self._worker_loop,
            args=(worker_name, task, worker_task_id),
            daemon=True,
        )
        self.worker_threads[worker_name] = thread
        thread.start()

        return f"Spawned '{worker_name}' with task_id={worker_task_id} workspace={created}"

    def _worker_loop(self, worker: str, task: str, task_id: str):
        runtime = self._runtime(worker)
        runtime.task_id = task_id
        runtime.task_started_at = time.time()

        system_prompt = WORKER_SYSTEM_TEMPLATE.format(name=worker, planner=self.planner_name)
        messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"<assignment>task_id={task_id}\n{task}</assignment>\n"
                    "Execute only inside your workspace and submit handoff on completion."
                ),
            },
            {
                "role": "user",
                "content": f"<workspace>{runtime.workspace_path}</workspace>",
            },
            {
                "role": "user",
                "content": f"<scratchpad>{SCRATCHPADS.read(worker) or '(empty scratchpad)'}</scratchpad>",
            },
        ]

        tools = self._worker_tools()

        for _ in range(MAX_WORKER_TURNS):
            inbox = BUS.read_inbox(worker)
            for msg in inbox:
                messages.append({"role": "user", "content": json.dumps(msg)})

            try:
                response = client.messages.create(
                    model=MODEL,
                    system=system_prompt,
                    messages=messages,
                    tools=tools,
                    max_tokens=6000,
                )
            except Exception as e:
                self._record_error(worker, f"llm_call: {e}")
                self._submit_handoff(
                    worker,
                    {"status": HandoffStatus.FAILED.value, "task_id": task_id},
                    final_text="LLM call failed.",
                )
                break

            runtime.attempts += 1
            runtime.turns += 1
            runtime.tokens_used += getattr(response.usage, "input_tokens", 0)
            runtime.tokens_used += getattr(response.usage, "output_tokens", 0)

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                runtime.last_text = "\n".join(
                    blk.text for blk in response.content if getattr(blk, "type", None) == "text"
                ).strip()
                if not runtime.handoff_submitted:
                    self._submit_handoff(worker, {"task_id": task_id}, final_text=runtime.last_text)
                break

            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output = self._worker_exec(worker, block.name, block.input)
                print(f"  [{worker}] {block.name}: {str(output)[:120]}")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })

            messages.append({"role": "user", "content": results})
            if runtime.handoff_submitted:
                break

        if not runtime.handoff_submitted:
            self._submit_handoff(worker, {"task_id": task_id}, final_text=runtime.last_text)

        self._cleanup_workspace(worker)
        self._set_worker_status(worker, "idle")

    def planner_exec(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "spawn_worker":
            return self.spawn_worker(
                task=str(args.get("task", "")),
                name=str(args.get("name", "")).strip() or None,
                task_id=str(args.get("task_id", "")).strip() or None,
            )

        if tool_name == "review_handoff":
            return self.review_handoffs(
                task_id=str(args.get("task_id")) if args.get("task_id") is not None else None,
                agent_id=str(args.get("agent_id")) if args.get("agent_id") is not None else None,
                include_diff=bool(args.get("include_diff", False)),
            )

        if tool_name == "rewrite_scratchpad":
            return SCRATCHPADS.rewrite(self.planner_name, str(args.get("content", "")))

        if tool_name == "send_message":
            to = str(args.get("to", ""))
            if not to:
                return "Error: missing 'to'"
            msg_type = str(args.get("msg_type", "message"))
            if msg_type not in ("message", "broadcast"):
                return "Error: msg_type must be 'message' or 'broadcast'"
            return BUS.send(
                sender=self.planner_name,
                to=to,
                content=str(args.get("content", "")),
                msg_type=msg_type,
            )

        if tool_name == "read_inbox":
            return json.dumps(BUS.read_inbox(self.planner_name), indent=2)

        if tool_name == "list_workers":
            return self.list_workers()

        return f"Unknown tool: {tool_name}"


HARNESS = PlannerWorkerIsolationHarness()
TOOLS = HARNESS._planner_tools()


def agent_loop(messages: List[Dict[str, Any]]):
    while True:
        inbox = BUS.read_inbox(HARNESS.planner_name)
        if inbox:
            messages.append({"role": "user", "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"})
            messages.append({"role": "assistant", "content": "I reviewed inbox updates and will coordinate next actions."})

        response = client.messages.create(
            model=MODEL,
            system=PLANNER_SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        tool_results = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            try:
                output = HARNESS.planner_exec(block.name, block.input)
            except Exception as e:
                output = f"Error: {e}"
            print(f"> {block.name}: {str(output)[:200]}")
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})

        messages.append({"role": "user", "content": tool_results})


def _print_workers():
    print(HARNESS.list_workers())


def _print_handoffs(include_diff: bool = False):
    print(HARNESS.review_handoffs(include_diff=include_diff))


def _print_planner_inbox():
    print(json.dumps(BUS.read_inbox(HARNESS.planner_name), indent=2))


def _print_scratchpad(name: str):
    content = SCRATCHPADS.read(name)
    if not content:
        print(f"Scratchpad for {name} is empty")
    else:
        print(content)


def _workspace_status(worker_name: str) -> str:
    rt = HARNESS._runtime(worker_name)
    if not rt.workspace_path:
        return f"No workspace recorded for {worker_name}"
    exists = Path(rt.workspace_path).exists()
    return (
        f"worker={worker_name} workspace={rt.workspace_path} "
        f"exists={exists} cleaned={rt.workspace_cleaned}"
    )


def _print_workspace_status(worker_name: str):
    print(_workspace_status(worker_name))


def _demo_seed_prompt() -> str:
    return (
        "You are the planner. Decompose this request into isolated worker tasks: "
        "Create src/hello.py that prints Hello and add tests/test_hello.py. "
        "Delegate to workers, review handoffs, and summarize outcomes."
    )


def _sleep_for_workers(seconds: int):
    deadline = time.time() + max(seconds, 0)
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    print("s15 worker isolation")
    print("Commands: /workers /handoffs /handoffs_diff /inbox /scratch <name> /workspace <name> /demo /wait <sec> /q")

    history: List[Dict[str, Any]] = []

    while True:
        try:
            query = input("\033[36ms15 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        q = query.strip()
        if q.lower() in ("q", "exit", "/q", ""):
            break

        if q == "/workers":
            _print_workers()
            continue

        if q == "/handoffs":
            _print_handoffs(include_diff=False)
            continue

        if q == "/handoffs_diff":
            _print_handoffs(include_diff=True)
            continue

        if q == "/inbox":
            _print_planner_inbox()
            continue

        if q.startswith("/scratch "):
            who = q.split(" ", 1)[1].strip()
            _print_scratchpad(who)
            continue

        if q.startswith("/workspace "):
            who = q.split(" ", 1)[1].strip()
            _print_workspace_status(who)
            continue

        if q == "/demo":
            history.append({"role": "user", "content": _demo_seed_prompt()})
            agent_loop(history)
            print()
            continue

        if q.startswith("/wait "):
            raw = q.split(" ", 1)[1].strip()
            sec = int(raw) if raw.isdigit() else 5
            print(f"Waiting {sec}s for workers...")
            _sleep_for_workers(sec)
            continue

        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
