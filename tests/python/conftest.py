
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end tests that require full system")
    config.addinivalue_line("markers", "slow: tests that take significant time to run")


@pytest.fixture
def tmp_git_repo(tmp_path):
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    (repo_path / "README.md").write_text("# Test Repo\n")
    return repo_path


@pytest.fixture
def mock_config():
    from harness.config import HarnessConfig, LLMConfig

    return HarnessConfig(
        llm=LLMConfig(api_key="test-api-key-for-mocking"),
    )
