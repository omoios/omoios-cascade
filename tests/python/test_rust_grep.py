import pytest

import harness.tools.worker_tools as worker_tools


@pytest.mark.asyncio
async def test_grep_uses_rust_path_when_enabled(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("alpha\nneedle\nomega\n")
    called = {"value": False}

    def fake_rust_grep(root_dir: str, pattern: str, include: str | None, max_results: int):
        called["value"] = True
        assert root_dir == str(tmp_path)
        assert pattern == "needle"
        assert include == "*.py"
        assert max_results == 10000
        return [("a.py", 2, "needle")]

    monkeypatch.setattr(worker_tools, "HAS_RUST_GREP", True)
    monkeypatch.setattr(worker_tools, "_rust_grep", fake_rust_grep)

    result = await worker_tools.grep_handler(
        pattern="needle",
        path=".",
        workspace_path=str(tmp_path),
        include="*.py",
    )

    assert called["value"] is True
    assert result["truncated"] is False
    assert result["total"] == 1
    assert result["matches"] == [{"file": "a.py", "line": 2, "content": "needle"}]


@pytest.mark.asyncio
async def test_grep_falls_back_to_subprocess_when_rust_disabled(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("alpha\nneedle\nomega\n")
    (tmp_path / "b.txt").write_text("needle\n")

    monkeypatch.setattr(worker_tools, "HAS_RUST_GREP", False)

    result = await worker_tools.grep_handler(pattern="needle", path=".", workspace_path=str(tmp_path))

    assert result["truncated"] is False
    assert result["total"] == 2
    assert {m["file"] for m in result["matches"]} == {"a.py", "b.txt"}
