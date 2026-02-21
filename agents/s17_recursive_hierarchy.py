#!/usr/bin/env python3
"""
s17_recursive_hierarchy.py - Recursive Planner Hierarchy

Concept:
- Root planner -> SubPlanner -> Worker tree
- SubPlanners can spawn SubPlanners (recursive)
- Child handoffs are aggregated and bubbled upward
- Depth limit prevents infinite recursion
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

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

MAX_WORKER_TURNS = 40
MAX_PLANNER_TURNS = 50
MAX_SCRATCHPAD_CHARS = 9000
MAX_INLINE_OUTPUT = 50000
POLL_INTERVAL = 3
VALID_MSG_TYPES = {"message", "broadcast", "handoff"}

ROOT_SYSTEM = (
    f"You are ROOT PLANNER at {WORKDIR}. "
    "You decompose and delegate. You NEVER write code. "
    "Use sub-planners for subtrees and workers for leaf tasks."
)
SUBPLANNER_SYSTEM = (
    "You are SUBPLANNER '{name}' depth={depth} parent={parent}. "
    "Own one delegated subtree. You may spawn workers and deeper sub-planners within depth limit. "
    "You NEVER write code. Aggregate child handoffs and bubble upward."
)
WORKER_SYSTEM = (
    "You are WORKER '{name}' parent={parent}. "
    "Execute assigned task only. Do NOT decompose. Do NOT spawn. Submit handoff when done."
)


class AgentKind(str, Enum):
    ROOT = "root_planner"
    SUBPLANNER = "subplanner"
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
    handoff_id: str
    agent_id: str
    task_id: str
    status: HandoffStatus
    kind: AgentKind
    depth: int
    parent_id: Optional[str]
    aggregate: bool = False
    child_handoff_ids: List[str] = field(default_factory=list)
    diff: Dict[str, Dict[str, str]] = field(default_factory=dict)
    narrative: str = ""
    artifacts: List[str] = field(default_factory=list)
    metrics: HandoffMetrics = field(default_factory=HandoffMetrics)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["kind"] = self.kind.value
        return payload


@dataclass
class PlannerRuntime:
    name: str
    kind: AgentKind
    parent_id: Optional[str]
    depth: int
    task_id: str
    assigned_task: str
    started_at: float = field(default_factory=time.time)
    attempts: int = 0
    turns: int = 0
    tokens_used: int = 0
    child_ids: List[str] = field(default_factory=list)
    child_latest_handoff: Dict[str, str] = field(default_factory=dict)
    child_handoffs_in_order: List[str] = field(default_factory=list)
    aggregate_submitted: bool = False
    last_text: str = ""


@dataclass
class WorkerRuntime:
    name: str
    parent_id: str
    depth: int
    task_id: str
    assigned_task: str
    started_at: float = field(default_factory=time.time)
    attempts: int = 0
    turns: int = 0
    tokens_used: int = 0
    diff: Dict[str, Dict[str, str]] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    handoff_submitted: bool = False
    last_text: str = ""


class Scratchpads:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def read(self, name: str) -> str:
        p = self._path(name)
        if not p.exists():
            return ""
        return p.read_text()[:MAX_SCRATCHPAD_CHARS]

    def rewrite(self, name: str, content: str) -> str:
        text = content[:MAX_SCRATCHPAD_CHARS]
        p = self._path(name)
        p.write_text(text)
        return f"Scratchpad rewritten: {p} ({len(text)} chars)"


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
        p = self._path(name)
        if not p.exists():
            return []
        raw = p.read_text().strip()
        if not raw:
            p.write_text("")
            return []
        out: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            if line.strip():
                out.append(json.loads(line))
        p.write_text("")
        return out

    def count_pending(self, name: str) -> int:
        p = self._path(name)
        if not p.exists():
            return 0
        raw = p.read_text().strip()
        if not raw:
            return 0
        return len([ln for ln in raw.splitlines() if ln.strip()])


BUS = MessageBus(INBOX_DIR)
SCRATCHPADS = Scratchpads(SCRATCHPAD_DIR)
HANDOFFS: List[Handoff] = []


class RecursiveHierarchy:
    def __init__(self, root_name: str = "root", depth_limit: int = 3):
        self.root_name = root_name
        self.depth_limit = max(depth_limit, 1)

        self.planners: Dict[str, PlannerRuntime] = {}
        self.workers: Dict[str, WorkerRuntime] = {}

        self.agent_status: Dict[str, str] = {}
        self.agent_kind: Dict[str, AgentKind] = {}
        self.agent_parent: Dict[str, Optional[str]] = {}
        self.agent_depth: Dict[str, int] = {}

        self.planner_threads: Dict[str, threading.Thread] = {}
        self.worker_threads: Dict[str, threading.Thread] = {}

        self._bootstrap_root()

    # ---- bookkeeping ----

    def _bootstrap_root(self):
        rt = PlannerRuntime(
            name=self.root_name,
            kind=AgentKind.ROOT,
            parent_id=None,
            depth=0,
            task_id="root",
            assigned_task="Top-level decomposition and orchestration",
        )
        self.planners[self.root_name] = rt
        self.agent_status[self.root_name] = "idle"
        self.agent_kind[self.root_name] = AgentKind.ROOT
        self.agent_parent[self.root_name] = None
        self.agent_depth[self.root_name] = 0
        self._init_planner_scratchpad(rt)

    def _next_worker(self) -> str:
        i = 1
        while f"worker-{i}" in self.agent_kind:
            i += 1
        return f"worker-{i}"

    def _next_subplanner(self) -> str:
        i = 1
        while f"subplanner-{i}" in self.agent_kind:
            i += 1
        return f"subplanner-{i}"

    def _set_status(self, name: str, status: str):
        self.agent_status[name] = status

    def _safe_path(self, rel_path: str) -> Path:
        resolved = (WORKDIR / rel_path).resolve()
        if not resolved.is_relative_to(WORKDIR):
            raise ValueError(f"Path escapes workspace: {rel_path}")
        return resolved

    @staticmethod
    def _status_from_string(raw: Optional[str]) -> Optional[HandoffStatus]:
        if not raw:
            return None
        txt = raw.strip()
        for s in HandoffStatus:
            if s.value == txt:
                return s
        return None

    @staticmethod
    def _dedupe(values: List[str]) -> List[str]:
        seen = set()
        out = []
        for v in values:
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    def list_agents(self) -> str:
        lines = []
        for name in sorted(self.agent_kind.keys()):
            lines.append(
                f"- {name}: kind={self.agent_kind[name].value} "
                f"status={self.agent_status.get(name, 'unknown')} "
                f"depth={self.agent_depth.get(name, -1)} "
                f"parent={self.agent_parent.get(name) or '(none)'} "
                f"inbox={BUS.count_pending(name)}"
            )
        return "\n".join(lines) if lines else "No agents."

    # ---- scratchpads ----

    def _init_planner_scratchpad(self, rt: PlannerRuntime):
        role = "ROOT" if rt.kind == AgentKind.ROOT else "SUBPLANNER"
        parent = rt.parent_id or "(none)"
        SCRATCHPADS.rewrite(
            rt.name,
            (
                f"# Planner Scratchpad ({rt.name})\n\n"
                f"- Role: {role}\n"
                f"- Depth: {rt.depth}/{self.depth_limit}\n"
                f"- Parent: {parent}\n\n"
                "## Constraints\n"
                "- Planner never writes code\n"
                "- Delegates to workers/subplanners\n"
                "- Respects depth limit\n"
                "- Aggregates child handoffs upward\n\n"
                "## Assigned scope\n"
                f"- {rt.assigned_task}\n"
            ),
        )

    def _init_worker_scratchpad(self, rt: WorkerRuntime):
        SCRATCHPADS.rewrite(
            rt.name,
            (
                f"# Worker Scratchpad ({rt.name})\n\n"
                f"- Parent planner: {rt.parent_id}\n"
                f"- Depth: {rt.depth}\n\n"
                "## Constraints\n"
                "- Execute task\n"
                "- No decomposition\n"
                "- No spawning\n"
                "- Submit handoff\n\n"
                "## Assigned task\n"
                f"- {rt.assigned_task}\n"
            ),
        )

    # ---- worker file ops ----

    def _worker_error(self, worker: str, msg: str):
        self.workers[worker].errors.append(msg)

    def _worker_diff(self, worker: str, path: str, before: str, after: str):
        rt = self.workers[worker]
        if path in rt.diff:
            rt.diff[path] = {"before": rt.diff[path]["before"], "after": after}
        else:
            rt.diff[path] = {"before": before, "after": after}

    def _run_bash(self, worker: str, command: str) -> str:
        blocked = ["rm -rf /", "sudo", "shutdown", "reboot"]
        if any(b in command for b in blocked):
            self._worker_error(worker, f"bash blocked: {command}")
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
            return out[:MAX_INLINE_OUTPUT] if out else "(no output)"
        except subprocess.TimeoutExpired:
            self._worker_error(worker, f"bash timeout: {command}")
            return "Error: Timeout (120s)"
        except Exception as e:
            self._worker_error(worker, f"bash error: {e}")
            return f"Error: {e}"

    def _read_file(self, worker: str, path: str, limit: Optional[int]) -> str:
        try:
            lines = self._safe_path(path).read_text().splitlines()
            if limit is not None and limit > 0 and len(lines) > limit:
                lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
            return "\n".join(lines)[:MAX_INLINE_OUTPUT]
        except Exception as e:
            self._worker_error(worker, f"read_file({path}): {e}")
            return f"Error: {e}"

    def _write_file(self, worker: str, path: str, content: str) -> str:
        try:
            fp = self._safe_path(path)
            before = fp.read_text() if fp.exists() else ""
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
            self._worker_diff(worker, path, before, fp.read_text())
            self.workers[worker].artifacts.append(path)
            return f"Wrote {len(content)} bytes"
        except Exception as e:
            self._worker_error(worker, f"write_file({path}): {e}")
            return f"Error: {e}"

    def _edit_file(self, worker: str, path: str, old_text: str, new_text: str) -> str:
        try:
            fp = self._safe_path(path)
            before = fp.read_text()
            if old_text not in before:
                err = f"Text not found in {path}"
                self._worker_error(worker, f"edit_file({path}): {err}")
                return f"Error: {err}"
            fp.write_text(before.replace(old_text, new_text, 1))
            self._worker_diff(worker, path, before, fp.read_text())
            self.workers[worker].artifacts.append(path)
            return f"Edited {path}"
        except Exception as e:
            self._worker_error(worker, f"edit_file({path}): {e}")
            return f"Error: {e}"

    # ---- handoffs ----

    def _resolve_worker_status(self, rt: WorkerRuntime, requested: Optional[HandoffStatus]) -> HandoffStatus:
        if requested:
            return requested
        if not rt.errors:
            return HandoffStatus.SUCCESS
        if rt.errors and rt.diff:
            return HandoffStatus.PARTIAL_FAILURE
        txt = "\n".join(rt.errors).lower()
        if any(k in txt for k in ("blocked", "permission", "not found", "timeout")):
            return HandoffStatus.BLOCKED
        return HandoffStatus.FAILED

    def _compose_worker_narrative(self, rt: WorkerRuntime, status: HandoffStatus) -> str:
        payload = {
            "worker": rt.name,
            "parent": rt.parent_id,
            "task_id": rt.task_id,
            "status": status.value,
            "files_modified": len(rt.diff),
            "artifacts": rt.artifacts,
            "errors": rt.errors[-5:],
            "assistant_final_text": rt.last_text,
            "diff_files": list(rt.diff.keys()),
        }
        try:
            resp = client.messages.create(
                model=MODEL,
                system=(
                    "Write concise worker handoff narrative. "
                    "Include what changed, what did not, risk, and one next step. "
                    "Plain text <= 10 lines."
                ),
                messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
                max_tokens=450,
            )
            rt.tokens_used += getattr(resp.usage, "input_tokens", 0)
            rt.tokens_used += getattr(resp.usage, "output_tokens", 0)
            text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
            if text:
                return text
        except Exception as e:
            rt.errors.append(f"narrative_generation: {e}")

        changed = ", ".join(rt.diff.keys()) if rt.diff else "no files"
        lines = [
            f"Worker {rt.name} finished task {rt.task_id} with status {status.value}.",
            f"Changed: {changed}.",
        ]
        if rt.errors:
            lines.append(f"Latest error: {rt.errors[-1]}")
        if rt.last_text:
            lines.append(f"Final output: {rt.last_text[:220]}")
        lines.append("Next step: planner reviews diff and sets follow-up.")
        return "\n".join(lines)

    def _build_worker_handoff(self, rt: WorkerRuntime, requested: Optional[HandoffStatus]) -> Handoff:
        status = self._resolve_worker_status(rt, requested)
        handoff = Handoff(
            handoff_id=f"h-{uuid.uuid4().hex[:10]}",
            agent_id=rt.name,
            task_id=rt.task_id,
            status=status,
            kind=AgentKind.WORKER,
            depth=rt.depth,
            parent_id=rt.parent_id,
            aggregate=False,
            diff=dict(rt.diff),
            artifacts=self._dedupe(rt.artifacts),
            metrics=HandoffMetrics(
                wall_time=max(time.time() - rt.started_at, 0.0),
                tokens_used=rt.tokens_used,
                attempts=rt.attempts,
                files_modified=len(rt.diff),
            ),
        )
        handoff.narrative = self._compose_worker_narrative(rt, status)
        return handoff

    def _merge_child_diffs(self, handoffs: List[Handoff]) -> Dict[str, Dict[str, str]]:
        merged: Dict[str, Dict[str, str]] = {}
        for handoff in handoffs:
            for path, delta in handoff.diff.items():
                before = delta.get("before", "")
                after = delta.get("after", "")
                if path in merged:
                    merged[path] = {"before": merged[path]["before"], "after": after}
                else:
                    merged[path] = {"before": before, "after": after}
        return merged

    @staticmethod
    def _resolve_aggregate_status(handoffs: List[Handoff]) -> HandoffStatus:
        if not handoffs:
            return HandoffStatus.BLOCKED
        statuses = [h.status for h in handoffs]
        if all(s == HandoffStatus.SUCCESS for s in statuses):
            return HandoffStatus.SUCCESS
        if any(s == HandoffStatus.FAILED for s in statuses):
            return HandoffStatus.FAILED
        if any(s == HandoffStatus.BLOCKED for s in statuses):
            return HandoffStatus.BLOCKED
        return HandoffStatus.PARTIAL_FAILURE

    def _compose_aggregate_narrative(
        self,
        planner: PlannerRuntime,
        child_handoffs: List[Handoff],
        status: HandoffStatus,
    ) -> str:
        payload = {
            "planner": planner.name,
            "depth": planner.depth,
            "task_id": planner.task_id,
            "status": status.value,
            "children": [
                {
                    "agent": h.agent_id,
                    "kind": h.kind.value,
                    "status": h.status.value,
                    "task_id": h.task_id,
                    "files_modified": h.metrics.files_modified,
                    "narrative": h.narrative,
                }
                for h in child_handoffs
            ],
        }
        try:
            resp = client.messages.create(
                model=MODEL,
                system=(
                    "Write one aggregate handoff narrative for parent planner. "
                    "Compress child handoffs to concise status/risk/next-step update. "
                    "Plain text <= 12 lines."
                ),
                messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
                max_tokens=650,
            )
            planner.tokens_used += getattr(resp.usage, "input_tokens", 0)
            planner.tokens_used += getattr(resp.usage, "output_tokens", 0)
            text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
            if text:
                return text
        except Exception:
            pass

        lines = [
            f"SubPlanner {planner.name} aggregated {len(child_handoffs)} child handoffs ({status.value}).",
            "Children:",
        ]
        for h in child_handoffs[:6]:
            lines.append(f"- {h.agent_id} ({h.kind.value}) {h.status.value} task={h.task_id}")
        if len(child_handoffs) > 6:
            lines.append(f"- ... and {len(child_handoffs) - 6} more")
        lines.append("Next step: parent planner reconciles and delegates follow-up.")
        return "\n".join(lines)

    def _handoff_by_id(self, handoff_id: str) -> Optional[Handoff]:
        for h in HANDOFFS:
            if h.handoff_id == handoff_id:
                return h
        return None

    def _store_handoff(self, handoff: Handoff):
        HANDOFFS.append(handoff)

    def review_handoffs(
        self,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None,
        include_diff: bool = False,
    ) -> str:
        out = []
        for h in HANDOFFS:
            if agent_id and h.agent_id != agent_id:
                continue
            if task_id and h.task_id != str(task_id):
                continue
            item: Dict[str, Any] = {
                "handoff_id": h.handoff_id,
                "agent_id": h.agent_id,
                "kind": h.kind.value,
                "depth": h.depth,
                "parent_id": h.parent_id,
                "task_id": h.task_id,
                "status": h.status.value,
                "aggregate": h.aggregate,
                "child_handoff_ids": h.child_handoff_ids,
                "narrative": h.narrative,
                "artifacts": h.artifacts,
                "metrics": asdict(h.metrics),
            }
            if include_diff:
                item["diff"] = h.diff
            out.append(item)
        return json.dumps(out, indent=2) if out else "No handoffs found."

    # ---- spawn ----

    def spawn_worker(self, parent_planner: str, task: str, name: Optional[str], task_id: Optional[str]) -> str:
        parent = self.planners.get(parent_planner)
        if not parent:
            return f"Error: Unknown planner '{parent_planner}'"
        worker = name.strip() if isinstance(name, str) and name.strip() else self._next_worker()
        if worker in self.agent_kind and self.agent_status.get(worker) not in ("idle", "shutdown"):
            return f"Error: '{worker}' is currently {self.agent_status.get(worker)}"

        rt = WorkerRuntime(
            name=worker,
            parent_id=parent_planner,
            depth=parent.depth + 1,
            task_id=task_id or str(uuid.uuid4())[:8],
            assigned_task=task,
        )
        self.workers[worker] = rt
        self.agent_kind[worker] = AgentKind.WORKER
        self.agent_parent[worker] = parent_planner
        self.agent_depth[worker] = rt.depth
        self.agent_status[worker] = "working"
        if worker not in parent.child_ids:
            parent.child_ids.append(worker)
        parent.aggregate_submitted = False

        self._init_worker_scratchpad(rt)
        thread = threading.Thread(target=self._worker_loop, args=(worker, task, rt.task_id), daemon=True)
        self.worker_threads[worker] = thread
        thread.start()
        return f"Spawned worker '{worker}' under {parent_planner} (task_id={rt.task_id})"

    def spawn_subplanner(self, parent_planner: str, task: str, name: Optional[str], task_id: Optional[str]) -> str:
        parent = self.planners.get(parent_planner)
        if not parent:
            return f"Error: Unknown planner '{parent_planner}'"
        depth = parent.depth + 1
        if depth > self.depth_limit:
            return (
                f"Error: Depth limit reached. parent={parent_planner} "
                f"depth={parent.depth} limit={self.depth_limit}"
            )

        sub = name.strip() if isinstance(name, str) and name.strip() else self._next_subplanner()
        if sub in self.agent_kind and self.agent_status.get(sub) not in ("idle", "shutdown"):
            return f"Error: '{sub}' is currently {self.agent_status.get(sub)}"

        rt = PlannerRuntime(
            name=sub,
            kind=AgentKind.SUBPLANNER,
            parent_id=parent_planner,
            depth=depth,
            task_id=task_id or str(uuid.uuid4())[:8],
            assigned_task=task,
        )
        self.planners[sub] = rt
        self.agent_kind[sub] = AgentKind.SUBPLANNER
        self.agent_parent[sub] = parent_planner
        self.agent_depth[sub] = depth
        self.agent_status[sub] = "working"
        if sub not in parent.child_ids:
            parent.child_ids.append(sub)
        parent.aggregate_submitted = False

        self._init_planner_scratchpad(rt)
        thread = threading.Thread(target=self._subplanner_loop, args=(sub, task, rt.task_id), daemon=True)
        self.planner_threads[sub] = thread
        thread.start()
        return (
            f"Spawned subplanner '{sub}' under {parent_planner} "
            f"(depth={depth}/{self.depth_limit}, task_id={rt.task_id})"
        )

    # ---- bubble logic ----

    def _children_done(self, planner: PlannerRuntime) -> bool:
        if not planner.child_ids:
            return False
        for child in planner.child_ids:
            if child not in planner.child_latest_handoff:
                return False
            if self.agent_status.get(child, "unknown") not in ("idle", "shutdown"):
                return False
        return True

    def _submit_aggregate_handoff(self, planner_name: str) -> str:
        planner = self.planners.get(planner_name)
        if not planner:
            return f"Error: Unknown planner '{planner_name}'"
        if planner.kind == AgentKind.ROOT:
            return "Root planner does not bubble upward."
        if not planner.parent_id:
            return "Error: Subplanner has no parent."

        child_handoffs: List[Handoff] = []
        for child in planner.child_ids:
            hid = planner.child_latest_handoff.get(child)
            if not hid:
                continue
            h = self._handoff_by_id(hid)
            if h:
                child_handoffs.append(h)
        if not child_handoffs:
            return f"Error: No child handoffs available for {planner_name}"

        status = self._resolve_aggregate_status(child_handoffs)
        diff = self._merge_child_diffs(child_handoffs)
        artifacts: List[str] = []
        for h in child_handoffs:
            artifacts.extend(h.artifacts)

        agg = Handoff(
            handoff_id=f"h-{uuid.uuid4().hex[:10]}",
            agent_id=planner.name,
            task_id=planner.task_id,
            status=status,
            kind=AgentKind.SUBPLANNER,
            depth=planner.depth,
            parent_id=planner.parent_id,
            aggregate=True,
            child_handoff_ids=[h.handoff_id for h in child_handoffs],
            diff=diff,
            artifacts=self._dedupe(artifacts),
            metrics=HandoffMetrics(
                wall_time=max(time.time() - planner.started_at, 0.0),
                tokens_used=planner.tokens_used,
                attempts=planner.attempts,
                files_modified=len(diff),
            ),
        )
        agg.narrative = self._compose_aggregate_narrative(planner, child_handoffs, status)
        self._store_handoff(agg)
        planner.aggregate_submitted = True

        BUS.send(
            sender=planner.name,
            to=planner.parent_id,
            content=agg.narrative,
            msg_type="handoff",
            extra={"handoff": agg.to_dict()},
        )
        return f"Aggregate handoff submitted {agg.handoff_id} ({agg.status.value})"

    def _process_planner_inbox(self, planner_name: str, messages: List[Dict[str, Any]]):
        planner = self.planners[planner_name]
        inbox = BUS.read_inbox(planner_name)
        if not inbox:
            return

        for msg in inbox:
            messages.append({"role": "user", "content": json.dumps(msg)})
            if msg.get("type") != "handoff":
                continue
            payload = msg.get("handoff")
            if not isinstance(payload, dict):
                continue
            child = str(payload.get("agent_id", "")).strip()
            hid = str(payload.get("handoff_id", "")).strip()
            if not child or not hid:
                continue
            if child not in planner.child_ids:
                planner.child_ids.append(child)
            planner.child_latest_handoff[child] = hid
            planner.child_handoffs_in_order.append(hid)

        if planner.kind == AgentKind.SUBPLANNER:
            if not planner.aggregate_submitted and self._children_done(planner):
                out = self._submit_aggregate_handoff(planner_name)
                print(f"  [{planner_name}] auto_aggregate: {out[:140]}")

    # ---- tools ----

    def _planner_tools(self, planner_name: str) -> List[Dict[str, Any]]:
        planner = self.planners[planner_name]
        tools = [
            {
                "name": "spawn_worker",
                "description": "Spawn a worker for one concrete task.",
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
                "description": "Review handoffs from children.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "task_id": {"type": "string"},
                        "include_diff": {"type": "boolean"},
                    },
                },
            },
            {
                "name": "read_inbox",
                "description": "Read and drain planner inbox.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_agents",
                "description": "List hierarchy agents and states.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "list_children",
                "description": "List direct children of this planner.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "rewrite_scratchpad",
                "description": "Rewrite planner scratchpad by replacement.",
                "input_schema": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
            },
            {
                "name": "send_message",
                "description": "Send direct message to child.",
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
        ]
        if planner.depth < self.depth_limit:
            tools.append(
                {
                    "name": "spawn_subplanner",
                    "description": "Spawn sub-planner for delegated subtree.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "task": {"type": "string"},
                            "task_id": {"type": "string"},
                        },
                        "required": ["task"],
                    },
                }
            )
        if planner.kind == AgentKind.SUBPLANNER:
            tools.append(
                {
                    "name": "aggregate_handoffs",
                    "description": "Aggregate child handoffs and bubble upward.",
                    "input_schema": {"type": "object", "properties": {}},
                }
            )
        return tools

    @staticmethod
    def _worker_tools() -> List[Dict[str, Any]]:
        return [
            {
                "name": "bash",
                "description": "Run shell command.",
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
                    "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write/create file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
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
                "description": "Submit structured handoff to parent planner.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": [s.value for s in HandoffStatus]},
                        "task_id": {"type": "string"},
                        "narrative": {"type": "string"},
                        "artifacts": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            {
                "name": "rewrite_scratchpad",
                "description": "Rewrite worker scratchpad by replacement.",
                "input_schema": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
            },
        ]

    def planner_exec(self, planner_name: str, tool_name: str, args: Dict[str, Any]) -> str:
        if planner_name not in self.planners:
            return f"Error: Unknown planner '{planner_name}'"

        if tool_name == "spawn_worker":
            return self.spawn_worker(
                parent_planner=planner_name,
                task=str(args.get("task", "")),
                name=str(args.get("name", "")).strip() or None,
                task_id=str(args.get("task_id", "")).strip() or None,
            )
        if tool_name == "spawn_subplanner":
            return self.spawn_subplanner(
                parent_planner=planner_name,
                task=str(args.get("task", "")),
                name=str(args.get("name", "")).strip() or None,
                task_id=str(args.get("task_id", "")).strip() or None,
            )
        if tool_name == "review_handoff":
            return self.review_handoffs(
                agent_id=str(args.get("agent_id")) if args.get("agent_id") is not None else None,
                task_id=str(args.get("task_id")) if args.get("task_id") is not None else None,
                include_diff=bool(args.get("include_diff", False)),
            )
        if tool_name == "read_inbox":
            return json.dumps(BUS.read_inbox(planner_name), indent=2)
        if tool_name == "list_agents":
            return self.list_agents()
        if tool_name == "list_children":
            return json.dumps({"planner": planner_name, "children": self.planners[planner_name].child_ids}, indent=2)
        if tool_name == "aggregate_handoffs":
            return self._submit_aggregate_handoff(planner_name)
        if tool_name == "rewrite_scratchpad":
            return SCRATCHPADS.rewrite(planner_name, str(args.get("content", "")))
        if tool_name == "send_message":
            to = str(args.get("to", "")).strip()
            if not to:
                return "Error: missing 'to'"
            msg_type = str(args.get("msg_type", "message")).strip()
            if msg_type not in ("message", "broadcast"):
                return "Error: msg_type must be 'message' or 'broadcast'"
            return BUS.send(
                sender=planner_name,
                to=to,
                content=str(args.get("content", "")),
                msg_type=msg_type,
            )
        return f"Unknown planner tool: {tool_name}"

    def _submit_worker_handoff(self, worker_name: str, args: Optional[Dict[str, Any]] = None) -> str:
        rt = self.workers[worker_name]
        if rt.handoff_submitted:
            return f"Handoff already submitted for task {rt.task_id}"

        args = args or {}
        requested = self._status_from_string(args.get("status"))
        handoff = self._build_worker_handoff(rt, requested)
        if isinstance(args.get("task_id"), str) and args.get("task_id").strip():
            handoff.task_id = args["task_id"].strip()
        if isinstance(args.get("narrative"), str) and args.get("narrative").strip():
            handoff.narrative = args["narrative"].strip()
        if isinstance(args.get("artifacts"), list):
            extra = [a for a in args["artifacts"] if isinstance(a, str)]
            handoff.artifacts = self._dedupe(handoff.artifacts + extra)

        self._store_handoff(handoff)
        rt.handoff_submitted = True
        BUS.send(
            sender=worker_name,
            to=rt.parent_id,
            content=handoff.narrative,
            msg_type="handoff",
            extra={"handoff": handoff.to_dict()},
        )
        return f"Submitted handoff {handoff.handoff_id} ({handoff.status.value})"

    def worker_exec(self, worker_name: str, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "bash":
            return self._run_bash(worker_name, str(args.get("command", "")))
        if tool_name == "read_file":
            return self._read_file(worker_name, str(args.get("path", "")), args.get("limit"))
        if tool_name == "write_file":
            return self._write_file(worker_name, str(args.get("path", "")), str(args.get("content", "")))
        if tool_name == "edit_file":
            return self._edit_file(
                worker_name,
                str(args.get("path", "")),
                str(args.get("old_text", "")),
                str(args.get("new_text", "")),
            )
        if tool_name == "submit_handoff":
            return self._submit_worker_handoff(worker_name, args)
        if tool_name == "rewrite_scratchpad":
            return SCRATCHPADS.rewrite(worker_name, str(args.get("content", "")))
        return f"Unknown worker tool: {tool_name}"

    # ---- loops ----

    def _worker_loop(self, worker_name: str, task: str, task_id: str):
        rt = self.workers[worker_name]
        rt.task_id = task_id
        rt.started_at = time.time()

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
                "content": f"<scratchpad>{SCRATCHPADS.read(worker_name) or '(empty scratchpad)'}</scratchpad>",
            },
        ]
        system = WORKER_SYSTEM.format(name=worker_name, parent=rt.parent_id)

        for _ in range(MAX_WORKER_TURNS):
            inbox = BUS.read_inbox(worker_name)
            for msg in inbox:
                messages.append({"role": "user", "content": json.dumps(msg)})

            try:
                resp = client.messages.create(
                    model=MODEL,
                    system=system,
                    messages=messages,
                    tools=self._worker_tools(),
                    max_tokens=6000,
                )
            except Exception as e:
                rt.errors.append(f"llm_call: {e}")
                self._submit_worker_handoff(worker_name, {"status": HandoffStatus.FAILED.value, "task_id": task_id})
                self._set_status(worker_name, "idle")
                return

            rt.attempts += 1
            rt.turns += 1
            rt.tokens_used += getattr(resp.usage, "input_tokens", 0)
            rt.tokens_used += getattr(resp.usage, "output_tokens", 0)
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                rt.last_text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
                if not rt.handoff_submitted:
                    self._submit_worker_handoff(worker_name, {"task_id": task_id})
                break

            results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output = self.worker_exec(worker_name, block.name, block.input)
                print(f"  [{worker_name}] {block.name}: {str(output)[:120]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
            messages.append({"role": "user", "content": results})

            if rt.handoff_submitted:
                break

        if not rt.handoff_submitted:
            self._submit_worker_handoff(worker_name, {"task_id": task_id})
        self._set_status(worker_name, "idle")

    def _subplanner_loop(self, planner_name: str, task: str, task_id: str):
        planner = self.planners[planner_name]
        planner.task_id = task_id
        planner.assigned_task = task
        planner.started_at = time.time()

        messages: List[Dict[str, Any]] = [
            {
                "role": "user",
                "content": (
                    f"<assignment>task_id={task_id}\\n{task}</assignment>\\n"
                    "Decompose subtree. Delegate to workers/subplanners. Aggregate handoffs upward."
                ),
            },
            {
                "role": "user",
                "content": f"<depth_limit>current={planner.depth} max={self.depth_limit}</depth_limit>",
            },
            {
                "role": "user",
                "content": f"<scratchpad>{SCRATCHPADS.read(planner_name) or '(empty scratchpad)'}</scratchpad>",
            },
        ]
        system = SUBPLANNER_SYSTEM.format(name=planner_name, depth=planner.depth, parent=planner.parent_id)

        for _ in range(MAX_PLANNER_TURNS):
            self._process_planner_inbox(planner_name, messages)
            if planner.aggregate_submitted and self._children_done(planner):
                break

            try:
                resp = client.messages.create(
                    model=MODEL,
                    system=system,
                    messages=messages,
                    tools=self._planner_tools(planner_name),
                    max_tokens=7000,
                )
            except Exception:
                break

            planner.attempts += 1
            planner.turns += 1
            planner.tokens_used += getattr(resp.usage, "input_tokens", 0)
            planner.tokens_used += getattr(resp.usage, "output_tokens", 0)
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                planner.last_text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
                if not planner.aggregate_submitted and self._children_done(planner):
                    out = self._submit_aggregate_handoff(planner_name)
                    print(f"  [{planner_name}] aggregate: {out[:140]}")
                break

            results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output = self.planner_exec(planner_name, block.name, block.input)
                print(f"  [{planner_name}] {block.name}: {str(output)[:120]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
            messages.append({"role": "user", "content": results})

        if not planner.aggregate_submitted and self._children_done(planner):
            out = self._submit_aggregate_handoff(planner_name)
            print(f"  [{planner_name}] final_aggregate: {out[:140]}")
        self._set_status(planner_name, "idle")

    def root_loop(self, messages: List[Dict[str, Any]]):
        root = self.planners[self.root_name]
        while True:
            self._process_planner_inbox(self.root_name, messages)

            resp = client.messages.create(
                model=MODEL,
                system=ROOT_SYSTEM,
                messages=messages,
                tools=self._planner_tools(self.root_name),
                max_tokens=8000,
            )
            root.attempts += 1
            root.turns += 1
            root.tokens_used += getattr(resp.usage, "input_tokens", 0)
            root.tokens_used += getattr(resp.usage, "output_tokens", 0)
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                root.last_text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
                return

            results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                output = self.planner_exec(self.root_name, block.name, block.input)
                print(f"> {block.name}: {str(output)[:180]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
            messages.append({"role": "user", "content": results})


HIERARCHY = RecursiveHierarchy(root_name="root", depth_limit=3)


def _print_agents():
    print(HIERARCHY.list_agents())


def _print_handoffs(include_diff: bool = False):
    print(HIERARCHY.review_handoffs(include_diff=include_diff))


def _print_inbox(name: str):
    print(json.dumps(BUS.read_inbox(name), indent=2))


def _print_scratchpad(name: str):
    text = SCRATCHPADS.read(name)
    if not text:
        print(f"Scratchpad for {name} is empty")
    else:
        print(text)


def _demo_prompt() -> str:
    return (
        "You are root planner. Build recursive hierarchy for this goal: "
        "create a tiny Python package with module + test. "
        "Delegate source work to one subtree and test/docs work to another subtree. "
        "Use recursive subplanners only when needed, obey depth limit, and reconcile handoffs."
    )


def _sleep_for_agents(seconds: int):
    end = time.time() + max(seconds, 0)
    while time.time() < end:
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    print("s17 recursive hierarchy")
    print("Commands: /agents /handoffs /handoffs_diff /inbox <name> /scratch <name> /demo /wait <sec> /q")

    history: List[Dict[str, Any]] = []
    while True:
        try:
            query = input("\033[36ms17 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break

        q = query.strip()
        if q.lower() in ("q", "exit", "/q", ""):
            break
        if q == "/agents":
            _print_agents()
            continue
        if q == "/handoffs":
            _print_handoffs(include_diff=False)
            continue
        if q == "/handoffs_diff":
            _print_handoffs(include_diff=True)
            continue
        if q.startswith("/inbox "):
            _print_inbox(q.split(" ", 1)[1].strip())
            continue
        if q.startswith("/scratch "):
            _print_scratchpad(q.split(" ", 1)[1].strip())
            continue
        if q == "/demo":
            history.append({"role": "user", "content": _demo_prompt()})
            HIERARCHY.root_loop(history)
            print()
            continue
        if q.startswith("/wait "):
            raw = q.split(" ", 1)[1].strip()
            sec = int(raw) if raw.isdigit() else 5
            print(f"Waiting {sec}s for child agents...")
            _sleep_for_agents(sec)
            continue

        history.append({"role": "user", "content": query})
        HIERARCHY.root_loop(history)
        print()
