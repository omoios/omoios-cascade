import os

import pytest

import harness_core
from harness.git.workspace import cleanup_workspace, create_workspace

pytestmark = pytest.mark.slow


class TestWorkspaceIntegration:
    @pytest.mark.asyncio
    async def test_create_workspace(self, tmp_git_repo, tmp_path):
        ws = await create_workspace(
            repo_path=str(tmp_git_repo),
            worker_id="worker-1",
            workspaces_root=str(tmp_path / "ws"),
        )

        assert os.path.isdir(ws.workspace_path)

    @pytest.mark.asyncio
    async def test_workspace_has_copy_of_files(self, tmp_git_repo, tmp_path):
        src_file = os.path.join(str(tmp_git_repo), "source.txt")
        with open(src_file, "w") as f:
            f.write("original content")
        os.system(f"cd {tmp_git_repo} && git add -A && git commit -m init 2>/dev/null")

        ws = await create_workspace(
            repo_path=str(tmp_git_repo),
            worker_id="worker-2",
            workspaces_root=str(tmp_path / "ws"),
        )

        copied = os.path.join(ws.workspace_path, "source.txt")
        assert os.path.exists(copied)

    @pytest.mark.asyncio
    async def test_workspace_isolation(self, tmp_git_repo, tmp_path):
        src_file = os.path.join(str(tmp_git_repo), "isolate.txt")
        with open(src_file, "w") as f:
            f.write("original")
        os.system(f"cd {tmp_git_repo} && git add -A && git commit -m init 2>/dev/null")

        ws = await create_workspace(
            repo_path=str(tmp_git_repo),
            worker_id="worker-3",
            workspaces_root=str(tmp_path / "ws"),
        )

        ws_file = os.path.join(ws.workspace_path, "isolate.txt")
        with open(ws_file, "w") as f:
            f.write("modified")

        with open(src_file) as f:
            assert f.read() == "original"

    @pytest.mark.asyncio
    async def test_workspace_cleanup(self, tmp_git_repo, tmp_path):
        ws = await create_workspace(
            repo_path=str(tmp_git_repo),
            worker_id="worker-4",
            workspaces_root=str(tmp_path / "ws"),
        )

        assert os.path.isdir(ws.workspace_path)
        cleanup_workspace(ws)
        assert not os.path.exists(ws.workspace_path)

    def test_snapshot_workspace_returns_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.py").write_text("bbb")

        result = harness_core.snapshot_workspace(str(tmp_path))

        assert isinstance(result, dict)
        assert len(result) >= 2

    def test_compute_diff_detects_changes(self, tmp_path):
        (tmp_path / "file.txt").write_text("before")
        snap1 = harness_core.snapshot_workspace(str(tmp_path))

        (tmp_path / "file.txt").write_text("after")
        snap2 = harness_core.snapshot_workspace(str(tmp_path))

        diff = harness_core.compute_diff(snap1, snap2)
        assert len(diff) > 0

    def test_compute_diff_detects_new_files(self, tmp_path):
        (tmp_path / "old.txt").write_text("old")
        snap1 = harness_core.snapshot_workspace(str(tmp_path))

        (tmp_path / "new.txt").write_text("new")
        snap2 = harness_core.snapshot_workspace(str(tmp_path))

        diff = harness_core.compute_diff(snap1, snap2)
        assert len(diff) > 0

    def test_compute_diff_no_changes(self, tmp_path):
        (tmp_path / "same.txt").write_text("same")
        snap1 = harness_core.snapshot_workspace(str(tmp_path))
        snap2 = harness_core.snapshot_workspace(str(tmp_path))

        diff = harness_core.compute_diff(snap1, snap2)
        assert len(diff) == 0

    @pytest.mark.asyncio
    async def test_multiple_workspaces_isolated(self, tmp_git_repo, tmp_path):
        ws1 = await create_workspace(
            repo_path=str(tmp_git_repo),
            worker_id="worker-a",
            workspaces_root=str(tmp_path / "ws"),
        )
        ws2 = await create_workspace(
            repo_path=str(tmp_git_repo),
            worker_id="worker-b",
            workspaces_root=str(tmp_path / "ws"),
        )

        assert ws1.workspace_path != ws2.workspace_path
        assert os.path.isdir(ws1.workspace_path)
        assert os.path.isdir(ws2.workspace_path)
