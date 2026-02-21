import asyncio
import hashlib
import os
import shutil

from harness.models.handoff import FileDiff
from harness.models.workspace import Workspace, WorkspaceState

IGNORE_PATTERNS = [".git", ".workspaces", ".team", ".tasks", "node_modules", "__pycache__"]


async def create_workspace(repo_path: str, worker_id: str, workspaces_root: str | None = None) -> Workspace:
    if workspaces_root is None:
        workspaces_root = os.path.join(repo_path, ".workspaces")

    workspace_path = os.path.join(workspaces_root, worker_id)

    await asyncio.to_thread(
        shutil.copytree,
        repo_path,
        workspace_path,
        ignore=shutil.ignore_patterns(*IGNORE_PATTERNS),
        dirs_exist_ok=False,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "HEAD",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        base_commit = stdout.decode().strip() if proc.returncode == 0 else "no-git"
    except (FileNotFoundError, OSError):
        base_commit = "no-git"

    return Workspace(
        worker_id=worker_id,
        repo_path=repo_path,
        workspace_path=workspace_path,
        base_commit=base_commit,
        state=WorkspaceState.READY,
    )


def compute_diff(workspace: Workspace, base_snapshot: dict[str, str] | None = None) -> list[FileDiff]:
    current_snapshot = snapshot_workspace(workspace.workspace_path)

    if base_snapshot is None:
        return []

    diffs = []
    all_paths = set(base_snapshot.keys()) | set(current_snapshot.keys())

    for rel_path in sorted(all_paths):
        before_content = base_snapshot.get(rel_path)
        after_content = current_snapshot.get(rel_path)

        if before_content != after_content:
            before_hash = hashlib.md5(before_content.encode()).hexdigest() if before_content else None
            after_hash = hashlib.md5(after_content.encode()).hexdigest() if after_content else None

            if before_content is None:
                diff_text = f"+++ new file: {rel_path}"
            elif after_content is None:
                diff_text = f"--- deleted: {rel_path}"
            else:
                diff_text = f"--- modified: {rel_path}"

            diffs.append(
                FileDiff(
                    path=rel_path,
                    before_hash=before_hash,
                    after_hash=after_hash,
                    diff_text=diff_text,
                )
            )

    return diffs


def cleanup_workspace(workspace: Workspace) -> None:
    shutil.rmtree(workspace.workspace_path, ignore_errors=True)
    workspace.state = WorkspaceState.CLEANED


def snapshot_workspace(workspace_path: str) -> dict[str, str]:
    result = {}
    for root, _, files in os.walk(workspace_path):
        for filename in files:
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, workspace_path)

            for pattern in IGNORE_PATTERNS:
                if pattern in rel_path.split(os.sep):
                    break
            else:
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        result[rel_path] = f.read()
                except (UnicodeDecodeError, OSError):
                    pass

    return result
