#!/usr/bin/env python3
"""
s_full.py - Reference Agent: All 11 Mechanisms Combined (~500 LOC)

Capstone implementation combining every mechanism from s01-s11.
NOT a teaching session -- this is the "put it all together" reference.

    +------------------------------------------------------------------+
    |                        FULL AGENT                                 |
    |                                                                   |
    |  System prompt (s05 skills, s03 todo nag)                        |
    |                                                                   |
    |  Before each LLM call:                                            |
    |  +--------------------+  +------------------+  +--------------+  |
    |  | Microcompact (s06) |  | Drain bg (s08)   |  | Check inbox  |  |
    |  | Auto-compact (s06) |  | notifications    |  | (s09)        |  |
    |  +--------------------+  +------------------+  +--------------+  |
    |                                                                   |
    |  Tool dispatch (s02 pattern):                                     |
    |  +--------+----------+----------+---------+-----------+          |
    |  | bash   | read     | write    | edit    | TodoWrite |          |
    |  | task   | load_sk  | compress | bg_run  | bg_check  |          |
    |  | t_crt  | t_get    | t_upd    | t_list  | spawn_tm  |          |
    |  | list_tm| send_msg | rd_inbox | bcast   | shutdown  |          |
    |  | plan   | idle     | claim    |         |           |          |
    |  +--------+----------+----------+---------+-----------+          |
    |                                                                   |
    |  Subagent (s04):  spawn -> work -> return summary                 |
    |  Teammate (s09):  spawn -> work -> idle -> auto-claim (s11)      |
    |  Shutdown (s10):  request_id handshake                            |
    |  Plan gate (s10): submit -> approve/reject                        |
    +------------------------------------------------------------------+

    REPL commands: /compact /tasks /team /inbox
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from queue import Queue
from typing import Any, Deque, Dict, List, Optional, Set

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
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"
SCRATCHPAD_DIR = WORKDIR / ".scratchpad"
WORKSPACES_DIR = WORKDIR / ".workspaces"
RECONCILE_DIR = WORKDIR / ".reconcile"
GREEN_BRANCH_DIR = WORKDIR / ".green-branch"
TOKEN_THRESHOLD = 100000
POLL_INTERVAL = 5
IDLE_TIMEOUT = 60
SELF_REFLECTION_EVERY = 10
SCRATCHPAD_SUMMARY_TRIGGER = 80
RECURSION_DEPTH_LIMIT = 3

VALID_MSG_TYPES = {
    "message",
    "broadcast",
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
}


# === SECTION: base_tools ===
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        fp = safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"


# === SECTION: todos (s03) ===
class TodoManager:
    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        validated, ip = [], 0
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            af = str(item.get("activeForm", "")).strip()
            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not af:
                raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress":
                ip += 1
            validated.append({"content": content, "status": status, "activeForm": af})
        if len(validated) > 20:
            raise ValueError("Max 20 todos")
        if ip > 1:
            raise ValueError("Only one in_progress allowed")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            m = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}.get(
                item["status"], "[?]"
            )
            suffix = (
                f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            )
            lines.append(f"{m} {item['content']}{suffix}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)


# === SECTION: subagent (s04) ===
def run_subagent(prompt: str, agent_type: str = "Explore") -> str:
    sub_tools = [
        {
            "name": "bash",
            "description": "Run command.",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read file.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    ]
    if agent_type != "Explore":
        sub_tools += [
            {
                "name": "write_file",
                "description": "Write file.",
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
                "description": "Edit file.",
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
        ]
    sub_handlers = {
        "bash": lambda **kw: run_bash(kw["command"]),
        "read_file": lambda **kw: run_read(kw["path"]),
        "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
        "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    }
    sub_msgs = [{"role": "user", "content": prompt}]
    resp = None
    for _ in range(30):
        resp = client.messages.create(
            model=MODEL, messages=sub_msgs, tools=sub_tools, max_tokens=8000
        )
        sub_msgs.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                h = sub_handlers.get(b.name, lambda **kw: "Unknown tool")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": str(h(**b.input))[:50000],
                    }
                )
        sub_msgs.append({"role": "user", "content": results})
    if resp:
        return (
            "".join(b.text for b in resp.content if hasattr(b, "text"))
            or "(no summary)"
        )
    return "(subagent failed)"


# === SECTION: skills (s05) ===
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills = {}
        if skills_dir.exists():
            for f in sorted(skills_dir.glob("*.md")):
                text = f.read_text()
                match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
                meta, body = {}, text
                if match:
                    for line in match.group(1).strip().splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip()] = v.strip()
                    body = match.group(2).strip()
                self.skills[f.stem] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        if not self.skills:
            return "(no skills)"
        return "\n".join(
            f"  - {n}: {s['meta'].get('description', '-')}"
            for n, s in self.skills.items()
        )

    def load(self, name: str) -> str:
        s = self.skills.get(name)
        if not s:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f'<skill name="{name}">\n{s["body"]}\n</skill>'


# === SECTION: compression (s06) ===
def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str)) // 4


def microcompact(messages: list):
    indices = []
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    indices.append(part)
    if len(indices) <= 3:
        return
    for part in indices[:-3]:
        if isinstance(part.get("content"), str) and len(part["content"]) > 100:
            part["content"] = "[cleared]"


def auto_compact(messages: list) -> list:
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    conv_text = json.dumps(messages, default=str)[:80000]
    resp = client.messages.create(
        model=MODEL,
        messages=[
            {"role": "user", "content": f"Summarize for continuity:\n{conv_text}"}
        ],
        max_tokens=2000,
    )
    summary = resp.content[0].text
    return [
        {"role": "user", "content": f"[Compressed. Transcript: {path}]\n{summary}"},
        {
            "role": "assistant",
            "content": "Understood. Continuing with summary context.",
        },
    ]


# === SECTION: file_tasks (s07) ===
class TaskManager:
    def __init__(self):
        TASKS_DIR.mkdir(exist_ok=True)

    def _next_id(self) -> int:
        ids = [int(f.stem.split("_")[1]) for f in TASKS_DIR.glob("task_*.json")]
        return max(ids, default=0) + 1

    def _load(self, tid: int) -> dict:
        p = TASKS_DIR / f"task_{tid}.json"
        if not p.exists():
            raise ValueError(f"Task {tid} not found")
        return json.loads(p.read_text())

    def _save(self, task: dict):
        (TASKS_DIR / f"task_{task['id']}.json").write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        task = {
            "id": self._next_id(),
            "subject": subject,
            "description": description,
            "status": "pending",
            "owner": None,
            "blockedBy": [],
            "blocks": [],
        }
        self._save(task)
        return json.dumps(task, indent=2)

    def get(self, tid: int) -> str:
        return json.dumps(self._load(tid), indent=2)

    def update(
        self,
        tid: int,
        status: str = None,
        add_blocked_by: list = None,
        add_blocks: list = None,
    ) -> str:
        task = self._load(tid)
        if status:
            task["status"] = status
            if status == "completed":
                for f in TASKS_DIR.glob("task_*.json"):
                    t = json.loads(f.read_text())
                    if tid in t.get("blockedBy", []):
                        t["blockedBy"].remove(tid)
                        self._save(t)
            if status == "deleted":
                (TASKS_DIR / f"task_{tid}.json").unlink(missing_ok=True)
                return f"Task {tid} deleted"
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if add_blocks:
            task["blocks"] = list(set(task["blocks"] + add_blocks))
        self._save(task)
        return json.dumps(task, indent=2)

    def list_all(self) -> str:
        tasks = [
            json.loads(f.read_text()) for f in sorted(TASKS_DIR.glob("task_*.json"))
        ]
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            m = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(
                t["status"], "[?]"
            )
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            lines.append(f"{m} #{t['id']}: {t['subject']}{owner}{blocked}")
        return "\n".join(lines)

    def claim(self, tid: int, owner: str) -> str:
        task = self._load(tid)
        task["owner"] = owner
        task["status"] = "in_progress"
        self._save(task)
        return f"Claimed task #{tid} for {owner}"


# === SECTION: background (s08) ===
class BackgroundManager:
    def __init__(self):
        self.tasks = {}
        self.notifications = Queue()

    def run(self, command: str, timeout: int = 120) -> str:
        tid = str(uuid.uuid4())[:8]
        self.tasks[tid] = {"status": "running", "command": command, "result": None}
        threading.Thread(
            target=self._exec, args=(tid, command, timeout), daemon=True
        ).start()
        return f"Background task {tid} started: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int):
        try:
            r = subprocess.run(
                command,
                shell=True,
                cwd=WORKDIR,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = (r.stdout + r.stderr).strip()[:50000]
            self.tasks[tid].update(
                {"status": "completed", "result": output or "(no output)"}
            )
        except Exception as e:
            self.tasks[tid].update({"status": "error", "result": str(e)})
        self.notifications.put(
            {
                "task_id": tid,
                "status": self.tasks[tid]["status"],
                "result": self.tasks[tid]["result"][:500],
            }
        )

    def check(self, tid: str = None) -> str:
        if tid:
            t = self.tasks.get(tid)
            return (
                f"[{t['status']}] {t.get('result', '(running)')}"
                if t
                else f"Unknown: {tid}"
            )
        return (
            "\n".join(
                f"{k}: [{v['status']}] {v['command'][:60]}"
                for k, v in self.tasks.items()
            )
            or "No bg tasks."
        )

    def drain(self) -> list:
        notifs = []
        while not self.notifications.empty():
            notifs.append(self.notifications.get_nowait())
        return notifs


# === SECTION: messaging (s09) ===
class MessageBus:
    def __init__(self):
        INBOX_DIR.mkdir(parents=True, exist_ok=True)

    def send(
        self,
        sender: str,
        to: str,
        content: str,
        msg_type: str = "message",
        extra: dict = None,
    ) -> str:
        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        with open(INBOX_DIR / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        path = INBOX_DIR / f"{name}.jsonl"
        if not path.exists():
            return []
        msgs = [
            json.loads(line) for line in path.read_text().strip().splitlines() if line
        ]
        path.write_text("")
        return msgs

    def broadcast(self, sender: str, content: str, names: list) -> str:
        for n in names:
            if n != sender:
                self.send(sender, n, content, "broadcast")
        return f"Broadcast to {len([n for n in names if n != sender])} teammates"


# === SECTION: shutdown + plan tracking (s10) ===
shutdown_requests = {}
plan_requests = {}


# === SECTION: team (s09/s11) ===
class TeammateManager:
    def __init__(self, bus: MessageBus, task_mgr: TaskManager):
        TEAM_DIR.mkdir(exist_ok=True)
        self.bus = bus
        self.task_mgr = task_mgr
        self.config_path = TEAM_DIR / "config.json"
        self.config = self._load()
        self.threads = {}

    def _load(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save(self):
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find(self, name: str) -> dict:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save()
        threading.Thread(
            target=self._loop, args=(name, role, prompt), daemon=True
        ).start()
        return f"Spawned '{name}' (role: {role})"

    def _set_status(self, name: str, status: str):
        member = self._find(name)
        if member:
            member["status"] = status
            self._save()

    def _loop(self, name: str, role: str, prompt: str):
        team_name = self.config["team_name"]
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
            f"Use idle when done with current work. You may auto-claim tasks."
        )
        messages = [{"role": "user", "content": prompt}]
        tools = [
            {
                "name": "bash",
                "description": "Run command.",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            {
                "name": "read_file",
                "description": "Read file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write file.",
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
                "description": "Edit file.",
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
                "name": "send_message",
                "description": "Send message.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["to", "content"],
                },
            },
            {
                "name": "idle",
                "description": "Signal no more work.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "claim_task",
                "description": "Claim task by ID.",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "integer"}},
                    "required": ["task_id"],
                },
            },
        ]
        while True:
            # -- WORK PHASE --
            for _ in range(50):
                inbox = self.bus.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})
                try:
                    response = client.messages.create(
                        model=MODEL,
                        system=sys_prompt,
                        messages=messages,
                        tools=tools,
                        max_tokens=8000,
                    )
                except Exception:
                    self._set_status(name, "shutdown")
                    return
                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason != "tool_use":
                    break
                results = []
                idle_requested = False
                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "idle":
                            idle_requested = True
                            output = "Entering idle phase."
                        elif block.name == "claim_task":
                            output = self.task_mgr.claim(block.input["task_id"], name)
                        elif block.name == "send_message":
                            output = self.bus.send(
                                name, block.input["to"], block.input["content"]
                            )
                        else:
                            dispatch = {
                                "bash": lambda **kw: run_bash(kw["command"]),
                                "read_file": lambda **kw: run_read(kw["path"]),
                                "write_file": lambda **kw: run_write(
                                    kw["path"], kw["content"]
                                ),
                                "edit_file": lambda **kw: run_edit(
                                    kw["path"], kw["old_text"], kw["new_text"]
                                ),
                            }
                            output = dispatch.get(block.name, lambda **kw: "Unknown")(
                                **block.input
                            )
                        print(f"  [{name}] {block.name}: {str(output)[:120]}")
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(output),
                            }
                        )
                messages.append({"role": "user", "content": results})
                if idle_requested:
                    break
            # -- IDLE PHASE: poll for messages and unclaimed tasks --
            self._set_status(name, "idle")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(msg)})
                    resume = True
                    break
                unclaimed = []
                for f in sorted(TASKS_DIR.glob("task_*.json")):
                    t = json.loads(f.read_text())
                    if (
                        t.get("status") == "pending"
                        and not t.get("owner")
                        and not t.get("blockedBy")
                    ):
                        unclaimed.append(t)
                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)
                    # Identity re-injection for compressed contexts
                    if len(messages) <= 3:
                        messages.insert(
                            0,
                            {
                                "role": "user",
                                "content": f"<identity>You are '{name}', role: {role}, team: {team_name}.</identity>",
                            },
                        )
                        messages.insert(
                            1,
                            {
                                "role": "assistant",
                                "content": f"I am {name}. Continuing.",
                            },
                        )
                    messages.append(
                        {
                            "role": "user",
                            "content": f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>",
                        }
                    )
                    messages.append(
                        {
                            "role": "assistant",
                            "content": f"Claimed task #{task['id']}. Working on it.",
                        }
                    )
                    resume = True
                    break
            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]


# === SECTION: phase5_s12_s20 ===
PLANNER_SYSTEM = (
    f"You are a PLANNER at {WORKDIR}. You decompose, delegate, and reconcile. "
    "You NEVER write code directly. Use workers for execution."
)

WORKER_SYSTEM = (
    "You are WORKER '{name}' for planner '{planner}'. Execute only assigned task, "
    "never decompose, never spawn other agents, and submit structured handoff."
)


class StructuredHandoffStatus(str, Enum):
    SUCCESS = "Success"
    PARTIAL_FAILURE = "PartialFailure"
    FAILED = "Failed"
    BLOCKED = "Blocked"


@dataclass
class StructuredHandoffMetrics:
    wall_time: float = 0.0
    tokens_used: int = 0
    attempts: int = 0
    files_modified: int = 0


@dataclass
class StructuredHandoff:
    agent_id: str
    task_id: str
    status: StructuredHandoffStatus
    diff: Dict[str, Dict[str, str]] = field(default_factory=dict)
    narrative: str = ""
    artifacts: List[str] = field(default_factory=list)
    metrics: StructuredHandoffMetrics = field(default_factory=StructuredHandoffMetrics)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


class HandoffRegistry:
    def __init__(self):
        self._handoffs: List[StructuredHandoff] = []
        self._lock = threading.Lock()

    def submit(self, handoff: StructuredHandoff) -> str:
        with self._lock:
            self._handoffs.append(handoff)
        return f"Submitted handoff {handoff.agent_id}/{handoff.task_id} ({handoff.status.value})"

    def review(
        self, task_id: str = None, agent_id: str = None, include_diff: bool = False
    ) -> str:
        with self._lock:
            selected = []
            for handoff in self._handoffs:
                if task_id and handoff.task_id != str(task_id):
                    continue
                if agent_id and handoff.agent_id != str(agent_id):
                    continue
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
                selected.append(item)
        return json.dumps(selected, indent=2) if selected else "No handoffs found."

    def latest(
        self, task_id: str = None, agent_id: str = None
    ) -> Optional[StructuredHandoff]:
        with self._lock:
            for handoff in reversed(self._handoffs):
                if task_id and handoff.task_id != str(task_id):
                    continue
                if agent_id and handoff.agent_id != str(agent_id):
                    continue
                return handoff
        return None

    def count(self) -> int:
        with self._lock:
            return len(self._handoffs)


class ScratchpadManager:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_chars = 8000

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.md"

    def read(self, name: str) -> str:
        path = self._path(name)
        if not path.exists():
            return ""
        return path.read_text()[: self.max_chars]

    def rewrite(self, name: str, content: str) -> str:
        cleaned = str(content)[: self.max_chars]
        self._path(name).write_text(cleaned)
        return f"Scratchpad rewritten for {name} ({len(cleaned)} chars)"

    def autosummarize(self, name: str, messages: list) -> str:
        prompt = (
            "Summarize for scratchpad with sections: Goal, Progress, Risks, Next Step.\n"
            + json.dumps(messages[-20:], default=str)[:12000]
        )
        try:
            response = client.messages.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
            )
            text = "\n".join(
                b.text for b in response.content if getattr(b, "type", None) == "text"
            ).strip()
            if not text:
                text = "Goal\n- unknown\nProgress\n- unknown\nRisks\n- none\nNext Step\n- continue"
            return self.rewrite(name, text)
        except Exception as e:
            return self.rewrite(name, f"Autosummary fallback due to error: {e}")


class WorkerWorkspace:
    IGNORE_DIRS: Set[str] = {
        ".git",
        ".workspaces",
        ".team",
        ".tasks",
        "node_modules",
        "__pycache__",
    }
    IGNORE_SUFFIXES = (".pyc", ".pyo", ".swp", ".tmp")

    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.path = (WORKSPACES_DIR / worker_id).resolve()

    @staticmethod
    def _ignore(_dir: str, names: list) -> Set[str]:
        ignored = set()
        for name in names:
            if name in WorkerWorkspace.IGNORE_DIRS:
                ignored.add(name)
            elif any(
                name.endswith(suffix) for suffix in WorkerWorkspace.IGNORE_SUFFIXES
            ):
                ignored.add(name)
        return ignored

    def create(self) -> Path:
        WORKSPACES_DIR.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            shutil.rmtree(self.path)
        shutil.copytree(WORKDIR, self.path, ignore=self._ignore)
        return self.path

    def cleanup(self):
        if self.path.exists():
            shutil.rmtree(self.path)

    def resolve(self, rel_path: str) -> Path:
        candidate = (self.path / rel_path).resolve()
        if not candidate.is_relative_to(self.path):
            raise ValueError(f"Path escapes worker workspace: {rel_path}")
        return candidate

    def read(self, rel_path: str, limit: int = None) -> str:
        fp = self.resolve(rel_path)
        lines = fp.read_text().splitlines()
        if limit and limit > 0 and len(lines) > limit:
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)[:50000]

    def write(self, rel_path: str, content: str) -> str:
        fp = self.resolve(rel_path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes"

    def edit(self, rel_path: str, old_text: str, new_text: str) -> str:
        fp = self.resolve(rel_path)
        before = fp.read_text()
        if old_text not in before:
            return f"Error: Text not found in {rel_path}"
        fp.write_text(before.replace(old_text, new_text, 1))
        return f"Edited {rel_path}"

    def run_bash(self, command: str) -> str:
        blocked = ["rm -rf /", "sudo", "shutdown", "reboot"]
        if any(fragment in command for fragment in blocked):
            return "Error: Dangerous command blocked"
        proc = subprocess.run(
            command,
            shell=True,
            cwd=self.path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (proc.stdout + proc.stderr).strip()
        return output[:50000] if output else "(no output)"

    def snapshot(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for fp in self.path.rglob("*"):
            if not fp.is_file():
                continue
            rel = str(fp.relative_to(self.path))
            if any(part in self.IGNORE_DIRS for part in Path(rel).parts):
                continue
            if any(rel.endswith(suffix) for suffix in self.IGNORE_SUFFIXES):
                continue
            try:
                out[rel] = fp.read_text()
            except Exception:
                out[rel] = "<binary>"
        return out


class ErrorPolicy:
    def __init__(self, error_budget: float = 0.10, window: int = 50):
        self.error_budget = max(0.0, min(error_budget, 1.0))
        self.events: Deque[bool] = deque(maxlen=max(10, window))

    def record(self, success: bool):
        self.events.append(bool(success))

    def error_rate(self) -> float:
        if not self.events:
            return 0.0
        failures = len([x for x in self.events if not x])
        return failures / float(len(self.events))

    def healthy(self) -> bool:
        return self.error_rate() <= self.error_budget

    def status(self) -> str:
        return json.dumps(
            {
                "error_budget": self.error_budget,
                "window": len(self.events),
                "error_rate": round(self.error_rate(), 4),
                "healthy": self.healthy(),
            },
            indent=2,
        )


@dataclass
class WorkerAgentRuntime:
    worker_id: str
    task_id: str
    task_text: str
    started_at: float = field(default_factory=time.time)
    attempts: int = 0
    turns: int = 0
    tokens_used: int = 0
    tokens_since_tool: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    last_tool_at: float = field(default_factory=time.time)
    handoff_submitted: bool = False
    errors: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    diff: Dict[str, Dict[str, str]] = field(default_factory=dict)
    base_snapshot: Dict[str, str] = field(default_factory=dict)
    edit_counts: Dict[str, int] = field(default_factory=dict)
    interrupted: bool = False
    shutdown_requested: bool = False


class WorkerOrchestrator:
    def __init__(
        self,
        handoffs: HandoffRegistry,
        scratchpads: ScratchpadManager,
        policy: ErrorPolicy,
    ):
        self.handoffs = handoffs
        self.scratchpads = scratchpads
        self.policy = policy
        self.runtimes: Dict[str, WorkerAgentRuntime] = {}
        self.workspaces: Dict[str, WorkerWorkspace] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self.status: Dict[str, str] = {}
        self.fix_forward_tasks: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def _next_worker(self) -> str:
        idx = len(self.runtimes) + 1
        while f"worker-{idx}" in self.runtimes:
            idx += 1
        return f"worker-{idx}"

    def spawn_worker(self, task: str, name: str = None, task_id: str = None) -> str:
        worker = (name or "").strip() or self._next_worker()
        if self.status.get(worker) in ("working", "starting"):
            return f"Error: '{worker}' is currently {self.status.get(worker)}"
        assigned_task_id = (task_id or str(uuid.uuid4())[:8]).strip()
        runtime = WorkerAgentRuntime(
            worker_id=worker, task_id=assigned_task_id, task_text=task
        )
        workspace = WorkerWorkspace(worker)
        workspace.create()
        runtime.base_snapshot = workspace.snapshot()
        self.runtimes[worker] = runtime
        self.workspaces[worker] = workspace
        self.status[worker] = "starting"
        self.scratchpads.rewrite(
            worker,
            f"# Worker Scratchpad\n- task_id: {assigned_task_id}\n- task: {task}\n",
        )
        thread = threading.Thread(target=self._worker_loop, args=(worker,), daemon=True)
        self.threads[worker] = thread
        thread.start()
        return f"Spawned worker '{worker}' task_id={assigned_task_id} workspace={workspace.path}"

    def _status_from_runtime(
        self, runtime: WorkerAgentRuntime
    ) -> StructuredHandoffStatus:
        if runtime.shutdown_requested and runtime.diff:
            return StructuredHandoffStatus.PARTIAL_FAILURE
        if runtime.shutdown_requested and not runtime.diff:
            return StructuredHandoffStatus.BLOCKED
        if not runtime.errors:
            return StructuredHandoffStatus.SUCCESS
        if runtime.errors and runtime.diff:
            return StructuredHandoffStatus.PARTIAL_FAILURE
        return StructuredHandoffStatus.FAILED

    def submit_handoff(
        self,
        worker: str,
        narrative: str = "",
        status: str = None,
        artifacts: list = None,
    ) -> str:
        runtime = self.runtimes.get(worker)
        if not runtime:
            return f"Error: Unknown worker '{worker}'"
        if runtime.handoff_submitted:
            return f"Handoff already submitted for {worker}/{runtime.task_id}"
        resolved_status = self._status_from_runtime(runtime)
        if status:
            for item in StructuredHandoffStatus:
                if item.value == status:
                    resolved_status = item
                    break
        handoff = StructuredHandoff(
            agent_id=worker,
            task_id=runtime.task_id,
            status=resolved_status,
            diff=dict(runtime.diff),
            narrative=narrative.strip()
            or self._default_handoff_narrative(runtime, resolved_status),
            artifacts=list(dict.fromkeys((runtime.artifacts + (artifacts or [])))),
            metrics=StructuredHandoffMetrics(
                wall_time=max(time.time() - runtime.started_at, 0.0),
                tokens_used=runtime.tokens_used,
                attempts=runtime.attempts,
                files_modified=len(runtime.diff),
            ),
        )
        runtime.handoff_submitted = True
        self.policy.record(handoff.status == StructuredHandoffStatus.SUCCESS)
        return self.handoffs.submit(handoff)

    def _default_handoff_narrative(
        self, runtime: WorkerAgentRuntime, status: StructuredHandoffStatus
    ) -> str:
        changed = ", ".join(runtime.diff.keys()) if runtime.diff else "no files"
        msg = [
            f"Worker {runtime.worker_id} finished task {runtime.task_id} with status {status.value}.",
            f"Changed: {changed}.",
        ]
        if runtime.errors:
            msg.append(f"Latest error: {runtime.errors[-1]}")
        msg.append("Next step: planner review and merge/reconcile.")
        return "\n".join(msg)

    def _record_diff(
        self, runtime: WorkerAgentRuntime, rel_path: str, before: str, after: str
    ):
        if rel_path in runtime.diff:
            runtime.diff[rel_path] = {
                "before": runtime.diff[rel_path]["before"],
                "after": after,
            }
        else:
            runtime.diff[rel_path] = {"before": before, "after": after}
        runtime.artifacts = list(dict.fromkeys(runtime.artifacts + [rel_path]))
        runtime.edit_counts[rel_path] = runtime.edit_counts.get(rel_path, 0) + 1

    def _worker_exec(
        self, runtime: WorkerAgentRuntime, tool_name: str, args: dict
    ) -> str:
        workspace = self.workspaces[runtime.worker_id]
        if tool_name == "bash":
            runtime.tokens_since_tool = 0
            runtime.last_tool_at = time.time()
            return workspace.run_bash(str(args.get("command", "")))
        if tool_name == "read_file":
            runtime.tokens_since_tool = 0
            runtime.last_tool_at = time.time()
            return workspace.read(str(args.get("path", "")), args.get("limit"))
        if tool_name == "write_file":
            rel = str(args.get("path", ""))
            target = workspace.resolve(rel)
            before = target.read_text() if target.exists() else ""
            out = workspace.write(rel, str(args.get("content", "")))
            after = target.read_text() if target.exists() else ""
            self._record_diff(runtime, rel, before, after)
            runtime.tokens_since_tool = 0
            runtime.last_tool_at = time.time()
            return out
        if tool_name == "edit_file":
            rel = str(args.get("path", ""))
            target = workspace.resolve(rel)
            before = target.read_text() if target.exists() else ""
            out = workspace.edit(
                rel, str(args.get("old_text", "")), str(args.get("new_text", ""))
            )
            after = target.read_text() if target.exists() else ""
            self._record_diff(runtime, rel, before, after)
            runtime.tokens_since_tool = 0
            runtime.last_tool_at = time.time()
            return out
        if tool_name == "submit_handoff":
            return self.submit_handoff(
                runtime.worker_id,
                narrative=str(args.get("narrative", "")),
                status=str(args.get("status", "")) if args.get("status") else None,
                artifacts=[x for x in args.get("artifacts", []) if isinstance(x, str)]
                if isinstance(args.get("artifacts"), list)
                else [],
            )
        if tool_name == "rewrite_scratchpad":
            runtime.tokens_since_tool = 0
            runtime.last_tool_at = time.time()
            return self.scratchpads.rewrite(
                runtime.worker_id, str(args.get("content", ""))
            )
        return f"Unknown tool: {tool_name}"

    def _worker_loop(self, worker: str):
        runtime = self.runtimes[worker]
        self.status[worker] = "working"
        messages = [
            {
                "role": "user",
                "content": f"<assignment>task_id={runtime.task_id}\n{runtime.task_text}</assignment>",
            },
            {
                "role": "user",
                "content": f"<scratchpad>{self.scratchpads.read(worker) or '(empty)'}</scratchpad>",
            },
        ]
        tools = [
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
                    "properties": {
                        "path": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write file.",
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
                "description": "Edit file.",
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
                "description": "Submit structured handoff.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": [s.value for s in StructuredHandoffStatus],
                        },
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
        for _ in range(40):
            if runtime.shutdown_requested:
                break
            runtime.last_heartbeat = time.time()
            try:
                response = client.messages.create(
                    model=MODEL,
                    system=WORKER_SYSTEM.format(name=worker, planner="lead"),
                    messages=messages,
                    tools=tools,
                    max_tokens=6000,
                )
            except Exception as e:
                runtime.errors.append(f"llm_call: {e}")
                break
            runtime.attempts += 1
            runtime.turns += 1
            used = int(getattr(response.usage, "input_tokens", 0)) + int(
                getattr(response.usage, "output_tokens", 0)
            )
            runtime.tokens_used += used
            runtime.tokens_since_tool += used
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                try:
                    output = self._worker_exec(runtime, block.name, block.input)
                except Exception as e:
                    output = f"Error: {e}"
                    runtime.errors.append(str(e))
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                )
            messages.append({"role": "user", "content": results})
            if runtime.handoff_submitted:
                break
        if not runtime.handoff_submitted:
            self.submit_handoff(worker)
        self.status[worker] = "idle"
        try:
            self.workspaces[worker].cleanup()
        except Exception:
            pass

    def list_workers(self) -> str:
        if not self.runtimes:
            return "No workers."
        lines = []
        for worker, runtime in sorted(self.runtimes.items()):
            lines.append(
                f"- {worker}: status={self.status.get(worker, 'unknown')} task={runtime.task_id} "
                f"tokens={runtime.tokens_used} since_tool={runtime.tokens_since_tool} edits={sum(runtime.edit_counts.values())}"
            )
        return "\n".join(lines)

    def request_shutdown(self, worker: str, reason: str) -> str:
        runtime = self.runtimes.get(worker)
        if not runtime:
            return f"Error: Unknown worker '{worker}'"
        runtime.shutdown_requested = True
        runtime.errors.append(f"watchdog_shutdown: {reason}")
        self.status[worker] = "shutdown"
        return f"Shutdown requested for {worker} ({reason})"


def optimistic_merge(
    handoff: StructuredHandoff,
    runtime: WorkerAgentRuntime,
    canonical_snapshot: Dict[str, str],
    worker_snapshot: Dict[str, str],
    fix_forward_tasks: list,
) -> str:
    base = runtime.base_snapshot
    paths = sorted(
        set(base.keys()) | set(canonical_snapshot.keys()) | set(worker_snapshot.keys())
    )
    applied: List[str] = []
    conflicts: Dict[str, Dict[str, str]] = {}
    for rel_path in paths:
        base_v = base.get(rel_path, "")
        canonical_v = canonical_snapshot.get(rel_path, "")
        worker_v = worker_snapshot.get(rel_path, "")
        if worker_v == base_v:
            continue
        if canonical_v == base_v:
            target = (WORKDIR / rel_path).resolve()
            if target.is_relative_to(WORKDIR):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(worker_v)
                applied.append(rel_path)
            continue
        if worker_v != canonical_v:
            conflicts[rel_path] = {
                "base": base_v,
                "ours": worker_v,
                "theirs": canonical_v,
            }
    fix_task_id = None
    if conflicts:
        fix_task = TASK_MGR.create(
            subject=f"Fix-forward merge conflicts for {handoff.agent_id}/{handoff.task_id}",
            description=(
                "Optimistic merge conflict detected. Resolve directly on canonical state. "
                "Never revert.\n\n" + json.dumps(conflicts, indent=2)[:12000]
            ),
        )
        fix_forward_tasks.append(
            {
                "handoff": handoff.to_dict(),
                "conflicts": conflicts,
                "task": json.loads(fix_task),
            }
        )
        fix_task_id = json.loads(fix_task).get("id")
    return json.dumps(
        {
            "handoff": {"agent_id": handoff.agent_id, "task_id": handoff.task_id},
            "applied_files": applied,
            "conflicts": sorted(conflicts.keys()),
            "fix_forward_task_id": fix_task_id,
        },
        indent=2,
    )


class RecursiveHierarchy:
    def __init__(
        self,
        worker_orchestrator: WorkerOrchestrator,
        depth_limit: int = RECURSION_DEPTH_LIMIT,
    ):
        self.worker_orchestrator = worker_orchestrator
        self.depth_limit = max(1, depth_limit)
        self.subplanners: Dict[str, Dict[str, Any]] = {
            "lead": {"parent": None, "depth": 0, "task": "root"}
        }
        self.child_handoffs: Dict[str, List[Dict[str, Any]]] = {}

    def spawn_subplanner(self, parent: str, task: str, name: str = None) -> str:
        parent_node = self.subplanners.get(parent)
        if not parent_node:
            parent = "lead"
            parent_node = self.subplanners.get(parent)
            if not parent_node:
                return f"Error: Unknown parent planner '{parent}'"
        depth = int(parent_node["depth"]) + 1
        if depth > self.depth_limit:
            return f"Error: Depth limit reached ({self.depth_limit})"
        if name and name.strip():
            subplanner = name.strip()
        else:
            idx = len(self.subplanners)
            subplanner = f"subplanner-{idx}"
        self.subplanners[subplanner] = {"parent": parent, "depth": depth, "task": task}
        self.child_handoffs.setdefault(subplanner, [])
        return f"Spawned subplanner '{subplanner}' depth={depth}/{self.depth_limit}"

    def spawn_worker(
        self, planner: str, task: str, name: str = None, task_id: str = None
    ) -> str:
        if planner not in self.subplanners:
            return f"Error: Unknown planner '{planner}'"
        return self.worker_orchestrator.spawn_worker(
            task=task, name=name, task_id=task_id
        )

    def bubble_handoff(self, planner: str, handoff: StructuredHandoff) -> str:
        self.child_handoffs.setdefault(planner, []).append(handoff.to_dict())
        parent = self.subplanners.get(planner, {}).get("parent")
        if not parent:
            return f"Stored handoff at root planner '{planner}'"
        self.child_handoffs.setdefault(parent, []).append(handoff.to_dict())
        return f"Bubbled handoff from {planner} to {parent}"

    def summary(self) -> str:
        return json.dumps(
            {
                "depth_limit": self.depth_limit,
                "subplanners": self.subplanners,
                "handoff_counts": {k: len(v) for k, v in self.child_handoffs.items()},
            },
            indent=2,
        )


@dataclass
class WatchdogEvent:
    worker: str
    mode: str
    detail: str
    timestamp: float = field(default_factory=time.time)


class Watchdog(threading.Thread):
    def __init__(self, orchestrator: WorkerOrchestrator, poll_seconds: float = 2.5):
        super().__init__(daemon=True)
        self.orchestrator = orchestrator
        self.poll_seconds = max(1.0, poll_seconds)
        self.stop_event = threading.Event()
        self.events: List[WatchdogEvent] = []
        self.zombie_seconds = 60.0
        self.tunnel_edits = 20
        self.token_burn = 16000
        self.no_progress_turns = 16
        self.no_progress_seconds = 90.0

    def stop(self):
        self.stop_event.set()

    def _kill_and_respawn(self, worker: str, mode: str, detail: str):
        self.events.append(WatchdogEvent(worker=worker, mode=mode, detail=detail))
        rt = self.orchestrator.runtimes.get(worker)
        if not rt:
            return
        task_text = rt.task_text
        self.orchestrator.request_shutdown(worker, f"watchdog:{mode}")
        self.orchestrator.spawn_worker(task=task_text)

    def run(self):
        while not self.stop_event.is_set():
            now = time.time()
            for worker, runtime in list(self.orchestrator.runtimes.items()):
                if self.orchestrator.status.get(worker) != "working":
                    continue
                if runtime.handoff_submitted:
                    continue
                if now - runtime.last_heartbeat > self.zombie_seconds:
                    self._kill_and_respawn(
                        worker,
                        "zombie",
                        f"No heartbeat for {now - runtime.last_heartbeat:.1f}s",
                    )
                    continue
                if runtime.edit_counts:
                    top = max(runtime.edit_counts.values())
                    if top > self.tunnel_edits:
                        self._kill_and_respawn(
                            worker,
                            "tunnel_vision",
                            f"Repeated edits threshold exceeded ({top})",
                        )
                        continue
                if runtime.tokens_since_tool > self.token_burn:
                    self._kill_and_respawn(
                        worker,
                        "token_burn",
                        f"{runtime.tokens_since_tool} tokens since last tool call",
                    )
                    continue
                edits = sum(runtime.edit_counts.values())
                elapsed = max(now - runtime.started_at, 0.0)
                if (
                    runtime.attempts >= self.no_progress_turns
                    and edits == 0
                    and elapsed > self.no_progress_seconds
                ):
                    self._kill_and_respawn(
                        worker,
                        "no_progress",
                        f"No file edits after {runtime.attempts} turns in {elapsed:.1f}s",
                    )
                    continue
            self.stop_event.wait(self.poll_seconds)

    def render_events(self, limit: int = 25) -> str:
        recent = self.events[-max(1, limit) :]
        return json.dumps([asdict(event) for event in recent], indent=2)


class ReconciliationPass:
    def __init__(self, orchestrator: WorkerOrchestrator, max_rounds: int = 3):
        self.orchestrator = orchestrator
        self.max_rounds = max(1, max_rounds)
        self.reports: List[Dict[str, Any]] = []
        RECONCILE_DIR.mkdir(parents=True, exist_ok=True)
        GREEN_BRANCH_DIR.mkdir(parents=True, exist_ok=True)

    def _test_commands(self) -> list:
        cmds = []
        if (WORKDIR / "web" / "package.json").exists():
            cmds += [
                {
                    "name": "web_vitest",
                    "command": "npx vitest run",
                    "cwd": str(WORKDIR / "web"),
                },
                {
                    "name": "web_tsc",
                    "command": "npx tsc --noEmit",
                    "cwd": str(WORKDIR / "web"),
                },
                {
                    "name": "web_build",
                    "command": "npm run build",
                    "cwd": str(WORKDIR / "web"),
                },
            ]
        cmds.append(
            {
                "name": "py_compile",
                "command": "python3 -m compileall -q agents",
                "cwd": str(WORKDIR),
            }
        )
        return cmds

    def _run_suite(self) -> Dict[str, Any]:
        results = []
        for item in self._test_commands():
            started = time.time()
            try:
                proc = subprocess.run(
                    item["command"],
                    shell=True,
                    cwd=item["cwd"],
                    capture_output=True,
                    text=True,
                    timeout=900,
                )
                output = (proc.stdout + "\n" + proc.stderr).strip()[:20000]
                results.append(
                    {
                        "name": item["name"],
                        "returncode": proc.returncode,
                        "output": output,
                        "duration": max(time.time() - started, 0.0),
                    }
                )
            except subprocess.TimeoutExpired:
                results.append(
                    {
                        "name": item["name"],
                        "returncode": 124,
                        "output": "Timeout",
                        "duration": max(time.time() - started, 0.0),
                    }
                )
        return {
            "all_passed": all(x["returncode"] == 0 for x in results),
            "results": results,
        }

    def _parse_failures(self, suite: Dict[str, Any]) -> List[Dict[str, Any]]:
        out = []
        for result in suite.get("results", []):
            if result.get("returncode") == 0:
                continue
            out.append(
                {
                    "failure_id": f"f-{uuid.uuid4().hex[:10]}",
                    "command": result.get("name"),
                    "message": result.get("output", "")[:500],
                }
            )
        return out

    def _snapshot_green(self) -> str:
        snapshot_id = f"green-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        target = GREEN_BRANCH_DIR / snapshot_id
        shutil.copytree(WORKDIR, target, ignore=WorkerWorkspace._ignore)
        return str(target)

    def run(self, max_rounds: int = None) -> str:
        rounds = max_rounds or self.max_rounds
        report = {
            "report_id": f"r-{uuid.uuid4().hex[:10]}",
            "rounds": [],
            "verdict": "FAIL",
            "green_snapshot": None,
        }
        for round_idx in range(1, rounds + 1):
            suite = self._run_suite()
            failures = self._parse_failures(suite)
            round_report = {
                "round": round_idx,
                "suite": suite,
                "failures": failures,
                "fixers": [],
            }
            report["rounds"].append(round_report)
            if suite["all_passed"]:
                report["verdict"] = "PASS"
                report["green_snapshot"] = self._snapshot_green()
                break
            for failure in failures:
                fix_task = TASK_MGR.create(
                    subject=f"Reconcile fixer: {failure['command']}",
                    description=(
                        "Reconciliation fixer task. Apply minimal fix-forward change.\n"
                        + json.dumps(failure, indent=2)
                    ),
                )
                round_report["fixers"].append(json.loads(fix_task))
        report_path = RECONCILE_DIR / f"reconcile_{report['report_id']}.json"
        report_path.write_text(json.dumps(report, indent=2))
        self.reports.append(report)
        return json.dumps(
            {"report": report_path.name, "verdict": report["verdict"]}, indent=2
        )


# === SECTION: global_instances ===
TODO = TodoManager()
SKILLS = SkillLoader(SKILLS_DIR)
TASK_MGR = TaskManager()
BG = BackgroundManager()
BUS = MessageBus()
TEAM = TeammateManager(BUS, TASK_MGR)
HANDOFFS_V2 = HandoffRegistry()
SCRATCHPADS_V2 = ScratchpadManager(SCRATCHPAD_DIR)
ERROR_POLICY = ErrorPolicy(error_budget=0.10, window=50)
WORKERS_V2 = WorkerOrchestrator(HANDOFFS_V2, SCRATCHPADS_V2, ERROR_POLICY)
HIERARCHY = RecursiveHierarchy(WORKERS_V2, depth_limit=RECURSION_DEPTH_LIMIT)
WATCHDOG = Watchdog(WORKERS_V2)
WATCHDOG.start()
RECONCILIATION = ReconciliationPass(WORKERS_V2, max_rounds=3)

# === SECTION: system_prompt ===
SYSTEM = f"""{PLANNER_SYSTEM}

