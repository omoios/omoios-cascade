import pytest

import harness_core


class TestRustShell:
    def test_run_command_basic(self, tmp_path):
        exit_code, stdout, stderr = harness_core.rust_run_command("echo hello", None, None)

        assert exit_code == 0
        assert stdout.strip() == "hello"
        assert stderr == ""

    def test_run_command_exit_code(self, tmp_path):
        exit_code, stdout, stderr = harness_core.rust_run_command("exit 1", None, None)

        assert exit_code == 1

    def test_run_command_stderr(self, tmp_path):
        exit_code, stdout, stderr = harness_core.rust_run_command("echo oops >&2", None, None)

        assert exit_code == 0
        assert "oops" in stderr

    def test_run_command_cwd(self, tmp_path):
        exit_code, stdout, stderr = harness_core.rust_run_command("pwd", str(tmp_path), None)

        assert exit_code == 0
        assert str(tmp_path) in stdout

    def test_run_command_timeout(self, tmp_path):
        with pytest.raises(RuntimeError, match="timed out"):
            harness_core.rust_run_command("sleep 10", None, 1)

    def test_run_command_complex(self, tmp_path):
        exit_code, stdout, stderr = harness_core.rust_run_command("echo abc | tr a-z A-Z", None, None)

        assert exit_code == 0
        assert stdout.strip() == "ABC"

    def test_run_command_env(self, tmp_path):
        exit_code, stdout, stderr = harness_core.rust_run_command("echo $HOME", None, None)

        assert exit_code == 0
        assert stdout.strip() != ""

    def test_run_command_no_timeout(self, tmp_path):
        exit_code, stdout, stderr = harness_core.rust_run_command("echo ok", None, None)

        assert exit_code == 0
        assert stdout.strip() == "ok"
