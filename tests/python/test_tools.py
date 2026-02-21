import pytest

from harness.tools.planner_tools import create_default_registry
from harness.tools.worker_tools import (
    bash_handler,
    edit_file_handler,
    read_file_handler,
    submit_handoff_handler,
    write_file_handler,
)


class TestBashHandler:
    @pytest.mark.asyncio
    async def test_echo_hello(self, tmp_path):
        result = await bash_handler("echo hello", str(tmp_path))
        assert "hello" in result["stdout"]
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_false_command(self, tmp_path):
        result = await bash_handler("false", str(tmp_path))
        assert result["exit_code"] != 0

    @pytest.mark.asyncio
    async def test_stderr_capture(self, tmp_path):
        result = await bash_handler("echo err >&2", str(tmp_path))
        assert "err" in result["stderr"]

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self, tmp_path):
        result = await bash_handler("rm -rf /", str(tmp_path))
        assert "blocked" in result["stderr"].lower()
        assert result["exit_code"] == -1

    @pytest.mark.asyncio
    async def test_timeout(self, tmp_path):
        result = await bash_handler("sleep 10", str(tmp_path), timeout=1)
        assert "timed out" in result["stderr"].lower()
        assert result["exit_code"] == -1


class TestReadFileHandler:
    @pytest.mark.asyncio
    async def test_existing_file(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello\nWorld\nTest")

        result = await read_file_handler("test.txt", str(tmp_path))
        assert "Hello" in result["content"]
        assert "World" in result["content"]

    @pytest.mark.asyncio
    async def test_missing_file(self, tmp_path):
        result = await read_file_handler("nonexistent.txt", str(tmp_path))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_offset_and_limit(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("Line1\nLine2\nLine3\nLine4\nLine5")

        result = await read_file_handler("test.txt", str(tmp_path), offset=1, limit=2)
        content = result["content"].rstrip("\n")
        lines = content.split("\n")
        assert len(lines) == 2
        assert "Line2" in result["content"]
        assert "Line3" in result["content"]


class TestWriteFileHandler:
    @pytest.mark.asyncio
    async def test_creates_new_file(self, tmp_path):
        result = await write_file_handler("new.txt", "Hello World", str(tmp_path))
        assert result["bytes_written"] > 0
        assert (tmp_path / "new.txt").exists()
        assert (tmp_path / "new.txt").read_text() == "Hello World"

    @pytest.mark.asyncio
    async def test_overwrites_existing(self, tmp_path):
        test_file = tmp_path / "existing.txt"
        test_file.write_text("Original")

        result = await write_file_handler("existing.txt", "Updated", str(tmp_path))
        assert result["bytes_written"] > 0
        assert test_file.read_text() == "Updated"


class TestEditFileHandler:
    @pytest.mark.asyncio
    async def test_find_and_replace(self, tmp_path):
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Hello World")

        result = await edit_file_handler("edit.txt", "World", "Python", str(tmp_path))
        assert result["replacements"] == 1
        assert "Python" in test_file.read_text()

    @pytest.mark.asyncio
    async def test_old_string_not_found(self, tmp_path):
        test_file = tmp_path / "edit.txt"
        test_file.write_text("Hello World")

        result = await edit_file_handler("edit.txt", "NotFound", "Python", str(tmp_path))
        assert "error" in result


class TestSubmitHandoffHandler:
    @pytest.mark.asyncio
    async def test_handoff_submission(self):
        result = await submit_handoff_handler(
            agent_id="agent-1",
            task_id="task-1",
            status="completed",
            narrative="Task completed successfully",
        )
        assert result["submitted"] is True
        assert result["agent_id"] == "agent-1"
        assert result["task_id"] == "task-1"
        assert result["status"] == "completed"


class TestToolRegistry:
    def test_planner_tools_exclude_bash(self):
        registry = create_default_registry()
        names = registry.get_tool_names_for_role("root_planner")
        assert "bash" not in names

    def test_planner_tools_exclude_write_file(self):
        registry = create_default_registry()
        names = registry.get_tool_names_for_role("root_planner")
        assert "write_file" not in names

    def test_planner_tools_exclude_edit_file(self):
        registry = create_default_registry()
        names = registry.get_tool_names_for_role("root_planner")
        assert "edit_file" not in names

    def test_worker_tools_exclude_spawn_worker(self):
        registry = create_default_registry()
        names = registry.get_tool_names_for_role("worker")
        assert "spawn_worker" not in names

    def test_worker_tools_exclude_spawn_sub_planner(self):
        registry = create_default_registry()
        names = registry.get_tool_names_for_role("worker")
        assert "spawn_sub_planner" not in names

    def test_get_handler_returns_callable(self):
        registry = create_default_registry()
        handler = registry.get_handler("bash")
        assert handler is not None
        assert callable(handler)

    def test_get_handler_returns_none_for_unknown(self):
        registry = create_default_registry()
        assert registry.get_handler("nonexistent") is None

    def test_tool_schema_format(self):
        registry = create_default_registry()
        schemas = registry.get_tools_for_role("worker")
        for schema in schemas:
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema
