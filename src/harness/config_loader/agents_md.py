from __future__ import annotations

from pathlib import Path


def load_agents_md(workspace_root: str | Path) -> str:
    workspace_root = Path(workspace_root).resolve()

    search_names = ["AGENTS.md", "CLAUDE.md"]
    search_dirs = [
        workspace_root / ".claude",
        workspace_root / ".codex",
        workspace_root / ".omp",
        workspace_root,
    ]

    collected: list[str] = []
    seen: set[Path] = set()

    for dir_path in search_dirs:
        if not dir_path.is_dir():
            continue
        for name in search_names:
            candidate = dir_path / name
            resolved = candidate.resolve() if candidate.exists() else candidate
            if candidate.is_file() and resolved not in seen:
                seen.add(resolved)
                collected.append(candidate.read_text(encoding="utf-8"))

    current = workspace_root.parent
    for _ in range(5):
        if current == current.parent:
            break
        for name in search_names:
            candidate = current / name
            resolved = candidate.resolve() if candidate.exists() else candidate
            if candidate.is_file() and resolved not in seen:
                seen.add(resolved)
                collected.append(candidate.read_text(encoding="utf-8"))
        current = current.parent

    return "\n\n---\n\n".join(collected)
