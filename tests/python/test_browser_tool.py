import pytest

from harness.tools.browser_tool import HAS_PLAYWRIGHT, BrowserSession, browser_handler, visual_verify_handler


@pytest.mark.asyncio
async def test_browser_handler_without_playwright():
    if HAS_PLAYWRIGHT:
        pytest.skip("Playwright is installed, testing without-playwright path not possible")
    result = await browser_handler(action="navigate", url="https://example.com")
    assert "error" in result
    assert "Playwright" in result["error"]


@pytest.mark.asyncio
async def test_browser_handler_unknown_action():
    if not HAS_PLAYWRIGHT:
        pytest.skip("Playwright not installed")
    result = await browser_handler(action="unknown_action")
    assert "error" in result
    assert "Unknown action" in result["error"]


@pytest.mark.asyncio
async def test_browser_handler_navigate_requires_url():
    if not HAS_PLAYWRIGHT:
        pytest.skip("Playwright not installed")
    result = await browser_handler(action="navigate")
    assert "error" in result


@pytest.mark.asyncio
async def test_visual_verify_without_playwright():
    if HAS_PLAYWRIGHT:
        pytest.skip("Playwright is installed")
    result = await visual_verify_handler(url="https://example.com", expected="test")
    assert result["matches"] is False
    assert "Playwright" in result["issues"][0] or "error" in result


@pytest.mark.asyncio
async def test_browser_session_close():
    session = BrowserSession()
    await session.close()


def test_browser_config_defaults():
    from harness.config import BrowserConfig

    config = BrowserConfig()
    assert config.enabled is False
    assert config.headless is True
    assert config.timeout == 30000


def test_harness_config_has_browser():
    from harness.config import HarnessConfig

    config = HarnessConfig(llm={"api_key": "test"})
    assert hasattr(config, "browser")
    assert config.browser.enabled is False
