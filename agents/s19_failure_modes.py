#!/usr/bin/env python3
"""
s19_failure_modes.py - Failure Modes and Recovery (Watchdog)

Session concept:
- Add independent watchdog monitoring for pathological worker behavior.
- Detect failure modes from append-only activity logs.
- Kill and respawn stuck workers so throughput continues.

Failure modes covered in this session:
- Zombie: no heartbeat for N seconds.
- Tunnel vision: same file edited too many times.
- Token burn: high token spend without any tool call.

Constraints:
- Watchdog is monitoring + intervention only.
- Watchdog does not make planning or decomposition decisions.
- Activity logs are append-only JSONL under .activity/.
"""

from __future__ import annotations

import json
import importlib
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

Anthropic = importlib.import_module("anthropic").Anthropic

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd().resolve()
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-5-20250929")
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
ACTIVITY_DIR = WORKDIR / ".activity"
SCRATCHPAD_DIR = WORKDIR / ".scratchpad"

POLL_INTERVAL = 2.0
MAX_WORKER_TURNS = 48
MAX_PLANNER_TURNS = 80
MAX_INLINE_OUTPUT = 50000
MAX_SCRATCHPAD_CHARS = 9000

WATCHDOG_INTERVAL = 2.5
ZOMBIE_SECONDS = 60.0
TUNNEL_EDITS = 20
TOKEN_BURN_TOKENS = 16000

VALID_MSG_TYPES = {"message", "broadcast", "handoff", "interrupt", "watchdog_report"}

PLANNER_SYSTEM = (
    f"You are a PLANNER at {WORKDIR}. "
    "You decompose and delegate only. You NEVER write code. "
    "Monitor worker handoffs and watchdog reports. "
    "Use workers for execution and keep progress moving."
)

WORKER_SYSTEM_TEMPLATE = (
    "You are WORKER '{name}' under planner '{planner}'. "
    "Execute one assigned task. Do not decompose. Do not spawn. "
    "Submit a handoff when complete or interrupted."
)


class AgentRole(str, Enum):
    PLANNER = "planner"
    WORKER = "worker"


class HandoffStatus(str, Enum):
    SUCCESS = "Success"
    PARTIAL_FAILURE = "PartialFailure"
    FAILED = "Failed"
    BLOCKED = "Blocked"


class FailureMode(str, Enum):
    ZOMBIE = "zombie"
    TUNNEL_VISION = "tunnel_vision"
    TOKEN_BURN = "token_burn"


@dataclass
class HandoffMetrics:
    wall_time: float = 0.0
    tokens_used: int = 0
    attempts: int = 0
    files_modified: int = 0


@dataclass
class Handoff:
    handoff_id: str
    agent_id: str
    task_id: str
    status: HandoffStatus
    diff: Dict[str, Dict[str, str]] = field(default_factory=dict)
    narrative: str = ""
    artifacts: List[str] = field(default_factory=list)
    metrics: HandoffMetrics = field(default_factory=HandoffMetrics)
    watchdog_intervention: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass
class WatchdogEvent:
    event_id: str
    timestamp: float
    worker: str
    mode: FailureMode
    detail: str
    action: str
    task_id: str
    replacement_worker: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        return payload


@dataclass
class WorkerRuntime:
    worker: str
    planner: str
    task_id: str
    assigned_task: str
    allowed_paths: List[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    attempts: int = 0
    turns: int = 0
    tokens_used: int = 0
    tokens_since_tool_call: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    last_tool_call_at: float = field(default_factory=time.time)
    interrupted: bool = False
    shutdown_requested: bool = False
    watchdog_reason: Optional[str] = None
    handoff_submitted: bool = False
    errors: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    diff: Dict[str, Dict[str, str]] = field(default_factory=dict)
    edit_counts: Dict[str, int] = field(default_factory=dict)
    last_text: str = ""
    spawn_depth: int = 0


class ScratchpadManager:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def read(self, name: str) -> str:
        path = self._path(name)
        if not path.exists():
            return ""
        return path.read_text()[:MAX_SCRATCHPAD_CHARS]

    def rewrite(self, name: str, content: str) -> str:
        text = content[:MAX_SCRATCHPAD_CHARS]
        with self._lock:
            self._path(name).write_text(text)
        return f"Scratchpad rewritten: {name} ({len(text)} chars)"


class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}

    def _path(self, name: str) -> Path:
        return self.dir / f"{name}.jsonl"

    def _lock_for(self, name: str) -> threading.Lock:
        if name not in self._locks:
            self._locks[name] = threading.Lock()
        return self._locks[name]

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

        lock = self._lock_for(to)
        with lock:
            with open(self._path(to), "a") as f:
                f.write(json.dumps(payload) + "\n")

        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> List[Dict[str, Any]]:
        path = self._path(name)
        if not path.exists():
            return []

        lock = self._lock_for(name)
        with lock:
            raw = path.read_text().strip()
            if not raw:
                path.write_text("")
                return []

            out: List[Dict[str, Any]] = []
            for line in raw.splitlines():
                if line.strip():
                    out.append(json.loads(line))
            path.write_text("")
            return out

    def count_pending(self, name: str) -> int:
        path = self._path(name)
        if not path.exists():
            return 0
        raw = path.read_text().strip()
        if not raw:
            return 0
        return len([ln for ln in raw.splitlines() if ln.strip()])


