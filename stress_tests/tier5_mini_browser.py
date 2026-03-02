#!/usr/bin/env python3
"""Tier 5: Build a mini browser from near-scratch (Cursor-inspired).

Complexity: 5-8 workers, 12-15 files, ~300+ lines.
Task: Build a text-mode web browser with URL fetching, HTML parsing,
text rendering, link extraction, and a CLI interface.

This is the Cursor-scale challenge at educational scale — multiple modules
that must coordinate, with cross-cutting concerns (error handling, types).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-5"
WORKER_TIMEOUT = 240

SCAFFOLD_FILES = {
    "browser/__init__.py": "",
    "browser/types.py": '''\
from dataclasses import dataclass, field


@dataclass
class URL:
    """Parsed URL components."""
    scheme: str = "http"
    host: str = ""
    port: int = 80
    path: str = "/"
    query: str = ""
    fragment: str = ""

    @property
    def origin(self) -> str:
        port_str = f":{self.port}" if self.port not in (80, 443) else ""
        return f"{self.scheme}://{self.host}{port_str}"

    def __str__(self) -> str:
        q = f"?{self.query}" if self.query else ""
        f = f"#{self.fragment}" if self.fragment else ""
        return f"{self.origin}{self.path}{q}{f}"


@dataclass
class Link:
    """An extracted hyperlink."""
    text: str
    href: str
    index: int = 0


@dataclass
class Page:
    """A fetched and parsed page."""
    url: str
    status_code: int
    title: str = ""
    text_content: str = ""
    links: list[Link] = field(default_factory=list)
    error: str = ""
''',
    "tests/__init__.py": "",
    "tests/test_types.py": """\
from browser.types import URL, Link, Page


def test_url_origin():
    u = URL(scheme="https", host="example.com", port=443, path="/page")
    assert u.origin == "https://example.com"


def test_url_str():
    u = URL(host="example.com", path="/search", query="q=test")
    assert str(u) == "http://example.com/search?q=test"


def test_page_defaults():
    p = Page(url="http://example.com", status_code=200)
    assert p.title == ""
    assert p.links == []
    assert p.error == ""
""",
}

INSTRUCTIONS = """\
Build a text-mode web browser. The browser fetches URLs, parses HTML into text, \
extracts links, and provides a CLI for navigating pages. Use ONLY Python stdlib \
(urllib, html.parser, etc.) — no external dependencies.

The existing `browser/types.py` defines URL, Link, and Page dataclasses. \
Build everything else from scratch.

MODULE 1 — URL Parser (`browser/url_parser.py`):
- `parse_url(raw: str) -> URL` that handles:
  - Full URLs: "http://example.com/path?q=1#frag"
  - Scheme-relative: "//example.com/path"
  - Path-only: "/about" (relative to a base)
  - Defaults: scheme=http, port=80 (443 for https), path="/"
- `resolve_url(base: URL, relative: str) -> URL` that resolves relative URLs:
  - Absolute URLs returned as-is
  - "/path" replaces base path
  - "path" appends to base path directory
  - "#frag" updates fragment only

MODULE 2 — HTTP Fetcher (`browser/fetcher.py`):
- `fetch(url: URL, timeout: int = 10) -> tuple[int, dict[str, str], str]`
  Returns (status_code, headers_dict, body_text).
  Uses `urllib.request.urlopen`. Handles redirects (follow up to 5).
  On error (timeout, DNS, connection refused), return (0, {}, "") and set
  a descriptive error string.
- `FetchResult` dataclass: status_code, headers, body, error, redirect_chain

MODULE 3 — HTML Parser (`browser/html_parser.py`):
- Subclass `html.parser.HTMLParser` to extract:
  - `parse_html(html: str) -> ParseResult`
  - ParseResult dataclass with: title (from <title>), text (visible text),
    links (list of Link from <a href>)
  - Strip <script> and <style> content entirely
  - Collapse whitespace in text output
  - Extract text from: p, h1-h6, li, td, th, span, div, a

MODULE 4 — Text Renderer (`browser/renderer.py`):
- `render_page(page: Page, width: int = 80) -> str` that formats:
  - Title bar: "=== {title} ===" centered to width
  - URL line: "URL: {url}"
  - Separator line
  - Text content word-wrapped to width
  - Links section: numbered list "[1] link text (href)"
- `wrap_text(text: str, width: int = 80) -> str` — word-wrap preserving paragraph breaks

MODULE 5 — Browser Engine (`browser/engine.py`):
- `Browser` class:
  - `__init__(self)` — empty history list, current page None
  - `navigate(self, url_str: str) -> Page` — parse URL, fetch, parse HTML, build Page
  - `back(self) -> Page | None` — go to previous page in history
  - `current(self) -> Page | None` — current page
  - `history_list(self) -> list[str]` — URLs visited
  - `follow_link(self, index: int) -> Page` — follow numbered link from current page

MODULE 6 — CLI (`browser/cli.py`):
- `main()` function with a REPL loop:
  - `go <url>` — navigate to URL
  - `back` — go back
  - `links` — show numbered links
  - `follow <n>` — follow link number n
  - `quit` — exit
  - Display rendered page after each navigation

TESTS — Create comprehensive tests:

`tests/test_url_parser.py`:
- test_parse_full_url: parse "https://example.com:8080/path?q=1#top"
- test_parse_minimal: parse "example.com" → scheme=http, path="/"
- test_resolve_absolute: resolve absolute URL returns it unchanged
- test_resolve_relative_path: resolve "about" relative to "http://example.com/docs/"
- test_resolve_root_path: resolve "/about" relative to any base

`tests/test_html_parser.py`:
- test_parse_title: extract title from <title>Hello</title>
- test_parse_text: extract visible text, strip scripts/styles
- test_parse_links: extract href and text from <a> tags
- test_collapse_whitespace: multiple spaces/newlines collapsed

`tests/test_renderer.py`:
- test_render_title_bar: verify centered title line
- test_wrap_text: verify word wrapping at boundary
- test_render_links_section: verify numbered link format

`tests/test_engine.py`:
- test_navigate_builds_page: use a mock/fake fetch to verify navigate produces a Page
- test_history: navigate twice, verify history_list has 2 URLs
- test_back: navigate twice, back() returns first page

NOTE ON TESTING: For tests/test_engine.py, you CAN'T make real HTTP requests in tests. \
Instead, make the Browser class accept an optional `fetcher` callable in __init__ \
(defaulting to the real fetch function). Tests pass a fake fetcher that returns \
canned HTML responses. This is dependency injection for testability.

Run `python -m pytest tests/ -v` to verify all tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No requests, no beautifulsoup, no httpx.
- Use urllib.request for HTTP fetching.
- Use html.parser.HTMLParser for HTML parsing.
- The CLI does NOT need to be tested (interactive REPL).
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=5,
        name="Mini Browser (Cursor-Inspired)",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=240,
        expected_test_count=15,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
