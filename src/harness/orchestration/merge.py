import os
from uuid import uuid4

from harness.git.workspace import snapshot_workspace
from harness.models import FileDiff, MergeResult, MergeStatus, Task, Workspace


def optimistic_merge(
    workspace: Workspace,
    canonical_path: str,
    idempotency_guard=None,
    base_snapshot: dict[str, str] | None = None,
) -> MergeResult:
    if idempotency_guard and not idempotency_guard.can_merge_handoff(workspace.worker_id):
        return MergeResult(worker_id=workspace.worker_id, status=MergeStatus.NO_CHANGES)

    canonical_snapshot = snapshot_workspace(canonical_path)
    worker_snapshot = snapshot_workspace(workspace.workspace_path)
    if base_snapshot is None:
        base_snapshot = dict(canonical_snapshot)

    changed_paths = sorted(
        path
        for path in (set(base_snapshot.keys()) | set(worker_snapshot.keys()))
        if worker_snapshot.get(path) != base_snapshot.get(path)
    )

    if not changed_paths:
        if idempotency_guard:
            idempotency_guard.mark_handoff_merged(workspace.worker_id)
        return MergeResult(worker_id=workspace.worker_id, status=MergeStatus.NO_CHANGES)

    files_merged: list[str] = []
    conflicts: list[str] = []

    for rel_path in changed_paths:
        base_content = base_snapshot.get(rel_path)
        worker_content = worker_snapshot.get(rel_path)
        canonical_content = canonical_snapshot.get(rel_path)

        if canonical_content != base_content:
            conflicts.append(rel_path)
            continue

        target_path = os.path.join(canonical_path, rel_path)
        if worker_content is None:
            if os.path.exists(target_path):
                os.remove(target_path)
                files_merged.append(rel_path)
        else:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(worker_content)
            files_merged.append(rel_path)

    if idempotency_guard:
        idempotency_guard.mark_handoff_merged(workspace.worker_id)

    if conflicts:
        conflict_diffs = [FileDiff(path=path, diff_text=f"--- conflict: {path}") for path in conflicts]
        fix_forward_task = Task(
            id=f"fix-forward-{workspace.worker_id}-{uuid4().hex[:8]}",
            title=f"Fix-forward merge conflicts for {workspace.worker_id}",
            description=(
                "Optimistic merge detected conflicts. Resolve directly on canonical state.\n\n" + "\n".join(conflicts)
            ),
            metadata={"conflicts": conflicts, "diffs": [diff.model_dump() for diff in conflict_diffs]},
        )
        return MergeResult(
            worker_id=workspace.worker_id,
            status=MergeStatus.CONFLICT,
            files_merged=files_merged,
            conflicts=conflicts,
            fix_forward_task=fix_forward_task,
        )

    if not files_merged:
        return MergeResult(worker_id=workspace.worker_id, status=MergeStatus.NO_CHANGES)

    return MergeResult(
        worker_id=workspace.worker_id,
        status=MergeStatus.CLEAN,
        files_merged=files_merged,
        conflicts=[],
        fix_forward_task=None,
    )
