import os
import subprocess

import pytest

from harness.tools.git_tools import git_branch_handler, git_commit_handler, git_diff_handler, git_status_handler


@pytest.fixture
def git_workspace(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "file.txt").write_text("hello\n")
    subprocess.run(["git", "init"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )
    return repo


@pytest.mark.asyncio
async def test_git_status_handler_reports_changes(git_workspace):
    (git_workspace / "file.txt").write_text("changed\n")
    result = await git_status_handler(workspace_path=str(git_workspace))
    assert result["exit_code"] == 0
    assert "file.txt" in result["output"]


@pytest.mark.asyncio
async def test_git_diff_handler_supports_staged(git_workspace):
    (git_workspace / "file.txt").write_text("changed\n")
    subprocess.run(["git", "add", "file.txt"], cwd=git_workspace, check=True)
    result = await git_diff_handler(workspace_path=str(git_workspace), staged=True)
    assert result["exit_code"] == 0
    assert "diff --git" in result["output"]


@pytest.mark.asyncio
async def test_git_commit_requires_message(git_workspace):
    result = await git_commit_handler(workspace_path=str(git_workspace), message="")
    assert result["exit_code"] == -1
    assert "Commit message is required" in result["error"]


@pytest.mark.asyncio
async def test_git_commit_and_branch_handlers(git_workspace, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

    (git_workspace / "file.txt").write_text("changed\n")
    commit_result = await git_commit_handler(workspace_path=str(git_workspace), message="update file")
    assert commit_result["exit_code"] == 0

    create_branch = await git_branch_handler(workspace_path=str(git_workspace), create=True, name="feature/test")
    assert create_branch["exit_code"] == 0
    assert "Switched to a new branch" in create_branch["output"]

    list_branch = await git_branch_handler(workspace_path=str(git_workspace))
    assert list_branch["exit_code"] == 0
    assert "feature/test" in list_branch["output"]
