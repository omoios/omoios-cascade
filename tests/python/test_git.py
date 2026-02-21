import os
import subprocess

import pytest

from harness.git.commit import commit_changes
from harness.git.workspace import (
    cleanup_workspace,
    compute_diff,
    create_workspace,
    snapshot_workspace,
)
from harness.models.coherence import IdempotencyGuard
from harness.models.merge import MergeStatus
from harness.models.workspace import WorkspaceState
from harness.orchestration.merge import optimistic_merge


@pytest.fixture
def git_repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    (repo_path / "file1.txt").write_text("content 1")
    (repo_path / "file2.txt").write_text("content 2")

    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo_path,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )

    return repo_path


def test_create_workspace(git_repo):
    workspace = create_workspace(str(git_repo), "worker1")

    assert os.path.exists(workspace.workspace_path)
    assert os.path.isfile(os.path.join(workspace.workspace_path, "file1.txt"))
    assert os.path.isfile(os.path.join(workspace.workspace_path, "file2.txt"))
    assert workspace.state == WorkspaceState.READY


def test_workspace_isolation(git_repo):
    workspace1 = create_workspace(str(git_repo), "worker1")
    workspace2 = create_workspace(str(git_repo), "worker2")

    ws1_file = os.path.join(workspace1.workspace_path, "file1.txt")
    ws1_file_content = "modified content"
    with open(ws1_file, "w") as f:
        f.write(ws1_file_content)

    ws2_file = os.path.join(workspace2.workspace_path, "file1.txt")
    with open(ws2_file, "r") as f:
        ws2_content = f.read()

    assert ws2_content == "content 1"


def test_compute_diff_detects_changes(git_repo):
    workspace = create_workspace(str(git_repo), "worker1")

    base_snapshot = snapshot_workspace(workspace.workspace_path)

    ws_file = os.path.join(workspace.workspace_path, "file1.txt")
    with open(ws_file, "w") as f:
        f.write("modified content")

    diffs = compute_diff(workspace, base_snapshot)

    assert len(diffs) == 1
    assert diffs[0].path == "file1.txt"


def test_compute_diff_no_changes(git_repo):
    workspace = create_workspace(str(git_repo), "worker1")

    base_snapshot = snapshot_workspace(workspace.workspace_path)

    diffs = compute_diff(workspace, base_snapshot)

    assert diffs == []


def test_compute_diff_new_file(git_repo):
    workspace = create_workspace(str(git_repo), "worker1")

    base_snapshot = snapshot_workspace(workspace.workspace_path)

    new_file = os.path.join(workspace.workspace_path, "new_file.txt")
    with open(new_file, "w") as f:
        f.write("new content")

    diffs = compute_diff(workspace, base_snapshot)

    assert len(diffs) == 1
    assert diffs[0].path == "new_file.txt"


def test_cleanup_workspace(git_repo):
    workspace = create_workspace(str(git_repo), "worker1")

    assert os.path.exists(workspace.workspace_path)

    cleanup_workspace(workspace)

    assert not os.path.exists(workspace.workspace_path)
    assert workspace.state == WorkspaceState.CLEANED


def test_snapshot_workspace(git_repo):
    workspace = create_workspace(str(git_repo), "worker1")

    snapshot = snapshot_workspace(workspace.workspace_path)

    assert "file1.txt" in snapshot
    assert "file2.txt" in snapshot
    assert snapshot["file1.txt"] == "content 1"
    assert snapshot["file2.txt"] == "content 2"


class TestCommitChanges:
    def test_commit_new_file(self, git_repo):
        new_file = git_repo / "new.txt"
        new_file.write_text("new content")

        commit_hash = commit_changes(str(git_repo), "add new file")

        assert commit_hash != ""

    def test_commit_nothing(self, git_repo):
        commit_hash = commit_changes(str(git_repo), "no-op commit")

        assert commit_hash == ""


class TestOptimisticMerge:
    def test_clean_merge_new_file(self, git_repo):
        workspace = create_workspace(str(git_repo), "worker-merge-new")
        base_snapshot = snapshot_workspace(workspace.workspace_path)

        new_file = os.path.join(workspace.workspace_path, "merged_new.txt")
        with open(new_file, "w") as file_handle:
            file_handle.write("new from worker")

        result = optimistic_merge(workspace, str(git_repo), base_snapshot=base_snapshot)

        assert result.status == MergeStatus.CLEAN
        assert "merged_new.txt" in result.files_merged
        assert (git_repo / "merged_new.txt").read_text() == "new from worker"

    def test_clean_merge_modified_file(self, git_repo):
        workspace = create_workspace(str(git_repo), "worker-merge-mod")
        base_snapshot = snapshot_workspace(workspace.workspace_path)

        ws_file = os.path.join(workspace.workspace_path, "file1.txt")
        with open(ws_file, "w") as file_handle:
            file_handle.write("worker modified")

        result = optimistic_merge(workspace, str(git_repo), base_snapshot=base_snapshot)

        assert result.status == MergeStatus.CLEAN
        assert "file1.txt" in result.files_merged
        assert (git_repo / "file1.txt").read_text() == "worker modified"

    def test_conflict_detection(self, git_repo):
        workspace = create_workspace(str(git_repo), "worker-merge-conflict")
        base_snapshot = snapshot_workspace(workspace.workspace_path)

        ws_file = os.path.join(workspace.workspace_path, "file1.txt")
        with open(ws_file, "w") as file_handle:
            file_handle.write("worker version")

        (git_repo / "file1.txt").write_text("canonical version")

        result = optimistic_merge(workspace, str(git_repo), base_snapshot=base_snapshot)

        assert result.status == MergeStatus.CONFLICT
        assert "file1.txt" in result.conflicts
        assert result.fix_forward_task is not None

    def test_no_changes(self, git_repo):
        workspace = create_workspace(str(git_repo), "worker-merge-no-changes")
        base_snapshot = snapshot_workspace(workspace.workspace_path)

        result = optimistic_merge(workspace, str(git_repo), base_snapshot=base_snapshot)

        assert result.status == MergeStatus.NO_CHANGES
        assert result.files_merged == []

    def test_idempotency_prevents_duplicate_merge(self, git_repo):
        workspace = create_workspace(str(git_repo), "worker-merge-idempotent")
        base_snapshot = snapshot_workspace(workspace.workspace_path)

        new_file = os.path.join(workspace.workspace_path, "idempotent.txt")
        with open(new_file, "w") as file_handle:
            file_handle.write("first merge")

        guard = IdempotencyGuard()

        first_result = optimistic_merge(
            workspace,
            str(git_repo),
            idempotency_guard=guard,
            base_snapshot=base_snapshot,
        )
        second_result = optimistic_merge(
            workspace,
            str(git_repo),
            idempotency_guard=guard,
            base_snapshot=base_snapshot,
        )

        assert first_result.status == MergeStatus.CLEAN
        assert second_result.status == MergeStatus.NO_CHANGES
