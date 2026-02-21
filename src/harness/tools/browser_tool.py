from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

HAS_PLAYWRIGHT = False
try:
    from playwright.async_api import Browser, Page, async_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    pass


class BrowserSession:
    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def ensure_browser(self) -> Page:
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

        if self._page is not None:
            return self._page

        self._playwright = await async_playwright().__aenter__()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()
        return self._page

    async def close(self):
        if self._page:
            await self._page.close()
            self._page = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.__aexit__(None, None, None)
            self._playwright = None


_sessions: dict[str, BrowserSession] = {}


def _get_session(session_id: str) -> BrowserSession:
    if session_id not in _sessions:
        _sessions[session_id] = BrowserSession()
    return _sessions[session_id]


async def browser_handler(
    action: str,
    url: str | None = None,
    selector: str | None = None,
    text: str | None = None,
    script: str | None = None,
    path: str | None = None,
    workspace_path: str = ".",
    session_id: str = "default",
) -> dict[str, Any]:
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright not installed. Run: pip install playwright && playwright install chromium"}

    session = _get_session(session_id)

    try:
        if action == "navigate":
            if not url:
                return {"error": "url is required for navigate action"}
            page = await session.ensure_browser()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            return {"status": "ok", "url": page.url, "title": await page.title()}

        elif action == "screenshot":
            page = await session.ensure_browser()
            screenshot_bytes = await page.screenshot(full_page=True)

            if path:
                save_path = Path(workspace_path) / path
                save_path.parent.mkdir(parents=True, exist_ok=True)
                save_path.write_bytes(screenshot_bytes)
                return {"status": "ok", "path": str(save_path), "size": len(screenshot_bytes)}
            else:
                b64 = base64.b64encode(screenshot_bytes).decode()
                return {"status": "ok", "base64": b64[:100] + "...", "size": len(screenshot_bytes)}

        elif action == "click":
            if not selector:
                return {"error": "selector is required for click action"}
            page = await session.ensure_browser()
            await page.click(selector, timeout=10000)
            return {"status": "ok", "selector": selector}

        elif action == "type":
            if not selector or not text:
                return {"error": "selector and text are required for type action"}
            page = await session.ensure_browser()
            await page.fill(selector, text, timeout=10000)
            return {"status": "ok", "selector": selector, "text_length": len(text)}

        elif action == "evaluate":
            if not script:
                return {"error": "script is required for evaluate action"}
            page = await session.ensure_browser()
            result = await page.evaluate(script)
            return {"status": "ok", "result": str(result)[:5000]}

        elif action == "get_text":
            page = await session.ensure_browser()
            if selector:
                element = await page.query_selector(selector)
                if element:
                    text_content = await element.text_content()
                    return {"status": "ok", "text": (text_content or "")[:5000]}
                return {"error": f"Element not found: {selector}"}
            else:
                text_content = await page.inner_text("body")
                return {"status": "ok", "text": text_content[:10000]}

        elif action == "accessibility_snapshot":
            page = await session.ensure_browser()
            snapshot = await page.accessibility.snapshot()
            return {"status": "ok", "snapshot": str(snapshot)[:10000]}

        elif action == "close":
            await session.close()
            _sessions.pop(session_id, None)
            return {"status": "ok", "message": "Browser closed"}

        else:
            return {
                "error": "Unknown action: "
                f"{action}. Valid: navigate, screenshot, click, type, evaluate, get_text, accessibility_snapshot, close"
            }

    except Exception as e:
        return {"error": f"Browser action failed: {type(e).__name__}: {str(e)[:500]}"}


async def visual_verify_handler(
    url: str,
    expected: str,
    workspace_path: str = ".",
    session_id: str = "default",
) -> dict[str, Any]:
    if not HAS_PLAYWRIGHT:
        return {"error": "Playwright not installed", "matches": False, "issues": ["Playwright not available"]}

    session = _get_session(session_id)

    try:
        page = await session.ensure_browser()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        screenshot_bytes = await page.screenshot(full_page=True)
        screenshot_path = Path(workspace_path) / ".screenshots" / "visual_verify.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(screenshot_bytes)

        page_text = await page.inner_text("body")
        title = await page.title()

        expected_lower = expected.lower()
        page_content = f"{title} {page_text}".lower()

        keywords = [w for w in expected_lower.split() if len(w) > 3]
        matched_keywords = [k for k in keywords if k in page_content]
        match_ratio = len(matched_keywords) / max(len(keywords), 1)

        issues: list[str] = []
        if match_ratio < 0.5:
            issues.append(f"Low keyword match: {len(matched_keywords)}/{len(keywords)} keywords found")
        if not title:
            issues.append("Page has no title")
        if len(page_text.strip()) < 50:
            issues.append("Page appears mostly empty")

        return {
            "matches": match_ratio >= 0.5 and not issues,
            "match_ratio": round(match_ratio, 2),
            "issues": issues,
            "screenshot_path": str(screenshot_path),
            "title": title,
        }

    except Exception as e:
        return {"matches": False, "issues": [f"Verification failed: {str(e)[:500]}"], "screenshot_path": ""}