class ActivityLogger:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}

    def _path(self, worker: str) -> Path:
        return self.root / f"{worker}.jsonl"

    def _lock_for(self, worker: str) -> threading.Lock:
        if worker not in self._locks:
            self._locks[worker] = threading.Lock()
        return self._locks[worker]

    def log(
        self,
        worker: str,
        event: str,
        task_id: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "ts": time.time(),
            "event": event,
            "worker": worker,
            "task_id": task_id,
        }
        if data:
            payload.update(data)

        lock = self._lock_for(worker)
        with lock:
            with open(self._path(worker), "a") as f:
                f.write(json.dumps(payload) + "\n")

    def read_recent(self, worker: str, limit: int = 200) -> List[Dict[str, Any]]:
        path = self._path(worker)
        if not path.exists():
            return []

        lock = self._lock_for(worker)
        with lock:
            raw = path.read_text().splitlines()

        lines = raw[-max(limit, 1) :]
        out: List[Dict[str, Any]] = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out

    def last_timestamp(self, worker: str) -> Optional[float]:
        recent = self.read_recent(worker, limit=1)
        if not recent:
            return None
        ts = recent[-1].get("ts")
        return float(ts) if isinstance(ts, (int, float)) else None

    def recent_edit_counts(self, worker: str, limit: int = 200) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self.read_recent(worker, limit=limit):
            if item.get("event") != "tool_call":
                continue
            if item.get("tool") not in ("write_file", "edit_file"):
                continue
            rel_path = str(item.get("path", "")).strip()
            if not rel_path:
                continue
            counts[rel_path] = counts.get(rel_path, 0) + 1
        return counts

    def has_tool_call_after(self, worker: str, ts: float, limit: int = 200) -> bool:
        for item in self.read_recent(worker, limit=limit):
            item_ts = item.get("ts")
            if not isinstance(item_ts, (int, float)):
                continue
            if float(item_ts) <= ts:
                continue
            if item.get("event") == "tool_call":
                return True
        return False


BUS = MessageBus(INBOX_DIR)
SCRATCHPADS = ScratchpadManager(SCRATCHPAD_DIR)
ACTIVITY = ActivityLogger(ACTIVITY_DIR)
HANDOFFS: List[Handoff] = []


