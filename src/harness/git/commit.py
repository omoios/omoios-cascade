import asyncio


async def commit_changes(repo_path: str, message: str, author: str = "harness") -> str:
    try:
        add_proc = await asyncio.create_subprocess_exec(
            "git",
            "add",
            "-A",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await add_proc.communicate()
        if add_proc.returncode != 0:
            return ""

        commit_proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            message,
            "--author",
            f"{author} <{author}@harness>",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        commit_stdout, commit_stderr = await commit_proc.communicate()

        if commit_proc.returncode != 0:
            output = f"{commit_stdout.decode()}\n{commit_stderr.decode()}".lower()
            if "nothing to commit" in output or "no changes added to commit" in output:
                return ""
            return ""

        hash_proc = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "HEAD",
            cwd=repo_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        hash_stdout, _ = await hash_proc.communicate()
        if hash_proc.returncode != 0:
            return ""

        return hash_stdout.decode().strip()
    except (FileNotFoundError, OSError):
        return ""