Use tools to solve tasks. Use TodoWrite for multi-step work.
Planner role enforcement:
- NEVER write code directly with bash/write_file/edit_file.
- ALWAYS delegate execution using spawn_worker.
- Use optimistic_merge and reconcile for fix-forward orchestration.

Skills available:
{SKILLS.descriptions()}"""


# === SECTION: shutdown_protocol (s10) ===
def handle_shutdown_request(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    BUS.send(
        "lead",
        teammate,
        "Please shut down.",
        "shutdown_request",
        {"request_id": req_id},
    )
    return f"Shutdown request {req_id} sent to '{teammate}'"


# === SECTION: plan_approval (s10) ===
def handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    req = plan_requests.get(request_id)
    if not req:
        return f"Error: Unknown plan request_id '{request_id}'"
    req["status"] = "approved" if approve else "rejected"
    BUS.send(
        "lead",
        req["from"],
        feedback,
        "plan_approval_response",
        {"request_id": request_id, "approve": approve, "feedback": feedback},
    )
    return f"Plan {req['status']} for '{req['from']}'"


def _snapshot_canonical() -> Dict[str, str]:
    snap: Dict[str, str] = {}
    for fp in WORKDIR.rglob("*"):
        if not fp.is_file():
            continue
        rel = str(fp.relative_to(WORKDIR))
        if any(part in WorkerWorkspace.IGNORE_DIRS for part in Path(rel).parts):
            continue
        if any(rel.endswith(suffix) for suffix in WorkerWorkspace.IGNORE_SUFFIXES):
            continue
        try:
            snap[rel] = fp.read_text()
        except Exception:
            snap[rel] = "<binary>"
    return snap


def _planner_guard(tool_name: str) -> Optional[str]:
    forbidden = {"bash", "write_file", "edit_file"}
    if tool_name in forbidden:
        return (
            f"Error: Planner role cannot use '{tool_name}'. "
            "Delegate execution with spawn_worker."
        )
    return None


def _worker_progress_signature() -> str:
    parts: List[str] = []
    for worker, runtime in sorted(WORKERS_V2.runtimes.items()):
        parts.append(
            ":".join(
                [
                    worker,
                    WORKERS_V2.status.get(worker, "unknown"),
                    str(runtime.attempts),
                    str(sum(runtime.edit_counts.values())),
                    "1" if runtime.handoff_submitted else "0",
                ]
            )
        )
    return f"handoffs={HANDOFFS_V2.count()}|" + "|".join(parts)


def handle_submit_handoff(
    agent_id: str,
    task_id: str,
    status: str,
    narrative: str = "",
    artifacts: list = None,
    diff: dict = None,
) -> str:
    resolved = StructuredHandoffStatus.SUCCESS
    for item in StructuredHandoffStatus:
        if item.value == status:
            resolved = item
            break
    handoff = StructuredHandoff(
        agent_id=agent_id,
        task_id=task_id,
        status=resolved,
        diff=diff or {},
        narrative=narrative or f"Manual handoff from {agent_id}/{task_id}",
        artifacts=artifacts or [],
        metrics=StructuredHandoffMetrics(files_modified=len(diff or {})),
    )
    ERROR_POLICY.record(handoff.status == StructuredHandoffStatus.SUCCESS)
    return HANDOFFS_V2.submit(handoff)


def handle_optimistic_merge(task_id: str = None, agent_id: str = None) -> str:
    handoff = HANDOFFS_V2.latest(task_id=task_id, agent_id=agent_id)
    if not handoff:
        return "Error: handoff not found"
    runtime = WORKERS_V2.runtimes.get(handoff.agent_id)
    workspace = WORKERS_V2.workspaces.get(handoff.agent_id)
    if not runtime or not workspace:
        return "Error: worker runtime/workspace not found"
    canonical = _snapshot_canonical()
    worker_snapshot = workspace.snapshot()
    return optimistic_merge(
        handoff, runtime, canonical, worker_snapshot, WORKERS_V2.fix_forward_tasks
    )


# === SECTION: tool_dispatch (s02) ===
TOOL_HANDLERS = {
    "bash": lambda **kw: run_bash(kw["command"]),
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "TodoWrite": lambda **kw: TODO.update(kw["items"]),
    "task": lambda **kw: run_subagent(kw["prompt"], kw.get("agent_type", "Explore")),
    "load_skill": lambda **kw: SKILLS.load(kw["name"]),
    "compress": lambda **kw: "Compressing...",
    "background_run": lambda **kw: BG.run(kw["command"], kw.get("timeout", 120)),
    "check_background": lambda **kw: BG.check(kw.get("task_id")),
    "task_create": lambda **kw: TASK_MGR.create(
        kw["subject"], kw.get("description", "")
    ),
    "task_get": lambda **kw: TASK_MGR.get(kw["task_id"]),
    "task_update": lambda **kw: TASK_MGR.update(
        kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("add_blocks")
    ),
    "task_list": lambda **kw: TASK_MGR.list_all(),
    "spawn_teammate": lambda **kw: TEAM.spawn(kw["name"], kw["role"], kw["prompt"]),
    "list_teammates": lambda **kw: TEAM.list_all(),
    "send_message": lambda **kw: BUS.send(
        "lead", kw["to"], kw["content"], kw.get("msg_type", "message")
    ),
    "read_inbox": lambda **kw: json.dumps(BUS.read_inbox("lead"), indent=2),
    "broadcast": lambda **kw: BUS.broadcast("lead", kw["content"], TEAM.member_names()),
    "shutdown_request": lambda **kw: handle_shutdown_request(kw["teammate"]),
    "plan_approval": lambda **kw: handle_plan_review(
        kw["request_id"], kw["approve"], kw.get("feedback", "")
    ),
    "spawn_worker": lambda **kw: WORKERS_V2.spawn_worker(
        kw["task"], kw.get("name"), kw.get("task_id")
    ),
    "spawn_subplanner": lambda **kw: HIERARCHY.spawn_subplanner(
        kw.get("parent", "lead"), kw["task"], kw.get("name")
    ),
    "submit_handoff": lambda **kw: handle_submit_handoff(
        kw["agent_id"],
        kw["task_id"],
        kw["status"],
        kw.get("narrative", ""),
        kw.get("artifacts"),
        kw.get("diff"),
    ),
    "review_handoff": lambda **kw: HANDOFFS_V2.review(
        kw.get("task_id"), kw.get("agent_id"), kw.get("include_diff", False)
    ),
    "read_scratchpad": lambda **kw: SCRATCHPADS_V2.read(kw["agent_id"])
    or "(empty scratchpad)",
    "rewrite_scratchpad": lambda **kw: SCRATCHPADS_V2.rewrite(
        kw["agent_id"], kw["content"]
    ),
    "optimistic_merge": lambda **kw: handle_optimistic_merge(
        kw.get("task_id"), kw.get("agent_id")
    ),
    "hierarchy_status": lambda **kw: HIERARCHY.summary(),
    "list_workers": lambda **kw: WORKERS_V2.list_workers(),
    "error_policy_status": lambda **kw: ERROR_POLICY.status(),
    "list_watchdog_events": lambda **kw: WATCHDOG.render_events(
        int(kw.get("limit", 25))
    ),
    "reconcile": lambda **kw: RECONCILIATION.run(kw.get("max_rounds")),
    "idle": lambda **kw: "Lead does not idle.",
    "claim_task": lambda **kw: TASK_MGR.claim(kw["task_id"], "lead"),
}

TOOLS = [
    {
        "name": "bash",
        "description": "Run a shell command.",
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
        "description": "Write content to file.",
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
        "name": "TodoWrite",
        "description": "Update task tracking list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                            "activeForm": {"type": "string"},
                        },
                        "required": ["content", "status", "activeForm"],
                    },
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "task",
        "description": "Spawn a subagent for isolated exploration or work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "agent_type": {
                    "type": "string",
                    "enum": ["Explore", "general-purpose"],
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "load_skill",
        "description": "Load specialized knowledge by name.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "compress",
        "description": "Manually compress conversation context.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "background_run",
        "description": "Run command in background thread.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "check_background",
        "description": "Check background task status.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
        },
    },
    {
        "name": "task_create",
        "description": "Create a persistent file task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["subject"],
        },
    },
    {
        "name": "task_get",
        "description": "Get task details by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_update",
        "description": "Update task status or dependencies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "deleted"],
                },
                "add_blocked_by": {"type": "array", "items": {"type": "integer"}},
                "add_blocks": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_list",
        "description": "List all tasks.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "spawn_teammate",
        "description": "Spawn a persistent autonomous teammate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "role": {"type": "string"},
                "prompt": {"type": "string"},
            },
            "required": ["name", "role", "prompt"],
        },
    },
    {
        "name": "list_teammates",
        "description": "List all teammates.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_message",
        "description": "Send a message to a teammate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "content": {"type": "string"},
                "msg_type": {"type": "string", "enum": list(VALID_MSG_TYPES)},
            },
            "required": ["to", "content"],
        },
    },
    {
        "name": "read_inbox",
        "description": "Read and drain the lead's inbox.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "broadcast",
        "description": "Send message to all teammates.",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
    },
    {
        "name": "shutdown_request",
        "description": "Request a teammate to shut down.",
        "input_schema": {
            "type": "object",
            "properties": {"teammate": {"type": "string"}},
            "required": ["teammate"],
        },
    },
    {
        "name": "plan_approval",
        "description": "Approve or reject a teammate's plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "approve": {"type": "boolean"},
                "feedback": {"type": "string"},
            },
            "required": ["request_id", "approve"],
        },
    },
    {
        "name": "idle",
        "description": "Enter idle state.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "claim_task",
        "description": "Claim a task from the board.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "spawn_worker",
        "description": "Spawn isolated worker with fresh context.",
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
        "name": "spawn_subplanner",
        "description": "Spawn recursive subplanner node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "parent": {"type": "string"},
                "name": {"type": "string"},
                "task": {"type": "string"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "submit_handoff",
        "description": "Submit structured handoff manually.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "task_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": [s.value for s in StructuredHandoffStatus],
                },
                "narrative": {"type": "string"},
                "artifacts": {"type": "array", "items": {"type": "string"}},
                "diff": {"type": "object"},
            },
            "required": ["agent_id", "task_id", "status"],
        },
    },
    {
        "name": "review_handoff",
        "description": "Review structured handoffs.",
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
        "name": "read_scratchpad",
        "description": "Read agent scratchpad state.",
        "input_schema": {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        },
    },
    {
        "name": "rewrite_scratchpad",
        "description": "Rewrite agent scratchpad (replace content).",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["agent_id", "content"],
        },
    },
    {
        "name": "optimistic_merge",
        "description": "Run optimistic 3-way merge and create fix-forward task on conflict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "agent_id": {"type": "string"},
            },
        },
    },
    {
        "name": "hierarchy_status",
        "description": "Show recursive hierarchy status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_workers",
        "description": "List planner-worker split worker statuses.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "error_policy_status",
        "description": "Show error budget and tolerance status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_watchdog_events",
        "description": "Show watchdog failure mode interventions.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
        },
    },
    {
        "name": "reconcile",
        "description": "Run reconciliation pass with capped rounds.",
        "input_schema": {
            "type": "object",
            "properties": {"max_rounds": {"type": "integer"}},
        },
    },
]


# === SECTION: agent_loop ===
def agent_loop(messages: list):
    rounds_without_todo = 0
    lead_turns = 0
    stalled_rounds = 0
    inspection_only_rounds = 0
    last_progress = _worker_progress_signature()
    inspection_tools = {
        "list_workers",
        "read_inbox",
        "read_scratchpad",
        "task_list",
        "list_watchdog_events",
        "hierarchy_status",
        "error_policy_status",
    }
    while True:
        lead_turns += 1
        if lead_turns % SELF_REFLECTION_EVERY == 0:
            messages.append(
                {
                    "role": "user",
                    "content": "<self_reflection>Re-evaluate plan quality, progress, and whether to delegate work.</self_reflection>",
                }
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": "I will self-check for tunnel vision and keep delegation healthy.",
                }
            )
        # s06: compression pipeline
        microcompact(messages)
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            print("[auto-compact triggered]")
            messages[:] = auto_compact(messages)
        if len(messages) > SCRATCHPAD_SUMMARY_TRIGGER:
            SCRATCHPADS_V2.autosummarize("lead", messages)
        # s08: drain background notifications
        notifs = BG.drain()
        if notifs:
            txt = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
            )
            messages.append(
                {
                    "role": "user",
                    "content": f"<background-results>\n{txt}\n</background-results>",
                }
            )
            messages.append(
                {"role": "assistant", "content": "Noted background results."}
            )
        # s10: check lead inbox
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append(
                {
                    "role": "user",
                    "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
                }
            )
            messages.append({"role": "assistant", "content": "Noted inbox messages."})
        # LLM call
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return
        # Tool execution
        results = []
        used_todo = False
        manual_compress = False
        used_tools: List[str] = []
        for block in response.content:
            if block.type == "tool_use":
                used_tools.append(block.name)
                if block.name == "compress":
                    manual_compress = True
                guard_error = _planner_guard(block.name)
                if guard_error:
                    output = guard_error
                    print(f"> {block.name}: {str(output)[:200]}")
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(output),
                        }
                    )
                    continue
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = (
                        handler(**block.input)
                        if handler
                        else f"Unknown tool: {block.name}"
                    )
                except Exception as e:
                    output = f"Error: {e}"
                print(f"> {block.name}: {str(output)[:200]}")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                )
                if block.name == "TodoWrite":
                    used_todo = True
        # s03: nag reminder
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if rounds_without_todo >= 3:
            results.insert(
                0, {"type": "text", "text": "<reminder>Update your todos.</reminder>"}
            )

        if used_tools and all(tool in inspection_tools for tool in used_tools):
            inspection_only_rounds += 1
        else:
            inspection_only_rounds = 0

        progress_now = _worker_progress_signature()
        if progress_now == last_progress:
            stalled_rounds += 1
        else:
            stalled_rounds = 0
        last_progress = progress_now

        if inspection_only_rounds >= 4 or stalled_rounds >= 6:
            results.insert(
                0,
                {
                    "type": "text",
                    "text": (
                        "<runtime_guard>No measurable execution progress detected. "
                        "Take one execution action now: spawn_worker, spawn_subplanner(parent='lead'), "
                        "optimistic_merge, task_update, or reconcile. "
                        "Avoid inspection-only loops.</runtime_guard>"
                    ),
                },
            )

        if stalled_rounds >= 10:
            forced = RECONCILIATION.run(1)
            print(f"> auto_reconcile: {forced[:200]}")
            results.insert(
                0,
                {
                    "type": "text",
                    "text": f"<auto_reconcile>{forced}</auto_reconcile>",
                },
            )
            try:
                forced_payload = json.loads(forced)
            except Exception:
                forced_payload = {}
            if forced_payload.get("verdict") == "PASS" and not any(
                status == "working" for status in WORKERS_V2.status.values()
            ):
                messages.append({"role": "user", "content": results})
                return
            stalled_rounds = 0
            inspection_only_rounds = 0

        messages.append({"role": "user", "content": results})
        # s06: manual compress
        if manual_compress:
            print("[manual compact]")
            messages[:] = auto_compact(messages)


# === SECTION: repl ===
if __name__ == "__main__":
    history = []
    while True:
        try:
            query = input("\033[36ms_full >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        if query.strip() == "/compact":
            if history:
                print("[manual compact via /compact]")
                history[:] = auto_compact(history)
            continue
        if query.strip() == "/tasks":
            print(TASK_MGR.list_all())
            continue
        if query.strip() == "/team":
            print(TEAM.list_all())
            continue
        if query.strip() == "/workers":
            print(WORKERS_V2.list_workers())
            continue
        if query.strip() == "/handoffs":
            print(HANDOFFS_V2.review(include_diff=False))
            continue
        if query.strip() == "/watchdog":
            print(WATCHDOG.render_events())
            continue
        if query.strip() == "/policy":
            print(ERROR_POLICY.status())
            continue
        if query.strip() == "/hierarchy":
            print(HIERARCHY.summary())
            continue
        if query.strip() == "/reconcile":
            print(RECONCILIATION.run())
            continue
        if query.strip().startswith("/scratch "):
            agent_id = query.strip().split(" ", 1)[1]
            print(
                SCRATCHPADS_V2.read(agent_id) or f"Scratchpad for {agent_id} is empty"
            )
            continue
        if query.strip() == "/inbox":
            print(json.dumps(BUS.read_inbox("lead"), indent=2))
            continue
        history.append({"role": "user", "content": query})
        agent_loop(history)
        print()
