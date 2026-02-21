import pytest

from harness.tools import web_tools


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200, headers: dict | None = None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}


class _FakeClient:
    def __init__(self, response: _FakeResponse):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, follow_redirects: bool = True):
        _ = url
        _ = follow_redirects
        return self._response


@pytest.mark.asyncio
async def test_http_fetch_handler_without_httpx(monkeypatch):
    monkeypatch.setattr(web_tools, "HAS_HTTPX", False)
    monkeypatch.setattr(web_tools, "httpx", None)

    result = await web_tools.http_fetch_handler(workspace_path=".", url="https://example.com")
    assert result["exit_code"] == -1
    assert "uv add httpx" in result["error"]


@pytest.mark.asyncio
async def test_http_fetch_handler_truncates_large_response(monkeypatch):
    payload = b"a" * (web_tools.MAX_RESPONSE_BYTES + 500)
    fake_httpx = type("FakeHttpx", (), {"AsyncClient": lambda timeout: _FakeClient(_FakeResponse(payload))})
    monkeypatch.setattr(web_tools, "HAS_HTTPX", True)
    monkeypatch.setattr(web_tools, "httpx", fake_httpx)

    result = await web_tools.http_fetch_handler(workspace_path=".", url="https://example.com")
    assert result["exit_code"] == 0
    assert result["truncated"] is True
    assert len(result["output"].encode()) <= web_tools.MAX_RESPONSE_BYTES


@pytest.mark.asyncio
async def test_url_extract_handler_strips_html(monkeypatch):
    html = b"<html><body><h1>Title</h1><p>Hello world</p></body></html>"
    fake_httpx = type(
        "FakeHttpx",
        (),
        {
            "AsyncClient": lambda timeout: _FakeClient(
                _FakeResponse(html, headers={"content-type": "text/html; charset=utf-8"})
            )
        },
    )
    monkeypatch.setattr(web_tools, "HAS_HTTPX", True)
    monkeypatch.setattr(web_tools, "httpx", fake_httpx)
    monkeypatch.setattr(web_tools, "HAS_MARKDOWNIFY", False)

    result = await web_tools.url_extract_handler(workspace_path=".", url="https://example.com")
    assert result["exit_code"] == 0
    assert "Title" in result["output"]
    assert "Hello world" in result["output"]
    assert "<html>" not in result["output"].lower()