class FailureHarness:
    def __init__(self, planner_name: str = "planner"):
        self.planner_name = planner_name

        self.workers: Dict[str, WorkerRuntime] = {}
        self.worker_threads: Dict[str, threading.Thread] = {}
        self.worker_status: Dict[str, str] = {}
        self.worker_lock = threading.Lock()

        self.watchdog_events: List[WatchdogEvent] = []
        self.watchdog_lock = threading.Lock()

        self.respawn_count: Dict[str, int] = {}
        self.max_respawns_per_task = 3

        self._stop_event = threading.Event()
        self.watchdog = Watchdog(self, poll_seconds=WATCHDOG_INTERVAL)

        self._bootstrap_scratchpads()
        self.watchdog.start()

    def shutdown(self) -> None:
        self._stop_event.set()
        self.watchdog.stop()

        workers = list(self.workers.keys())
        for worker in workers:
            self.request_shutdown(worker, reason="harness shutdown")

    def _bootstrap_scratchpads(self) -> None:
        if SCRATCHPADS.read(self.planner_name):
            return
        SCRATCHPADS.rewrite(
            self.planner_name,
            (
                f"# Planner Scratchpad ({self.planner_name})\n\n"
                "## Role\n"
                "- I decompose and delegate.\n"
                "- I NEVER write code directly.\n\n"
                "## Watchdog\n"
                "- Watchdog reports indicate failure modes in workers.\n"
                "- I can respawn work after watchdog interventions.\n"
            ),
        )

    def _new_worker_name(self) -> str:
        n = 1
        while True:
            name = f"worker-{n}"
            if name not in self.worker_status:
                return name
            n += 1

    def _set_status(self, worker: str, status: str) -> None:
        with self.worker_lock:
            self.worker_status[worker] = status

    def _runtime(self, worker: str) -> Optional[WorkerRuntime]:
        with self.worker_lock:
            return self.workers.get(worker)

    def _safe_path(self, rel_path: str) -> Path:
        resolved = (WORKDIR / rel_path).resolve()
        if not resolved.is_relative_to(WORKDIR):
            raise ValueError(f"Path escapes workspace: {rel_path}")
        return resolved

    def _record_error(self, worker: str, message: str) -> None:
        rt = self._runtime(worker)
        if not rt:
            return
        rt.errors.append(message)
        ACTIVITY.log(worker, "error", rt.task_id, {"error": message})

    def _record_diff(self, worker: str, path: str, before: str, after: str) -> None:
        rt = self._runtime(worker)
        if not rt:
            return

        if path in rt.diff:
            rt.diff[path] = {"before": rt.diff[path]["before"], "after": after}
        else:
            rt.diff[path] = {"before": before, "after": after}

        rt.artifacts = self._dedupe(rt.artifacts + [path])
        rt.edit_counts[path] = rt.edit_counts.get(path, 0) + 1

    def _heartbeat(self, worker: str, reason: str = "tick") -> None:
        rt = self._runtime(worker)
        if not rt:
            return
        rt.last_heartbeat = time.time()
        ACTIVITY.log(worker, "heartbeat", rt.task_id, {"reason": reason})

    def _dedupe(self, items: List[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    def spawn_worker(
        self,
        task: str,
        name: Optional[str] = None,
        task_id: Optional[str] = None,
        allowed_paths: Optional[List[str]] = None,
        spawn_depth: int = 0,
    ) -> str:
        worker_name = (
            name.strip()
            if isinstance(name, str) and name.strip()
            else self._new_worker_name()
        )
        if worker_name in self.worker_status:
            status = self.worker_status.get(worker_name, "unknown")
            if status not in ("idle", "shutdown"):
                return f"Error: '{worker_name}' is currently {status}"

        new_task_id = task_id or str(uuid.uuid4())[:8]
        runtime = WorkerRuntime(
            worker=worker_name,
            planner=self.planner_name,
            task_id=new_task_id,
            assigned_task=task,
            allowed_paths=list(allowed_paths or []),
            spawn_depth=max(spawn_depth, 0),
        )

        with self.worker_lock:
            self.workers[worker_name] = runtime
            self.worker_status[worker_name] = "working"

        ACTIVITY.log(
            worker_name,
            "spawn",
            new_task_id,
            {
                "task": task,
                "allowed_paths": runtime.allowed_paths,
                "spawn_depth": runtime.spawn_depth,
            },
        )

        SCRATCHPADS.rewrite(
            worker_name,
            (
                f"# Worker Scratchpad ({worker_name})\n\n"
                "## Identity\n"
                f"- Planner: {self.planner_name}\n"
                f"- Task ID: {new_task_id}\n\n"
                "## Constraints\n"
                "- Execute assigned task only.\n"
                "- Submit handoff with narrative when complete or interrupted.\n"
                "- Do NOT decompose and do NOT spawn.\n\n"
                "## Scope\n"
                f"- Allowed paths: {runtime.allowed_paths or ['(not restricted)']}\n"
            ),
        )

        thread = threading.Thread(
            target=self._worker_loop,
            args=(worker_name, task, new_task_id),
            daemon=True,
        )
        self.worker_threads[worker_name] = thread
        thread.start()

        return f"Spawned {worker_name} task_id={new_task_id}"

    def _respawn_worker(self, previous_worker: str, reason: str) -> str:
        rt = self._runtime(previous_worker)
        if not rt:
            return "Error: worker not found for respawn"

        key = f"{rt.task_id}:{rt.assigned_task}"
        count = self.respawn_count.get(key, 0)
        if count >= self.max_respawns_per_task:
            return (
                f"Respawn skipped for {previous_worker}: "
                f"retry cap reached ({self.max_respawns_per_task})"
            )

        self.respawn_count[key] = count + 1
        replacement_name = self._new_worker_name()
        replacement_task_id = str(uuid.uuid4())[:8]

        spawn_msg = self.spawn_worker(
            task=rt.assigned_task,
            name=replacement_name,
            task_id=replacement_task_id,
            allowed_paths=rt.allowed_paths,
            spawn_depth=rt.spawn_depth + 1,
        )

        ACTIVITY.log(
            previous_worker,
            "respawn",
            rt.task_id,
            {
                "reason": reason,
                "replacement_worker": replacement_name,
                "replacement_task_id": replacement_task_id,
            },
        )

        return spawn_msg

    def snapshot_workers(self) -> List[WorkerRuntime]:
        with self.worker_lock:
            return [self.workers[w] for w in sorted(self.workers.keys())]

    def register_watchdog_event(self, event: WatchdogEvent) -> None:
        with self.watchdog_lock:
            self.watchdog_events.append(event)

        ACTIVITY.log(
            event.worker,
            "watchdog",
            event.task_id,
            {
                "mode": event.mode.value,
                "action": event.action,
                "detail": event.detail,
                "replacement_worker": event.replacement_worker,
            },
        )

        BUS.send(
            sender="watchdog",
            to=self.planner_name,
            content=f"Watchdog {event.mode.value} on {event.worker}: {event.action}",
            msg_type="watchdog_report",
            extra={"watchdog_event": event.to_dict()},
        )

    def list_watchdog_events(self, limit: int = 25) -> str:
        with self.watchdog_lock:
            subset = self.watchdog_events[-max(limit, 1) :]
        return json.dumps([e.to_dict() for e in subset], indent=2)

    def send_interrupt(self, worker: str, reason: str) -> str:
        rt = self._runtime(worker)
        if not rt:
            return f"Error: Unknown worker '{worker}'"

        rt.interrupted = True
        ACTIVITY.log(worker, "interrupt", rt.task_id, {"reason": reason})
        return BUS.send(
            sender="watchdog",
            to=worker,
            content=(
                "Watchdog interrupt: "
                f"{reason}. Step back, try a different approach, and submit what you have."
            ),
            msg_type="interrupt",
            extra={"reason": reason},
        )

    def request_shutdown(self, worker: str, reason: str) -> str:
        rt = self._runtime(worker)
        if not rt:
            return f"Error: Unknown worker '{worker}'"

        rt.shutdown_requested = True
        rt.watchdog_reason = reason
        self._set_status(worker, "shutdown")
        ACTIVITY.log(worker, "kill", rt.task_id, {"reason": reason})

        BUS.send(
            sender="watchdog",
            to=worker,
            content=f"Kill signal from watchdog: {reason}",
            msg_type="interrupt",
            extra={"reason": reason, "kill": True},
        )

        return f"Shutdown requested for {worker} ({reason})"

    def kill_and_respawn(
        self, worker: str, mode: FailureMode, detail: str
    ) -> WatchdogEvent:
        rt = self._runtime(worker)
        if not rt:
            event = WatchdogEvent(
                event_id=f"wd-{uuid.uuid4().hex[:10]}",
                timestamp=time.time(),
                worker=worker,
                mode=mode,
                detail=f"{detail} (worker already gone)",
                action="no-op",
                task_id="unknown",
            )
            self.register_watchdog_event(event)
            return event

        self.send_interrupt(worker, reason=detail)
        self.request_shutdown(worker, reason=f"watchdog:{mode.value}")
        spawn_result = self._respawn_worker(worker, reason=mode.value)

        replacement: Optional[str] = None
        if spawn_result.startswith("Spawned "):
            replacement = spawn_result.split(" ")[1]

        event = WatchdogEvent(
            event_id=f"wd-{uuid.uuid4().hex[:10]}",
            timestamp=time.time(),
            worker=worker,
            mode=mode,
            detail=detail,
            action=f"kill+respawn ({spawn_result})",
            task_id=rt.task_id,
            replacement_worker=replacement,
        )
        self.register_watchdog_event(event)
        return event

    def _scope_violation(self, worker: str, path: str) -> bool:
        rt = self._runtime(worker)
        if not rt:
            return False
        if not rt.allowed_paths:
            return False
        normalized = path.strip().lstrip("./")
        for allowed in rt.allowed_paths:
            allow = allowed.strip().lstrip("./")
            if not allow:
                continue
            if normalized == allow or normalized.startswith(allow + "/"):
                return False
        return True

    def _tool_call_logged(
        self, worker: str, tool: str, data: Optional[Dict[str, Any]] = None
    ) -> None:
        rt = self._runtime(worker)
        if not rt:
            return
        rt.tokens_since_tool_call = 0
        rt.last_tool_call_at = time.time()
        self._heartbeat(worker, reason=f"tool:{tool}")

        payload = {"tool": tool}
        if data:
            payload.update(data)
        ACTIVITY.log(worker, "tool_call", rt.task_id, payload)

    def _run_worker_bash(self, worker: str, command: str) -> str:
        blocked = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
        if any(fragment in command for fragment in blocked):
            self._record_error(worker, f"bash blocked: {command}")
            return "Error: Dangerous command blocked"

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                timeout=120,
            )
            out = (proc.stdout + proc.stderr).strip()
            self._tool_call_logged(
                worker, "bash", {"command": command, "return_code": proc.returncode}
            )
            return out[:MAX_INLINE_OUTPUT] if out else "(no output)"
        except subprocess.TimeoutExpired:
            self._record_error(worker, f"bash timeout: {command}")
            return "Error: Timeout (120s)"
        except Exception as e:
            self._record_error(worker, f"bash error: {e}")
            return f"Error: {e}"

    def _run_worker_read(
        self, worker: str, path: str, limit: Optional[int] = None
    ) -> str:
        try:
            fp = self._safe_path(path)
            lines = fp.read_text().splitlines()
            if limit is not None and int(limit) > 0 and len(lines) > int(limit):
                lines = lines[: int(limit)] + [
                    f"... ({len(lines) - int(limit)} more lines)"
                ]

            self._tool_call_logged(worker, "read_file", {"path": path})
            return "\n".join(lines)[:MAX_INLINE_OUTPUT]
        except Exception as e:
            self._record_error(worker, f"read_file({path}): {e}")
            return f"Error: {e}"

    def _run_worker_write(self, worker: str, path: str, content: str) -> str:
        try:
            if self._scope_violation(worker, path):
                self._record_error(worker, f"scope_creep write_file({path})")
                runtime = self._runtime(worker)
                ACTIVITY.log(
                    worker,
                    "scope_creep",
                    runtime.task_id if runtime is not None else "unknown",
                    {"path": path},
                )
                return f"Error: Path '{path}' outside assigned scope"

            fp = self._safe_path(path)
            before = fp.read_text() if fp.exists() else ""
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
            after = fp.read_text()
            self._record_diff(worker, path, before, after)
            self._tool_call_logged(
                worker, "write_file", {"path": path, "bytes": len(content)}
            )
            return f"Wrote {len(content)} bytes"
        except Exception as e:
            self._record_error(worker, f"write_file({path}): {e}")
            return f"Error: {e}"

    def _run_worker_edit(
        self, worker: str, path: str, old_text: str, new_text: str
    ) -> str:
        try:
            if self._scope_violation(worker, path):
                self._record_error(worker, f"scope_creep edit_file({path})")
                runtime = self._runtime(worker)
                ACTIVITY.log(
                    worker,
                    "scope_creep",
                    runtime.task_id if runtime is not None else "unknown",
                    {"path": path},
                )
                return f"Error: Path '{path}' outside assigned scope"

            fp = self._safe_path(path)
            before = fp.read_text()
            if old_text not in before:
                msg = f"Text not found in {path}"
                self._record_error(worker, f"edit_file({path}): {msg}")
                return f"Error: {msg}"

            fp.write_text(before.replace(old_text, new_text, 1))
            after = fp.read_text()
            self._record_diff(worker, path, before, after)
            self._tool_call_logged(worker, "edit_file", {"path": path})
            return f"Edited {path}"
        except Exception as e:
            self._record_error(worker, f"edit_file({path}): {e}")
            return f"Error: {e}"

    def _status_from_string(self, raw: Optional[str]) -> Optional[HandoffStatus]:
        if not raw:
            return None
        for status in HandoffStatus:
            if status.value == str(raw).strip():
                return status
        return None

    def _resolve_handoff_status(
        self, rt: WorkerRuntime, requested: Optional[HandoffStatus]
    ) -> HandoffStatus:
        if requested:
            return requested
        if rt.shutdown_requested and not rt.diff:
            return HandoffStatus.BLOCKED
        if rt.shutdown_requested and rt.diff:
            return HandoffStatus.PARTIAL_FAILURE
        if not rt.errors:
            return HandoffStatus.SUCCESS
        if rt.errors and rt.diff:
            return HandoffStatus.PARTIAL_FAILURE
        lower = "\n".join(rt.errors).lower()
        if any(
            k in lower
            for k in ("blocked", "scope_creep", "permission", "timeout", "not found")
        ):
            return HandoffStatus.BLOCKED
        return HandoffStatus.FAILED

    def _compose_handoff_narrative(
        self, rt: WorkerRuntime, status: HandoffStatus
    ) -> str:
        payload = {
            "worker": rt.worker,
            "task_id": rt.task_id,
            "status": status.value,
            "assigned_task": rt.assigned_task,
            "watchdog_reason": rt.watchdog_reason,
            "files_modified": len(rt.diff),
            "errors": rt.errors[-6:],
            "assistant_final_text": rt.last_text,
            "diff_files": list(rt.diff.keys()),
        }
        try:
            response = client.messages.create(
                model=MODEL,
                system=(
                    "Write concise worker handoff narrative for planner. "
                    "Include what changed, what did not, risk, and one next step. "
                    "If interrupted by watchdog, acknowledge it. "
                    "Plain text <= 10 lines."
                ),
                messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
                max_tokens=420,
            )
            rt.tokens_used += getattr(response.usage, "input_tokens", 0)
            rt.tokens_used += getattr(response.usage, "output_tokens", 0)
            chunks = [
                b.text for b in response.content if getattr(b, "type", None) == "text"
            ]
            text = "\n".join(chunks).strip()
            if text:
                return text
        except Exception as e:
            rt.errors.append(f"narrative_generation: {e}")

        changed = ", ".join(rt.diff.keys()) if rt.diff else "no files"
        lines = [
            f"Worker {rt.worker} finished task {rt.task_id} with status {status.value}.",
            f"Changed: {changed}.",
        ]
        if rt.watchdog_reason:
            lines.append(f"Watchdog intervention: {rt.watchdog_reason}")
        if rt.errors:
            lines.append(f"Latest error: {rt.errors[-1]}")
        if rt.last_text:
            lines.append(f"Final output: {rt.last_text[:220]}")
        lines.append("Next step: planner reviews this handoff and decides follow-up.")
        return "\n".join(lines)

    def _submit_handoff(
        self, worker: str, args: Optional[Dict[str, Any]] = None
    ) -> str:
        rt = self._runtime(worker)
        if not rt:
            return f"Error: Unknown worker '{worker}'"
        if rt.handoff_submitted:
            return f"Handoff already submitted for task {rt.task_id}"

        args = args or {}
        requested = self._status_from_string(args.get("status"))
        status = self._resolve_handoff_status(rt, requested)

        handoff = Handoff(
            handoff_id=f"h-{uuid.uuid4().hex[:10]}",
            agent_id=rt.worker,
            task_id=str(args.get("task_id") or rt.task_id),
            status=status,
            diff=dict(rt.diff),
            artifacts=self._dedupe(
                rt.artifacts
                + [a for a in args.get("artifacts", []) if isinstance(a, str)]
            )
            if isinstance(args.get("artifacts"), list)
            else list(rt.artifacts),
            metrics=HandoffMetrics(
                wall_time=max(time.time() - float(rt.started_at), 0.0),
                tokens_used=int(rt.tokens_used),
                attempts=int(rt.attempts),
                files_modified=len(rt.diff),
            ),
            watchdog_intervention=rt.watchdog_reason,
        )

        narrative_value = args.get("narrative")
        if isinstance(narrative_value, str) and narrative_value.strip():
            handoff.narrative = narrative_value.strip()
        else:
            handoff.narrative = self._compose_handoff_narrative(rt, status)

        HANDOFFS.append(handoff)
        rt.handoff_submitted = True

        ACTIVITY.log(
            worker,
            "handoff",
            rt.task_id,
            {"status": handoff.status.value, "handoff_id": handoff.handoff_id},
        )
        self._tool_call_logged(worker, "submit_handoff", {})

        BUS.send(
            sender=worker,
            to=self.planner_name,
            content=handoff.narrative,
            msg_type="handoff",
            extra={"handoff": handoff.to_dict()},
        )

        return f"Submitted handoff {handoff.handoff_id} ({handoff.status.value})"

    def _worker_exec(self, worker: str, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "bash":
            return self._run_worker_bash(worker, str(args.get("command", "")))
        if tool_name == "read_file":
            return self._run_worker_read(
                worker, str(args.get("path", "")), args.get("limit")
            )
        if tool_name == "write_file":
            return self._run_worker_write(
                worker, str(args.get("path", "")), str(args.get("content", ""))
            )
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
            content = str(args.get("content", ""))
            self._tool_call_logged(worker, "rewrite_scratchpad", {})
            return SCRATCHPADS.rewrite(worker, content)
        return f"Unknown worker tool: {tool_name}"

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
                "description": "Read file contents.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write or create file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Replace exact text in file.",
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
                "description": "Submit structured handoff to planner.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": [s.value for s in HandoffStatus],
                        },
                        "task_id": {"type": "string"},
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

    def _worker_loop(self, worker: str, task: str, task_id: str) -> None:
        rt = self._runtime(worker)
        if not rt:
            return

        system_prompt = WORKER_SYSTEM_TEMPLATE.format(
            name=worker, planner=self.planner_name
        )
        messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"<assignment>task_id={task_id}\\n{task}</assignment>\\n"
                    "Execute directly and submit handoff when complete."
                ),
            },
            {
                "role": "user",
                "content": f"<scratchpad>{SCRATCHPADS.read(worker) or '(empty scratchpad)'}</scratchpad>",
            },
        ]

        tools = self._worker_tools()
        self._heartbeat(worker, reason="start")

        for _ in range(MAX_WORKER_TURNS):
            latest_rt = self._runtime(worker)
            if not latest_rt:
                break
            if latest_rt.shutdown_requested:
                break

            inbox = BUS.read_inbox(worker)
            for msg in inbox:
                messages.append({"role": "user", "content": json.dumps(msg)})
                msg_type = str(msg.get("type", ""))
                if msg_type == "interrupt":
                    latest_rt.interrupted = True
                    if msg.get("reason"):
                        latest_rt.watchdog_reason = str(msg.get("reason"))

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
                    worker, {"status": HandoffStatus.FAILED.value, "task_id": task_id}
                )
                self._set_status(worker, "idle")
                return

            latest_rt.attempts += 1
            latest_rt.turns += 1
            input_tokens = int(getattr(response.usage, "input_tokens", 0))
            output_tokens = int(getattr(response.usage, "output_tokens", 0))
            used = input_tokens + output_tokens
            latest_rt.tokens_used += used
            latest_rt.tokens_since_tool_call += used

            ACTIVITY.log(
                worker,
                "llm_turn",
                latest_rt.task_id,
                {
                    "attempt": latest_rt.attempts,
                    "stop_reason": response.stop_reason,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "tokens_since_tool_call": latest_rt.tokens_since_tool_call,
                },
            )
            self._heartbeat(worker, reason="llm_turn")

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                latest_rt.last_text = "\n".join(
                    b.text
                    for b in response.content
                    if getattr(b, "type", None) == "text"
                ).strip()

                if latest_rt.interrupted and not latest_rt.handoff_submitted:
                    self._submit_handoff(
                        worker,
                        {
                            "status": HandoffStatus.PARTIAL_FAILURE.value,
                            "task_id": task_id,
                            "narrative": (
                                "Interrupted by watchdog before completion. "
                                "Submitting partial progress and diagnostics."
                            ),
                        },
                    )
                elif not latest_rt.handoff_submitted:
                    self._submit_handoff(worker, {"task_id": task_id})
                break

            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output = self._worker_exec(worker, block.name, block.input)
                print(f"  [{worker}] {block.name}: {str(output)[:120]}")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                )

            messages.append({"role": "user", "content": results})
            if latest_rt.handoff_submitted or latest_rt.shutdown_requested:
                break

            time.sleep(0.02)

        final_rt = self._runtime(worker)
        if final_rt and not final_rt.handoff_submitted:
            status = (
                HandoffStatus.PARTIAL_FAILURE.value
                if final_rt.shutdown_requested
                else HandoffStatus.SUCCESS.value
            )
            self._submit_handoff(worker, {"task_id": task_id, "status": status})

        self._set_status(worker, "idle")
        self._heartbeat(worker, reason="done")

    def list_workers(self) -> str:
        with self.worker_lock:
            if not self.workers:
                return "No workers."

            lines: List[str] = []
            for name in sorted(self.workers.keys()):
                rt = self.workers[name]
                status = self.worker_status.get(name, "unknown")
                inbox = BUS.count_pending(name)
                lines.append(
                    f"- {name}: status={status} task={rt.task_id} "
                    f"tokens={rt.tokens_used} since_tool={rt.tokens_since_tool_call} "
                    f"edits={sum(rt.edit_counts.values())} interrupted={rt.interrupted} inbox={inbox}"
                )
            return "\n".join(lines)

    def review_handoffs(
        self,
        worker: Optional[str] = None,
        task_id: Optional[str] = None,
        include_diff: bool = False,
    ) -> str:
        selected: List[Handoff] = []
        for handoff in HANDOFFS:
            if worker and handoff.agent_id != worker:
                continue
            if task_id and handoff.task_id != task_id:
                continue
            selected.append(handoff)

        if not selected:
            return "No handoffs found."

        out: List[Dict[str, Any]] = []
        for handoff in selected:
            item: Dict[str, Any] = {
                "handoff_id": handoff.handoff_id,
                "agent_id": handoff.agent_id,
                "task_id": handoff.task_id,
                "status": handoff.status.value,
                "narrative": handoff.narrative,
                "artifacts": handoff.artifacts,
                "watchdog_intervention": handoff.watchdog_intervention,
                "metrics": asdict(handoff.metrics),
            }
            if include_diff:
                item["diff"] = handoff.diff
            out.append(item)
        return json.dumps(out, indent=2)

    def planner_exec(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "spawn_worker":
            allowed_paths = args.get("allowed_paths")
            if not isinstance(allowed_paths, list):
                allowed_paths = []
            return self.spawn_worker(
                task=str(args.get("task", "")),
                name=str(args.get("name", "")).strip() or None,
                task_id=str(args.get("task_id", "")).strip() or None,
                allowed_paths=[str(p) for p in allowed_paths if isinstance(p, str)],
            )

        if tool_name == "review_handoff":
            return self.review_handoffs(
                worker=str(args.get("worker"))
                if args.get("worker") is not None
                else None,
                task_id=str(args.get("task_id"))
                if args.get("task_id") is not None
                else None,
                include_diff=bool(args.get("include_diff", False)),
            )

        if tool_name == "read_inbox":
            return json.dumps(BUS.read_inbox(self.planner_name), indent=2)

        if tool_name == "list_workers":
            return self.list_workers()

        if tool_name == "list_watchdog_reports":
            return self.list_watchdog_events(limit=int(args.get("limit", 25)))

        if tool_name == "stop_worker":
            worker = str(args.get("worker", "")).strip()
            if not worker:
                return "Error: missing worker"
            reason = str(args.get("reason", "planner requested stop")).strip()
            return self.request_shutdown(worker, reason=reason)

        if tool_name == "rewrite_scratchpad":
            return SCRATCHPADS.rewrite(self.planner_name, str(args.get("content", "")))

        if tool_name == "send_message":
            to = str(args.get("to", "")).strip()
            if not to:
                return "Error: missing 'to'"
            msg_type = str(args.get("msg_type", "message")).strip()
            if msg_type not in ("message", "broadcast"):
                return "Error: msg_type must be message or broadcast"
            return BUS.send(
                sender=self.planner_name,
                to=to,
                content=str(args.get("content", "")),
                msg_type=msg_type,
            )

        return f"Unknown planner tool: {tool_name}"

    def _planner_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "spawn_worker",
                "description": "Spawn worker for one concrete task.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "task": {"type": "string"},
                        "task_id": {"type": "string"},
                        "allowed_paths": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["task"],
                },
            },
            {
                "name": "review_handoff",
                "description": "Review handoffs from workers.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "worker": {"type": "string"},
                        "task_id": {"type": "string"},
                        "include_diff": {"type": "boolean"},
                    },
                },
            },
            {
                "name": "list_watchdog_reports",
                "description": "Read recent watchdog events.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer"},
                    },
                },
            },
            {
                "name": "stop_worker",
                "description": "Request worker shutdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "worker": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["worker"],
                },
            },
            {
                "name": "read_inbox",
                "description": "Read and drain planner inbox.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_workers",
                "description": "List workers and runtime metrics.",
                "input_schema": {"type": "object", "properties": {}},
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
                "description": "Send message to agent.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "content": {"type": "string"},
                        "msg_type": {
                            "type": "string",
                            "enum": ["message", "broadcast"],
                        },
                    },
                    "required": ["to", "content"],
                },
            },
        ]

    def planner_loop(self, messages: List[Dict[str, Any]]) -> None:
        tools = self._planner_tools()

        for _ in range(MAX_PLANNER_TURNS):
            inbox = BUS.read_inbox(self.planner_name)
            if inbox:
                messages.append(
                    {
                        "role": "user",
                        "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
                    }
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "I reviewed inbox updates and will continue.",
                    }
                )

            response = client.messages.create(
                model=MODEL,
                system=PLANNER_SYSTEM,
                messages=messages,
                tools=tools,
                max_tokens=8000,
            )
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return

            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output = self.planner_exec(block.name, block.input)
                print(f"> {block.name}: {str(output)[:180]}")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                )

            messages.append({"role": "user", "content": results})
            time.sleep(0.05)


