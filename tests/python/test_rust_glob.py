import pytest

import harness.tools.worker_tools as worker_tools


@pytest.mark.asyncio
async def test_find_files_uses_rust_glob_when_enabled(monkeypatch, tmp_path):
    called = {"value": False}

    def fake_rust_glob(root_dir: str, pattern: str, max_results: int):
        called["value"] = True
        assert root_dir == str(tmp_path)
        assert pattern == "src/*.py"
        assert max_results == 10000
        return ["src/a.py", "src/b.py"]

    monkeypatch.setattr(worker_tools, "HAS_RUST_GREP", True)
    monkeypatch.setattr(worker_tools, "_rust_glob", fake_rust_glob)

    result = await worker_tools.find_files_handler(pattern="src/*.py", workspace_path=str(tmp_path), max_results=5)

    assert called["value"] is True
    assert result == {"files": ["src/a.py", "src/b.py"], "total": 2, "truncated": False}


@pytest.mark.asyncio
async def test_find_files_falls_back_to_pathlib_when_rust_disabled(monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a\n")
    (tmp_path / "src" / "b.py").write_text("b\n")
    (tmp_path / "src" / "c.txt").write_text("c\n")

    monkeypatch.setattr(worker_tools, "HAS_RUST_GREP", False)

    result = await worker_tools.find_files_handler(pattern="src/*.py", workspace_path=str(tmp_path), max_results=1)

    assert result["files"] == ["src/a.py"]
    assert result["total"] == 2
    assert result["truncated"] is True
