import pytest

from harness.cli import create_parser, main


class TestCLI:
    def test_cli_version_command(self):
        assert main(["version"]) == 0

    def test_cli_run_requires_instructions(self):
        with pytest.raises(SystemExit):
            main(["run"])

    def test_cli_parser_run_args(self):
        parser = create_parser()
        parsed = parser.parse_args(["run", "-i", "test task"])

        assert parsed.instructions == "test task"
        assert parsed.command == "run"

    def test_cli_parser_repos(self):
        parser = create_parser()
        parsed = parser.parse_args(["run", "-i", "test", "--repos", "a", "b"])

        assert parsed.repos == ["a", "b"]