class Watchdog(threading.Thread):
    def __init__(
        self, harness: FailureHarness, poll_seconds: float = WATCHDOG_INTERVAL
    ):
        super().__init__(daemon=True)
        self.harness = harness
        self.poll_seconds = max(poll_seconds, 0.5)
        self._stop_event = threading.Event()
        self._last_mode_for_worker: Dict[str, Tuple[FailureMode, float]] = {}

    def stop(self) -> None:
        self._stop_event.set()

    def _recently_handled(
        self, worker: str, mode: FailureMode, min_gap: float = 10.0
    ) -> bool:
        prev = self._last_mode_for_worker.get(worker)
        if not prev:
            return False
        prev_mode, prev_ts = prev
        return prev_mode == mode and (time.time() - prev_ts) < min_gap

    def _mark_handled(self, worker: str, mode: FailureMode) -> None:
        self._last_mode_for_worker[worker] = (mode, time.time())

    def _detect_zombie(self, rt: WorkerRuntime, now: float) -> Optional[str]:
        last_ts = ACTIVITY.last_timestamp(rt.worker)
        if last_ts is None:
            idle = now - rt.last_heartbeat
        else:
            idle = now - float(last_ts)

        if idle > ZOMBIE_SECONDS:
            return f"No activity for {idle:.1f}s (threshold={ZOMBIE_SECONDS:.1f}s)"
        return None

    def _detect_tunnel_vision(self, rt: WorkerRuntime) -> Optional[str]:
        recent_counts = ACTIVITY.recent_edit_counts(rt.worker, limit=220)
        if not recent_counts:
            return None

        top_path = ""
        top_count = 0
        for path, count in recent_counts.items():
            if count > top_count:
                top_path = path
                top_count = count

        if top_count > TUNNEL_EDITS:
            return (
                f"Tunnel vision detected: '{top_path}' edited {top_count} times "
                f"(threshold={TUNNEL_EDITS})"
            )
        return None

    def _detect_token_burn(self, rt: WorkerRuntime) -> Optional[str]:
        if rt.tokens_since_tool_call > TOKEN_BURN_TOKENS:
            return (
                "Token burn detected: "
                f"{rt.tokens_since_tool_call} tokens since last tool call "
                f"(threshold={TOKEN_BURN_TOKENS})"
            )
        return None

    def _check_worker(self, rt: WorkerRuntime) -> None:
        status = self.harness.worker_status.get(rt.worker, "unknown")
        if status not in ("working",):
            return
        if rt.handoff_submitted:
            return

        now = time.time()

        zombie_detail = self._detect_zombie(rt, now)
        if zombie_detail and not self._recently_handled(rt.worker, FailureMode.ZOMBIE):
            self._mark_handled(rt.worker, FailureMode.ZOMBIE)
            self.harness.kill_and_respawn(rt.worker, FailureMode.ZOMBIE, zombie_detail)
            return

        tunnel_detail = self._detect_tunnel_vision(rt)
        if tunnel_detail and not self._recently_handled(
            rt.worker, FailureMode.TUNNEL_VISION
        ):
            self._mark_handled(rt.worker, FailureMode.TUNNEL_VISION)
            self.harness.kill_and_respawn(
                rt.worker, FailureMode.TUNNEL_VISION, tunnel_detail
            )
            return

        burn_detail = self._detect_token_burn(rt)
        if burn_detail and not self._recently_handled(
            rt.worker, FailureMode.TOKEN_BURN
        ):
            self._mark_handled(rt.worker, FailureMode.TOKEN_BURN)
            self.harness.kill_and_respawn(
                rt.worker, FailureMode.TOKEN_BURN, burn_detail
            )
            return

    def run(self) -> None:
        while not self._stop_event.is_set():
            workers = self.harness.snapshot_workers()
            for rt in workers:
                self._check_worker(rt)
            self._stop_event.wait(self.poll_seconds)


