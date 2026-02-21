from harness.config_loader.agents_md import load_agents_md


def test_load_agents_md_finds_workspace_agents_md(tmp_path):
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text("workspace-agents", encoding="utf-8")

    content = load_agents_md(tmp_path)

    assert "workspace-agents" in content


def test_load_agents_md_finds_claude_md_in_dot_claude(tmp_path):
    dot_claude = tmp_path / ".claude"
    dot_claude.mkdir()
    claude_file = dot_claude / "CLAUDE.md"
    claude_file.write_text("claude-instructions", encoding="utf-8")

    content = load_agents_md(tmp_path)

    assert "claude-instructions" in content


def test_load_agents_md_returns_empty_when_no_files_exist(tmp_path):
    content = load_agents_md(tmp_path)

    assert content == ""


def test_load_agents_md_deduplicates_same_file_via_symlinked_dirs(tmp_path):
    dot_claude = tmp_path / ".claude"
    dot_claude.mkdir()
    agents_file = dot_claude / "AGENTS.md"
    agents_file.write_text("shared-content", encoding="utf-8")

    codex_link = tmp_path / ".codex"
    codex_link.symlink_to(dot_claude, target_is_directory=True)

    content = load_agents_md(tmp_path)

    assert content.count("shared-content") == 1
