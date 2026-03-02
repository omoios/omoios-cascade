"""Shared scaffolding utilities for stress test repos.

Each tier creates a fresh git repo at /tmp/harness-tier-{N}/ with starter
code appropriate for that tier's complexity level. The scaffold functions
are idempotent — they nuke and recreate the repo each time.
"""

import os
import shutil
import subprocess
from pathlib import Path


def create_repo(repo_path: str, files: dict[str, str]) -> Path:
    """Create a fresh git repo with the given files.

    Args:
        repo_path: Absolute path for the repo (e.g. /tmp/harness-tier-1)
        files: Mapping of relative file paths to content strings

    Returns:
        Path object for the created repo
    """
    repo = Path(repo_path)

    # Nuke if exists
    if repo.exists():
        shutil.rmtree(repo)

    repo.mkdir(parents=True)

    # Write all files
    for rel_path, content in files.items():
        full_path = repo / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

    # Git init + commit
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "stress-test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "stress-test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "Initial scaffold"], cwd=repo, check=True, capture_output=True, env=env)

    return repo


def reset_repo(repo_path: str) -> None:
    """Reset a repo to its initial commit state."""
    subprocess.run(["git", "checkout", "--", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=repo_path, check=True, capture_output=True)