HARNESS = FailureHarness(planner_name="planner")


def _print_workers() -> None:
    print(HARNESS.list_workers())


def _print_handoffs(include_diff: bool = False) -> None:
    print(HARNESS.review_handoffs(include_diff=include_diff))


def _print_watchdog(limit: int = 25) -> None:
    print(HARNESS.list_watchdog_events(limit=limit))


def _print_planner_inbox() -> None:
    print(json.dumps(BUS.read_inbox(HARNESS.planner_name), indent=2))


def _print_activity(worker: str, limit: int = 40) -> None:
    events = ACTIVITY.read_recent(worker, limit=limit)
    print(json.dumps(events, indent=2))


def _print_scratchpad(name: str) -> None:
    content = SCRATCHPADS.read(name)
    if not content:
        print(f"Scratchpad for {name} is empty")
        return
    print(content)


def _wait(seconds: int) -> None:
    deadline = time.time() + max(seconds, 0)
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    print("s19 failure modes")
    print(
        "Commands: /workers /handoffs /handoffs_diff /watchdog [/n] /inbox "
        "/activity <worker> [/n] /scratch <name> /spawn <task> /wait <sec> /q"
    )

    history: List[Dict[str, Any]] = []

    try:
        while True:
            try:
                query = input("\033[36ms19 >> \033[0m")
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

            if q.startswith("/watchdog"):
                parts = q.split(" ", 1)
                limit = 25
                if len(parts) == 2 and parts[1].strip().isdigit():
                    limit = int(parts[1].strip())
                _print_watchdog(limit=limit)
                continue

            if q == "/inbox":
                _print_planner_inbox()
                continue

            if q.startswith("/activity "):
                rest = q.split(" ", 1)[1].strip()
                if " " in rest:
                    who, raw_limit = rest.split(" ", 1)
                    lim = int(raw_limit.strip()) if raw_limit.strip().isdigit() else 40
                else:
                    who, lim = rest, 40
                _print_activity(worker=who, limit=lim)
                continue

            if q.startswith("/scratch "):
                who = q.split(" ", 1)[1].strip()
                _print_scratchpad(who)
                continue

            if q.startswith("/spawn "):
                task = q.split(" ", 1)[1].strip()
                print(HARNESS.spawn_worker(task=task))
                continue

            if q.startswith("/wait "):
                raw = q.split(" ", 1)[1].strip()
                secs = int(raw) if raw.isdigit() else 10
                _wait(secs)
                print(f"Waited {secs}s")
                continue

            history.append({"role": "user", "content": q})
            HARNESS.planner_loop(history)
            print()
    finally:
        HARNESS.shutdown()
