import pytest

from harness.tools.worker_tools import ask_handler, find_files_handler, grep_handler, todo_write_handler


class TestGrepHandler:
    @pytest.mark.asyncio
    async def test_grep_returns_matches(self, tmp_path):
        (tmp_path / "a.py").write_text("alpha\nneedle here\nomega\n")
        (tmp_path / "b.txt").write_text("needle in txt\n")

        result = await grep_handler(pattern="needle", path=".", workspace_path=str(tmp_path))

        assert result["truncated"] is False
        assert result["total"] == 2
        assert len(result["matches"]) == 2
        assert {m["file"] for m in result["matches"]} == {"a.py", "b.txt"}

    @pytest.mark.asyncio
    async def test_grep_path_escape_prevented(self, tmp_path):
        result = await grep_handler(pattern="needle", path="../", workspace_path=str(tmp_path))

        assert "error" in result
        assert "escapes workspace" in result["error"]

    @pytest.mark.asyncio
    async def test_grep_truncates_at_100(self, tmp_path):
        lines = "\n".join([f"needle-{i}" for i in range(120)]) + "\n"
        (tmp_path / "many.txt").write_text(lines)

        result = await grep_handler(pattern="needle", path="many.txt", workspace_path=str(tmp_path))

        assert result["total"] == 120
        assert result["truncated"] is True
        assert len(result["matches"]) == 100
        assert "notice" in result


class TestFindFilesHandler:
    @pytest.mark.asyncio
    async def test_find_files_glob_pattern(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("print('a')\n")
        (tmp_path / "src" / "b.py").write_text("print('b')\n")
        (tmp_path / "src" / "c.txt").write_text("c\n")

        result = await find_files_handler(pattern="src/*.py", workspace_path=str(tmp_path))

        assert result["truncated"] is False
        assert result["total"] == 2
        assert result["files"] == ["src/a.py", "src/b.py"]

    @pytest.mark.asyncio
    async def test_find_files_respects_max_results(self, tmp_path):
        for i in range(5):
            (tmp_path / f"f{i}.py").write_text("x\n")

        result = await find_files_handler(pattern="*.py", workspace_path=str(tmp_path), max_results=3)

        assert result["total"] == 5
        assert result["truncated"] is True
        assert len(result["files"]) == 3


class TestTodoWriteHandler:
    @pytest.mark.asyncio
    async def test_todo_write_valid_todos(self, tmp_path):
        todos = [
            {"content": "First task", "status": "pending", "priority": "high"},
            {"content": "Second task", "status": "in_progress", "priority": "medium"},
        ]

        result = await todo_write_handler(todos=todos, workspace_path=str(tmp_path))

        assert result == {"status": "ok", "count": 2}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "todo",
        [
            {"content": "Bad status", "status": "doing", "priority": "high"},
            {"content": "Bad priority", "status": "pending", "priority": "urgent"},
        ],
    )
    async def test_todo_write_invalid_status_or_priority(self, tmp_path, todo):
        result = await todo_write_handler(todos=[todo], workspace_path=str(tmp_path))

        assert "error" in result


class TestAskHandler:
    @pytest.mark.asyncio
    async def test_ask_handler_basic_question(self, tmp_path):
        result = await ask_handler(question="Need clarification?", workspace_path=str(tmp_path))

        assert result == {"status": "asked", "question": "Need clarification?"}
