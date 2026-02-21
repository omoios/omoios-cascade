#!/usr/bin/env python3
"""
s12_structured_handoffs.py - Structured Handoffs

Workers submit structured handoffs upward with:
- status
- diff (file-based before/after)
- narrative
- artifacts
- metrics
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

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-5-20250929")
TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
TASKS_DIR = WORKDIR / ".tasks"
POLL_INTERVAL = 5
IDLE_TIMEOUT = 60

SYSTEM = f"You are a team lead at {WORKDIR}. Workers submit structured handoffs."


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

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
    "handoff",
}
shutdown_requests: Dict[str, Dict[str, Any]] = {}
plan_requests: Dict[str, Dict[str, Any]] = {}
HANDOFFS: List[Handoff] = []


class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str, msg_type: str = "message", extra: Optional[dict] = None) -> str:
        if msg_type not in VALID_MSG_TYPES:
            return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"
        msg = {"type": msg_type, "from": sender, "content": content, "timestamp": time.time()}
        if extra:
            msg.update(extra)
        inbox_path = self.dir / f"{to}.jsonl"
        with open(inbox_path, "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        inbox_path = self.dir / f"{name}.jsonl"
        if not inbox_path.exists():
            return []
        messages = []
        for line in inbox_path.read_text().strip().splitlines():
            if line:
                messages.append(json.loads(line))
        inbox_path.write_text("")
        return messages

    def broadcast(self, sender: str, content: str, teammates: list) -> str:
        count = 0
        for name in teammates:
            if name != sender:
                self.send(sender, name, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"


BUS = MessageBus(INBOX_DIR)


def scan_unclaimed_tasks() -> list:
    TASKS_DIR.mkdir(exist_ok=True)
    unclaimed = []
    for f in sorted(TASKS_DIR.glob("task_*.json")):
        task = json.loads(f.read_text())
        if task.get("status") == "pending" and not task.get("owner") and not task.get("blockedBy"):
            unclaimed.append(task)
    return unclaimed


def claim_task(task_id: int, owner: str) -> str:
    path = TASKS_DIR / f"task_{task_id}.json"
    if not path.exists():
        return f"Error: Task {task_id} not found"
    task = json.loads(path.read_text())
    task["owner"] = owner
    task["status"] = "in_progress"
    path.write_text(json.dumps(task, indent=2))
    return f"Claimed task #{task_id} for {owner}"


def _read_task(task_id: str) -> Optional[Dict[str, Any]]:
    if not task_id or task_id == "none":
        return None
    path = TASKS_DIR / f"task_{task_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def make_identity_block(name: str, role: str, team_name: str) -> dict:
    return {"role": "user", "content": f"<identity>You are '{name}', role: {role}, team: {team_name}. Continue your work.</identity>"}


def _status_from_string(raw: Optional[str]) -> Optional[HandoffStatus]:
    if not raw:
        return None
    normalized = raw.strip()
    for status in HandoffStatus:
        if status.value == normalized:
            return status
    return None


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


class TeammateManager:
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.dir.mkdir(exist_ok=True)
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()
        self.threads: Dict[str, threading.Thread] = {}
        self.worker_runtime: Dict[str, Dict[str, Any]] = {}

    def _load_config(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save_config(self):
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find_member(self, name: str) -> Optional[dict]:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def _set_status(self, name: str, status: str):
        member = self._find_member(name)
        if member:
            member["status"] = status
            self._save_config()

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find_member(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save_config()
        self.worker_runtime[name] = {
            "task_id": "none",
            "task_started_at": time.time(),
            "attempts": 0,
            "tokens_used": 0,
            "diff": {},
            "artifacts": [],
            "errors": [],
            "last_text": "",
            "handoff_submitted": False,
        }
        thread = threading.Thread(target=self._loop, args=(name, role, prompt), daemon=True)
        self.threads[name] = thread
        thread.start()
        return f"Spawned '{name}' (role: {role})"

    def _runtime(self, name: str) -> Dict[str, Any]:
        if name not in self.worker_runtime:
            self.worker_runtime[name] = {
                "task_id": "none",
                "task_started_at": time.time(),
                "attempts": 0,
                "tokens_used": 0,
                "diff": {},
                "artifacts": [],
                "errors": [],
                "last_text": "",
                "handoff_submitted": False,
            }
        return self.worker_runtime[name]

    def _reset_task_runtime(self, name: str, task_id: str):
        rt = self._runtime(name)
        rt["task_id"] = str(task_id)
        rt["task_started_at"] = time.time()
        rt["attempts"] = 0
        rt["tokens_used"] = 0
        rt["diff"] = {}
        rt["artifacts"] = []
        rt["errors"] = []
        rt["last_text"] = ""
        rt["handoff_submitted"] = False

    def _record_diff(self, name: str, path: str, before: str, after: str):
        rt = self._runtime(name)
        diff: Dict[str, Dict[str, str]] = rt["diff"]
        if path in diff:
            diff[path] = {"before": diff[path]["before"], "after": after}
        else:
            diff[path] = {"before": before, "after": after}

    def _record_error(self, name: str, err: str):
        self._runtime(name)["errors"].append(err)

    def _tracked_write(self, name: str, path: str, content: str) -> str:
        try:
            fp = _safe_path(path)
            before = fp.read_text() if fp.exists() else ""
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
            self._record_diff(name, path, before, fp.read_text())
            self._runtime(name)["artifacts"].append(path)
            return f"Wrote {len(content)} bytes"
        except Exception as e:
            self._record_error(name, f"write_file({path}): {e}")
            return f"Error: {e}"

    def _tracked_edit(self, name: str, path: str, old_text: str, new_text: str) -> str:
        try:
            fp = _safe_path(path)
            before = fp.read_text()
            if old_text not in before:
                err = f"Text not found in {path}"
                self._record_error(name, f"edit_file({path}): {err}")
                return f"Error: {err}"
            fp.write_text(before.replace(old_text, new_text, 1))
            self._record_diff(name, path, before, fp.read_text())
            self._runtime(name)["artifacts"].append(path)
            return f"Edited {path}"
        except Exception as e:
            self._record_error(name, f"edit_file({path}): {e}")
            return f"Error: {e}"

    def _compose_handoff_narrative(self, name: str, handoff: Handoff, final_text: str) -> str:
        rt = self._runtime(name)
        errors: List[str] = rt["errors"]
        task = _read_task(handoff.task_id)
        prompt = {
            "agent_id": handoff.agent_id,
            "task_id": handoff.task_id,
            "task_subject": task.get("subject") if task else "(unknown)",
            "status": handoff.status.value,
            "files_modified": handoff.metrics.files_modified,
            "artifacts": handoff.artifacts,
            "errors": errors[-5:],
            "assistant_final_text": final_text,
            "diff_files": list(handoff.diff.keys()),
        }
        try:
            response = client.messages.create(
                model=MODEL,
                system=(
                    "You write worker handoff narratives for a lead. "
                    "Output plain text only, <= 8 lines. Include what changed, "
                    "what did not, notable risks, and next step."
                ),
                messages=[{"role": "user", "content": json.dumps(prompt, indent=2)}],
                max_tokens=400,
            )
            rt["tokens_used"] += getattr(response.usage, "input_tokens", 0) + getattr(response.usage, "output_tokens", 0)
            text_chunks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            narrative = "\n".join(text_chunks).strip()
            if narrative:
                return narrative
        except Exception as e:
            self._record_error(name, f"narrative_generation: {e}")
        changed = ", ".join(handoff.diff.keys()) if handoff.diff else "no files"
        fallback = [
            f"Agent {handoff.agent_id} completed task {handoff.task_id} with status {handoff.status.value}.",
            f"Changed: {changed}.",
        ]
        if errors:
            fallback.append(f"Errors: {errors[-1]}")
        if final_text:
            fallback.append(f"Final output: {final_text[:240]}")
        fallback.append("Next step: lead should review the diff and assign follow-up if needed.")
        return "\n".join(fallback)

    def _resolve_handoff_status(self, name: str, requested: Optional[HandoffStatus]) -> HandoffStatus:
        if requested:
            return requested
        rt = self._runtime(name)
        errors: List[str] = rt["errors"]
        diff: Dict[str, Dict[str, str]] = rt["diff"]
        if not errors:
            return HandoffStatus.SUCCESS
        if errors and diff:
            return HandoffStatus.PARTIAL_FAILURE
        lower = "\n".join(errors).lower()
        if any(marker in lower for marker in ("not found", "blocked", "permission", "unavailable")):
            return HandoffStatus.BLOCKED
        return HandoffStatus.FAILED

    def _build_handoff(
        self,
        name: str,
        requested_status: Optional[HandoffStatus],
        task_id_override: Optional[str],
        final_text: str,
        narrative_override: Optional[str],
        extra_artifacts: Optional[List[str]],
    ) -> Handoff:
        rt = self._runtime(name)
        task_id = task_id_override or rt["task_id"] or "none"
        status = self._resolve_handoff_status(name, requested_status)
        artifacts = list(rt["artifacts"])
        if extra_artifacts:
            artifacts.extend(extra_artifacts)
        artifacts = _dedupe_keep_order(artifacts)
        diff = dict(rt["diff"])
        handoff = Handoff(
            agent_id=name,
            task_id=str(task_id),
            status=status,
            diff=diff,
            artifacts=artifacts,
            metrics=HandoffMetrics(
                wall_time=max(time.time() - float(rt["task_started_at"]), 0.0),
                tokens_used=int(rt["tokens_used"]),
                attempts=int(rt["attempts"]),
                files_modified=len(diff),
            ),
        )
        handoff.narrative = narrative_override or self._compose_handoff_narrative(name, handoff, final_text)
        return handoff

    def _submit_handoff(self, name: str, args: Optional[dict] = None, final_text: str = "") -> str:
        args = args or {}
        rt = self._runtime(name)
        if rt.get("handoff_submitted"):
            return f"Handoff already submitted for task {rt.get('task_id', 'none')}"
        requested_status = _status_from_string(args.get("status"))
        narrative_override = args.get("narrative") if isinstance(args.get("narrative"), str) else None
        task_override = str(args.get("task_id")) if args.get("task_id") is not None else None
        extra_artifacts = [a for a in args.get("artifacts", []) if isinstance(a, str)] if isinstance(args.get("artifacts"), list) else []
        handoff = self._build_handoff(
            name=name,
            requested_status=requested_status,
            task_id_override=task_override,
            final_text=final_text or rt.get("last_text", ""),
            narrative_override=narrative_override,
            extra_artifacts=extra_artifacts,
        )
        HANDOFFS.append(handoff)
        rt["handoff_submitted"] = True
        BUS.send(sender=name, to="lead", content=handoff.narrative, msg_type="handoff", extra={"handoff": handoff.to_dict()})
        return f"Submitted handoff for task {handoff.task_id} ({handoff.status.value})"

    def _loop(self, name: str, role: str, prompt: str):
        team_name = self.config["team_name"]
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
            "Use idle tool when no work remains. Submit a structured handoff when done."
        )
        messages = [{"role": "user", "content": prompt}]
        tools = self._teammate_tools()

        while True:
            for _ in range(50):
                inbox = BUS.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})
                try:
                    response = client.messages.create(model=MODEL, system=sys_prompt, messages=messages, tools=tools, max_tokens=8000)
                except Exception as e:
                    self._record_error(name, f"llm_call: {e}")
                    self._submit_handoff(name, {"status": HandoffStatus.FAILED.value}, final_text="LLM call failed.")
                    self._set_status(name, "idle")
                    return

                rt = self._runtime(name)
                rt["attempts"] += 1
                rt["tokens_used"] += getattr(response.usage, "input_tokens", 0) + getattr(response.usage, "output_tokens", 0)
                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason != "tool_use":
                    rt["last_text"] = "\n".join([b.text for b in response.content if getattr(b, "type", None) == "text"]).strip()
                    self._submit_handoff(name, final_text=rt["last_text"])
                    break

                results = []
                idle_requested = False
                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "idle":
                            idle_requested = True
                            output = "Entering idle phase. Will poll for new tasks."
                        else:
                            output = self._exec(name, block.name, block.input)
                        print(f"  [{name}] {block.name}: {str(output)[:120]}")
                        results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                messages.append({"role": "user", "content": results})
                if idle_requested:
                    break

            self._set_status(name, "idle")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)
                inbox = BUS.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(msg)})
                    resume = True
                    break

                unclaimed = scan_unclaimed_tasks()
                if unclaimed:
                    task = unclaimed[0]
                    claim_task(task["id"], name)
                    self._reset_task_runtime(name, str(task["id"]))
                    if len(messages) <= 3:
                        messages.insert(0, make_identity_block(name, role, team_name))
                        messages.insert(1, {"role": "assistant", "content": f"I am {name}. Continuing."})
                    task_prompt = f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>"
                    messages.append({"role": "user", "content": task_prompt})
                    messages.append({"role": "assistant", "content": f"Claimed task #{task['id']}. Working on it."})
                    resume = True
                    break

            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def _exec(self, sender: str, tool_name: str, args: dict) -> str:
        if tool_name == "bash":
            return _run_bash(args["command"])
        if tool_name == "read_file":
            return _run_read(args["path"])
        if tool_name == "write_file":
            return self._tracked_write(sender, args["path"], args["content"])
        if tool_name == "edit_file":
            return self._tracked_edit(sender, args["path"], args["old_text"], args["new_text"])
        if tool_name == "send_message":
            return BUS.send(sender, args["to"], args["content"], args.get("msg_type", "message"))
        if tool_name == "read_inbox":
            return json.dumps(BUS.read_inbox(sender), indent=2)
        if tool_name == "shutdown_response":
            req_id = args["request_id"]
            if req_id in shutdown_requests:
                shutdown_requests[req_id]["status"] = "approved" if args["approve"] else "rejected"
            BUS.send(sender, "lead", args.get("reason", ""), "shutdown_response", {"request_id": req_id, "approve": args["approve"]})
            return f"Shutdown {'approved' if args['approve'] else 'rejected'}"
        if tool_name == "plan_approval":
            plan_text = args.get("plan", "")
            req_id = str(uuid.uuid4())[:8]
            plan_requests[req_id] = {"from": sender, "plan": plan_text, "status": "pending"}
            BUS.send(sender, "lead", plan_text, "plan_approval_response", {"request_id": req_id, "plan": plan_text})
            return f"Plan submitted (request_id={req_id}). Waiting for approval."
        if tool_name == "claim_task":
            out = claim_task(args["task_id"], sender)
            if not out.startswith("Error:"):
                self._reset_task_runtime(sender, str(args["task_id"]))
            return out
        if tool_name == "submit_handoff":
            return self._submit_handoff(sender, args)
        return f"Unknown tool: {tool_name}"

    def _teammate_tools(self) -> list:
        return [
            {"name": "bash", "description": "Run a shell command.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
            {"name": "read_file", "description": "Read file contents.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
            {"name": "write_file", "description": "Write content to file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "edit_file", "description": "Replace exact text in file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
            {"name": "send_message", "description": "Send message to a teammate.", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
            {"name": "read_inbox", "description": "Read and drain your inbox.", "input_schema": {"type": "object", "properties": {}}},
            {"name": "shutdown_response", "description": "Respond to a shutdown request.", "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "reason": {"type": "string"}}, "required": ["request_id", "approve"]}},
            {"name": "plan_approval", "description": "Submit a plan for lead approval.", "input_schema": {"type": "object", "properties": {"plan": {"type": "string"}}, "required": ["plan"]}},
            {"name": "idle", "description": "Signal no immediate work and enter idle polling.", "input_schema": {"type": "object", "properties": {}}},
            {"name": "claim_task", "description": "Claim a task from the task board by ID.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
            {"name": "submit_handoff", "description": "Submit structured handoff to lead.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}, "status": {"type": "string", "enum": [status.value for status in HandoffStatus]}, "narrative": {"type": "string"}, "artifacts": {"type": "array", "items": {"type": "string"}}}}},
        ]

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]


TEAM = TeammateManager(TEAM_DIR)


def _safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def _run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR, capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def _run_read(path: str, limit: int = None) -> str:
    try:
        lines = _safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def _run_write(path: str, content: str) -> str:
    try:
        fp = _safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"
    except Exception as e:
        return f"Error: {e}"


def _run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = _safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


def handle_shutdown_request(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send("lead", teammate, "Please shut down gracefully.", "shutdown_request", {"request_id": req_id})
    return f"Shutdown request {req_id} sent to '{teammate}'"


def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    req = plan_requests.get(request_id)
    if not req:
        return f"Error: Unknown plan request_id '{request_id}'"
    req["status"] = "approved" if approve else "rejected"
    BUS.send("lead", req["from"], feedback, "plan_approval_response", {"request_id": request_id, "approve": approve, "feedback": feedback})
    return f"Plan {req['status']} for '{req['from']}'"


def review_handoffs(task_id: Optional[str] = None, agent_id: Optional[str] = None, include_diff: bool = False) -> str:
    selected = []
    for handoff in HANDOFFS:
        if task_id and handoff.task_id != str(task_id):
            continue
        if agent_id and handoff.agent_id != agent_id:
            continue
        selected.append(handoff)
    if not selected:
        return "No handoffs found."
    payload = []
    for handoff in selected:
        item = {
            "agent_id": handoff.agent_id,
            "task_id": handoff.task_id,
            "status": handoff.status.value,
            "narrative": handoff.narrative,
            "artifacts": handoff.artifacts,
            "metrics": asdict(handoff.metrics),
        }
        if include_diff:
            item["diff"] = handoff.diff
        payload.append(item)
    return json.dumps(payload, indent=2)


TOOL_HANDLERS = {
    "bash": lambda **kw: _run_bash(kw["command"]),
    "read_file": lambda **kw: _run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: _run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: _run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "spawn_teammate": lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates": lambda **kw: TEAM.list_all(),
    "send_message": lambda **kw: BUS.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
    "read_inbox": lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast": lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
    "shutdown_request": lambda **kw: handle_shutdown_request(kw["teammate"]),
    "shutdown_response": lambda **kw: json.dumps(shutdown_requests.get(kw.get("request_id", ""), {"error": "not found"})),
    "plan_approval": lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
    "idle": lambda **kw: "Lead does not idle.",
    "claim_task": lambda **kw: claim_task(kw["task_id"], "lead"),
    "review_handoff": lambda **kw: review_handoffs(kw.get("task_id"), kw.get("agent_id"), kw.get("include_diff", False)),
}

TOOLS = [
    {"name": "bash", "description": "Run a shell command.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "Read file contents.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Write content to file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "edit_file", "description": "Replace exact text in file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"}, "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]}},
    {"name": "spawn_teammate", "description": "Spawn an autonomous teammate.", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "role": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["name", "role", "prompt"]}},
    {"name": "list_teammates", "description": "List all teammates.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "send_message", "description": "Send a message to a teammate.", "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "content": {"type": "string"}, "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)}}, "required": ["to", "content"]}},
    {"name": "read_inbox", "description": "Read and drain the lead's inbox.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "broadcast", "description": "Send a message to all teammates.", "input_schema": {"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]}},
    {"name": "shutdown_request", "description": "Request a teammate to shut down.", "input_schema": {"type": "object", "properties": {"teammate": {"type": "string"}}, "required": ["teammate"]}},
    {"name": "shutdown_response", "description": "Check shutdown request status.", "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}}, "required": ["request_id"]}},
    {"name": "plan_approval", "description": "Approve or reject a teammate's plan.", "input_schema": {"type": "object", "properties": {"request_id": {"type": "string"}, "approve": {"type": "boolean"}, "feedback": {"type": "string"}}, "required": ["request_id", "approve"]}},
    {"name": "idle", "description": "Enter idle state (for lead -- rarely used).", "input_schema": {"type": "object", "properties": {}}},
    {"name": "claim_task", "description": "Claim a task from the board by ID.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]}},
    {"name": "review_handoff", "description": "Review submitted structured handoffs.", "input_schema": {"type": "object", "properties": {"task_id": {"type": "string"}, "agent_id": {"type": "string"}, "include_diff": {"type": "boolean"}}}},
]


def agent_loop(messages: list):
    while True:
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append({"role": "user", "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"})
            messages.append({"role": "assistant", "content": "Noted inbox messages, including worker handoffs."})
        response = client.messages.create(model=MODEL, system=SYSTEM, messages=messages, tools=TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        results = []
        for block in response.content:
            if block.type == "tool_use":
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                print(f"> {block.name}: {str(output)[:200]}")
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms12 >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        if query.strip() == "/team":
            print(TEAM.list_all())
            continue
        if query.strip() == "/inbox":
            print(json.dumps(BUS.read_inbox("lead"), indent=2))
            continue
        if query.strip() == "/handoffs":
            print(review_handoffs(include_diff=False))
            continue
        if query.strip() == "/tasks":
            TASKS_DIR.mkdir(exist_ok=True)
            for f in sorted(TASKS_DIR.glob("task_*.json")):
                t = json.loads(f.read_text())
                marker = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(t["status"], "[?]")
                owner = f" @{t['owner']}" if t.get("owner") else ""
                print(f"  {marker} #{t['id']}: {t['subject']}{owner}")
            continue
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
