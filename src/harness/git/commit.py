import subprocess


def commit_changes(repo_path: str, message: str, author: str = "harness") -> str:
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )

        commit_result = subprocess.run(
            ["git", "commit", "-m", message, "--author", f"{author} <{author}@harness>"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )

        if commit_result.returncode != 0:
            output = f"{commit_result.stdout}\n{commit_result.stderr}".lower()
            if "nothing to commit" in output or "no changes added to commit" in output:
                return ""
            return ""

        hash_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return hash_result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
