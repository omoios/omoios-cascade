#!/usr/bin/env python3
"""Tier 10: Full-Featured Text Browser.

Complexity: 20-30 workers, ~100+ files, ~3000 LOC.
Task: Build a FULL-featured text browser with network layer, HTML/CSS parsing,
layout engine, rendering, JavaScript stub, forms, bookmarks, history, and CLI.

This tier tests the harness's ability to build a complex application with many
layers: networking, parsing, layout, rendering, and interactive CLI. This is
approaching real-world browser complexity at educational scale.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-10"
WORKER_TIMEOUT = 600

SCAFFOLD_FILES = {
    "browser/__init__.py": '''\
"""Text Browser — A full-featured terminal web browser."""

__version__ = "0.1.0"

from browser.types import URL, Link, Page

__all__ = ["URL", "Link", "Page"]
''',
    "browser/types.py": '''\
"""Core types for the text browser."""

from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class Scheme(Enum):
    HTTP = "http"
    HTTPS = "https"
    FILE = "file"
    DATA = "data"


@dataclass
class URL:
    """Parsed URL components."""
    scheme: str = "http"
    host: str = ""
    port: int = 80
    path: str = "/"
    query: str = ""
    fragment: str = ""
    username: str = ""
    password: str = ""
    
    @property
    def origin(self) -> str:
        if self.scheme in ("http", "https"):
            port_str = f":{self.port}" if self.port not in (80, 443) else ""
            return f"{self.scheme}://{self.host}{port_str}"
        return ""
    
    def __str__(self) -> str:
        if self.scheme == "file":
            return f"file://{self.path}"
        q = f"?{self.query}" if self.query else ""
        f = f"#{self.fragment}" if self.fragment else ""
        auth = ""
        if self.username:
            auth = self.username
            if self.password:
                auth += f":{self.password}"
            auth += "@"
        return f"{self.scheme}://{auth}{self.host}{self.origin_suffix()}{self.path}{q}{f}"
    
    def origin_suffix(self) -> str:
        if self.scheme == "https" and self.port == 443:
            return ""
        if self.scheme == "http" and self.port == 80:
            return ""
        return f":{self.port}"


@dataclass
class Link:
    """An extracted hyperlink."""
    text: str
    href: str
    index: int = 0
    title: str = ""
    target: str = ""


@dataclass
class Page:
    """A fetched and parsed page."""
    url: URL
    status_code: int = 200
    title: str = ""
    text_content: str = ""
    html_content: str = ""
    links: list[Link] = field(default_factory=list)
    forms: list["Form"] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ""
    redirect_chain: list[str] = field(default_factory=list)
    load_time_ms: float = 0.0


@dataclass
class Form:
    """An HTML form."""
    action: str
    method: str = "GET"
    fields: list["FormField"] = field(default_factory=list)
    name: str = ""


@dataclass
class FormField:
    """A form field/input."""
    name: str
    type: str = "text"
    value: str = ""
    label: str = ""
    options: list[tuple[str, str]] = field(default_factory=list)
    required: bool = False
    placeholder: str = ""
''',
    "tests/__init__.py": "",
    "tests/conftest.py": """\
import pytest
from browser.types import URL, Page, Link


@pytest.fixture
def sample_url():
    return URL(scheme="https", host="example.com", path="/test", port=443)


@pytest.fixture
def sample_page():
    return Page(url=URL(host="example.com"), title="Test Page")


@pytest.fixture
def sample_link():
    return Link(text="Click here", href="/dest", index=1)
""",
    "tests/test_types.py": """\
from browser.types import URL, Link, Page


def test_url_origin():
    u = URL(scheme="https", host="example.com", port=443, path="/page")
    assert u.origin == "https://example.com"


def test_url_str():
    u = URL(host="example.com", path="/search", query="q=test")
    assert "example.com" in str(u)
    assert "/search" in str(u)


def test_page_defaults():
    p = Page(url=URL(host="example.com"), status_code=200)
    assert p.title == ""
    assert p.links == []
    assert p.error == ""
""",
}

INSTRUCTIONS = """\
Build a FULL-FEATURED text browser called "browser". Use ONLY Python stdlib.
No external dependencies. This is a major expansion of tier 5 with complete
networking, parsing, layout engine, rendering, forms, JS stub, and interactive CLI.

MODULE 1 — Network Layer (`browser/net/`):

1. Create `browser/net/__init__.py` — export all network classes

2. Create `browser/net/url.py`:
   - `parse_url(url_str: str, base: URL | None = None) -> URL` — full RFC-compliant URL
     parsing, handle relative URLs with base
   - `resolve_url(base: URL, relative: str) -> URL` — resolve relative URLs
   - `urlencode(params: dict) -> str` — encode query params
   - `urldecode(query: str) -> dict` — decode query string
   - `normalize_url(url: URL) -> URL` — lowercase host, default port, etc.

3. Create `browser/net/headers.py`:
   - `Headers` class — case-insensitive dict-like for HTTP headers
   - `parse_headers(raw: str) -> Headers` — parse raw header block
   - `format_headers(headers: Headers) -> str` — format for sending
   - `get_content_type(headers) -> str | None`
   - `get_charset(headers) -> str` — extract charset from Content-Type

4. Create `browser/net/cookie_jar.py`:
   - `Cookie` dataclass: name, value, domain, path, expires, secure, httponly
   - `CookieJar` class:
     - `set_cookie(self, cookie: Cookie) -> None`
     - `get_cookies(self, url: URL) -> list[Cookie]` — get applicable cookies
     - `clear(self) -> None`
     - `clear_expired(self) -> int` — remove expired, return count
     - `to_header_value(self, url: URL) -> str` — format for Cookie header
   - `parse_set_cookie(header: str, request_url: URL) -> Cookie`
   - Domain matching: exact match, or .domain suffix for subdomains

5. Create `browser/net/dns_cache.py`:
   - `DNSCache` class:
     - `__init__(self, ttl: int = 300)`
     - `resolve(self, hostname: str) -> str` — return IP, use socket.getaddrinfo
     - `cache` dict of hostname -> (ip, timestamp)
     - `clear(self) -> None`

6. Create `browser/net/connection_pool.py`:
   - `Connection` dataclass: socket, host, port, created_at, last_used
   - `ConnectionPool` class:
     - `__init__(self, max_connections: int = 10, max_idle: int = 60)`
     - `get_connection(self, host: str, port: int) -> Connection | None`
     - `put_connection(self, conn: Connection) -> None` — return to pool
     - `close_connection(self, conn: Connection) -> None`
     - `close_all(self) -> None`
   - HTTP/1.1 keep-alive support

7. Create `browser/net/http_client.py`:
   - `HTTPResponse` dataclass: status, headers, body, url, redirect_chain
   - `HTTPClient` class:
     - `__init__(self, timeout: int = 30, max_redirects: int = 5)`
     - `request(self, method: str, url: URL, headers: dict | None = None,
       body: bytes | None = None) -> HTTPResponse`
     - `get(self, url: URL) -> HTTPResponse` — convenience
     - `post(self, url: URL, data: dict | bytes) -> HTTPResponse`
     - Handle redirects (301, 302, 307, 308), tracking chain
     - Handle cookies via CookieJar
     - Handle chunked transfer encoding
     - Handle gzip/deflate Content-Encoding
     - Connection pooling via ConnectionPool
     - Proper request formatting: method, path, headers, body
     - Parse response status line, headers, body

MODULE 2 — Parser Layer (`browser/parser/`):

8. Create `browser/parser/__init__.py` — export parser classes

9. Create `browser/parser/html_tokenizer.py`:
   - Token types: DOCTYPE, START_TAG, END_TAG, TEXT, COMMENT
   - `Token` dataclass: type, name, data, attrs dict
   - `HTMLTokenizer` class:
     - `__init__(self, html: str)`
     - `tokenize(self) -> list[Token]` — char-by-char tokenization
     - Handle: tags, attributes (single/double/unquoted), entities, comments,
       CDATA, doctype
   - State machine: DATA, TAG_OPEN, TAG_NAME, BEFORE_ATTR, ATTR_NAME,
     AFTER_ATTR_NAME, BEFORE_ATTR_VALUE, ATTR_VALUE, etc.

10. Create `browser/parser/entity_decoder.py`:
    - `decode_entities(text: str) -> str` — replace &amp;, &lt;, &gt;, &quot;,
      &apos;, &nbsp;, and numeric entities (\u0026#123;)
    - `ENTITY_MAP` dict of named entities

11. Create `browser/parser/dom.py`:
    - `NodeType` enum: ELEMENT, TEXT, COMMENT, DOCUMENT
    - `Node` base class: type, parent, children list, attributes dict
    - `Element(Node)` — tag name, attrs, methods: get_attribute, set_attribute,
      get_elements_by_tag_name, get_element_by_id, query_selector (basic),
      text_content property
    - `TextNode(Node)` — text content
    - `Comment(Node)` — comment data
    - `Document(Node)` — root document node
    - `DOM` class: document root, create_element, create_text_node
    - Tree traversal: walk(), iter_text(), iter_elements()

12. Create `browser/parser/html_parser.py`:
    - `HTMLParser` class:
      - `__init__(self)`
      - `parse(self, html: str) -> Document` — tokenize and build DOM tree
      - Handle implied tags (html, head, body)
      - Handle self-closing tags
      - Handle foster parenting for misplaced elements
      - Build parent-child relationships correctly

13. Create `browser/parser/css_parser.py`:
    - `CSSSelector` class:
      - `__init__(self, selector: str)`
      - `matches(self, element: Element) -> bool`
      - Support: tag name, .class, #id, [attr], [attr=value], :first-child,
        descendant (space), child (>), adjacent sibling (+)
    - `parse_simple_selector(s: str) -> dict` — return parsed components

14. Create `browser/parser/css_properties.py`:
    - `CSSProperties` class — dict-like for style properties
    - `INHERITED_PROPERTIES` list: color, font-family, etc.
    - `is_inherited(prop: str) -> bool`
    - Parse inline style attribute (key: value;)
    - Known properties: display, color, background-color, font-size,
      font-weight, text-align, margin*, padding*, border*, width, height

MODULE 3 — Layout Engine (`browser/layout/`):

15. Create `browser/layout/__init__.py` — export layout classes

16. Create `browser/layout/box_model.py`:
    - `BoxModel` dataclass: content_width, content_height, padding (4 sides),
      border (4 sides), margin (4 sides)
    - `EdgeSizes` dataclass: top, right, bottom, left
    - `Rect` dataclass: x, y, width, height
    - `calculate_padding_box(box: BoxModel) -> Rect`
    - `calculate_border_box(box: BoxModel) -> Rect`
    - `calculate_margin_box(box: BoxModel) -> Rect`
    - `parse_length(value: str, parent_size: float, font_size: float) -> float` —
      parse px, em, %, rem

17. Create `browser/layout/block_layout.py`:
    - `BlockLayout` class:
      - `__init__(self, element: Element, parent: "BlockLayout | None")`
      - `layout(self, available_width: float) -> None` — calculate dimensions
      - `children: list[BlockLayout]` — child block containers
      - `position_children(self) -> None` — set child positions
    - Block formatting context: block elements stack vertically
    - Calculate widths based on available space and CSS

18. Create `browser/layout/inline_layout.py`:
    - `InlineLayout` class:
      - Layout inline elements within a line
      - `items: list[InlineItem]` — text runs, inline elements
      - `layout_line(self, available_width: float) -> float` — return height used
      - `LineBox` for each line of text
    - Inline formatting context: elements flow horizontally, wrap at width

19. Create `browser/layout/text_layout.py`:
    - `TextLayout` class:
      - `__init__(self, text: str, style: dict)`
      - `measure_width(self) -> float` — approximate using character count
      - `wrap(self, max_width: float) -> list[str]` — word wrap text
    - `measure_text(text: str, font_size: float) -> float` — rough estimation
    - Word breaking at spaces, hyphenation (simple)
    - Line breaking algorithm (greedy)

20. Create `browser/layout/table_layout.py`:
    - `TableLayout` class:
      - `__init__(self, table: Element)`
      - `calculate_column_widths(self, available_width: float) -> list[float]`
      - Distribute available width to columns
      - Support fixed and auto layout (simple)
    - `TableRow`, `TableCell` helper classes

21. Create `browser/layout/list_layout.py`:
    - `ListLayout` class:
      - `__init__(self, list_element: Element)`
      - `get_marker(self, index: int, list_type: str) -> str` — bullet, number,
        letter for ol/ul
      - Layout list items with indentation and markers

22. Create `browser/layout/layout_engine.py`:
    - `LayoutEngine` class:
      - `__init__(self, viewport_width: float, viewport_height: float)`
      - `layout(self, document: Document) -> LayoutTree` — build layout tree from DOM
      - `create_layout_node(self, element: Element) -> LayoutNode`
      - Determine display type (block, inline, none, list-item, table)
      - Build layout tree structure matching DOM
    - `LayoutTree` — root of layout tree
    - `LayoutNode` — base class for layout nodes

MODULE 4 — Render Layer (`browser/render/`):

23. Create `browser/render/__init__.py` — export render classes

24. Create `browser/render/screen_buffer.py`:
    - `ScreenBuffer` class:
      - `__init__(self, width: int, height: int)`
      - `clear(self) -> None`
      - `write(self, x: int, y: int, text: str, style: dict | None = None) -> None`
      - `write_line(self, y: int, text: str) -> None`
      - `get_line(self, y: int) -> str`
      - `scroll(self, lines: int) -> None`
      - `to_string(self) -> str` — full buffer as string

25. Create `browser/render/viewport.py`:
    - `Viewport` class:
      - `__init__(self, width: int, height: int)`
      - `scroll_x`, `scroll_y` — current scroll position
      - `scroll_to(self, x: int, y: int) -> None`
      - `scroll_by(self, dx: int, dy: int) -> None`
      - `visible_rect(self) -> tuple[int, int, int, int]` — (x, y, w, h)
      - `is_visible(self, rect) -> bool` — check if rect intersects viewport

26. Create `browser/render/text_renderer.py`:
    - `TextRenderer` class:
      - `__init__(self, buffer: ScreenBuffer, viewport: Viewport)`
      - `render_document(self, layout_tree: LayoutTree) -> None` — render to buffer
      - `render_block(self, block: BlockLayout, x: int, y: int) -> int` — return height
      - `render_inline(self, inline: InlineLayout, x: int, y: int) -> int`
      - `render_text(self, text: str, x: int, y: int, style: dict) -> int` — return width
      - Handle basic styles: bold (**), underline (__), italic

27. Create `browser/render/ansi_renderer.py`:
    - `ANSI_CODES` dict: reset, bold, dim, italic, underline, colors
    - `ANSIStyle` dataclass: bold, italic, underline, fg_color, bg_color
    - `ANSIRenderer(TextRenderer)`:
      - Override render to include ANSI escape codes
      - `style_to_ansi(style: dict) -> str` — convert style to ANSI codes
      - Support 256 colors
      - `strip_ansi(text: str) -> str` — remove codes for width calc

MODULE 5 — Engine (`browser/engine/`):

28. Create `browser/engine/__init__.py` — export engine classes

29. Create `browser/engine/browser.py`:
    - `Browser` class:
      - `__init__(self, config: "Config")`
      - `navigate(self, url_str: str) -> Page` — main navigation
        1. Parse URL (resolve relative if needed)
        2. Check cache
        3. Fetch via HTTP client
        4. Parse HTML
        5. Build layout
        6. Render to text
        7. Extract links and forms
        8. Update history
        9. Return Page
      - `reload(self) -> Page` — reload current
      - `stop(self) -> None` — stop loading
      - `current_page` property
      - `http_client` — HTTPClient instance
      - `cookie_jar` — CookieJar instance
      - `cache` — Cache instance

30. Create `browser/engine/tab.py`:
    - `Tab` class:
      - `__init__(self, browser: Browser, tab_id: int)`
      - `navigate(self, url: str) -> Page`
      - `back(self) -> Page | None` — go back in history
      - `forward(self) -> Page | None` — go forward
      - `history: list[str]` — URL history
      - `history_position: int` — current position
      - `add_to_history(self, url: str) -> None`
      - `current_url(self) -> str`

31. Create `browser/engine/tab_manager.py`:
    - `TabManager` class:
      - `__init__(self, browser: Browser)`
      - `create_tab(self) -> Tab` — create and return new tab
      - `close_tab(self, tab_id: int) -> bool`
      - `switch_tab(self, tab_id: int) -> Tab | None`
      - `list_tabs(self) -> list[tuple[int, str]]` — (id, title) pairs
      - `current_tab` property
      - `_next_id: int` counter

32. Create `browser/engine/bookmark.py`:
    - `Bookmark` dataclass: title, url, folder, created_at
    - `BookmarkManager` class:
      - `__init__(self, storage_path: str | None = None)`
      - `add(self, title: str, url: str, folder: str = "") -> Bookmark`
      - `remove(self, url: str) -> bool`
      - `list_all(self) -> list[Bookmark]`
      - `list_by_folder(self, folder: str) -> list[Bookmark]`
      - `search(self, query: str) -> list[Bookmark]`
      - `export_html(self) -> str` — Netscape bookmark format
      - `import_html(self, html: str) -> int` — import, return count

33. Create `browser/engine/history.py`:
    - `HistoryEntry` dataclass: url, title, visited_at
    - `HistoryManager` class:
      - `__init__(self, db_path: str = ":memory:")`
      - `add(self, url: str, title: str) -> None` — record visit
      - `get_recent(self, limit: int = 50) -> list[HistoryEntry]`
      - `search(self, query: str) -> list[HistoryEntry]`
      - `clear(self) -> None`
      - `delete_older_than(self, days: int) -> int` — delete old, return count
    - SQLite storage for persistence

34. Create `browser/engine/download.py`:
    - `Download` dataclass: url, path, filename, size, progress, status
    - `DownloadManager` class:
      - `__init__(self, download_dir: str)`
      - `download(self, url: str, filename: str | None = None) -> Download` —
        start download, return Download object
      - `list_downloads(self) -> list[Download]`
      - `get_download(self, download_id: int) -> Download | None`
      - `cancel(self, download_id: int) -> bool`
    - Save to file, track progress

MODULE 6 — Forms (`browser/forms/`):

35. Create `browser/forms/__init__.py` — export form classes

36. Create `browser/forms/form_parser.py`:
    - `FormParser` class:
      - `parse_forms(document: Document) -> list[Form]` — extract all forms from DOM
      - `parse_form_element(form_elem: Element) -> Form` — parse single form
      - Parse input fields: text, password, hidden, checkbox, radio, submit
      - Parse select elements with options
      - Parse textarea
      - Extract name, value, type, required, placeholder, label

37. Create `browser/forms/form_data.py`:
    - `FormData` class:
      - `__init__(self)`
      - `add(self, name: str, value: str) -> None`
      - `set(self, name: str, value: str) -> None`
      - `get(self, name: str) -> str | None`
      - `encode_urlencoded(self) -> bytes`
      - `encode_multipart(self, boundary: str) -> bytes` — stub for multipart
      - `from_dict(data: dict) -> FormData` — factory

38. Create `browser/forms/input_types.py`:
    - `InputHandler` base class for different input types
    - `TextInput(InputHandler)` — single line text
    - `PasswordInput(InputHandler)` — hidden input
    - `CheckboxInput(InputHandler)` — boolean, multiple values
    - `RadioInput(InputHandler)` — single selection from group
    - `SelectInput(InputHandler)` — dropdown selection
    - `TextareaInput(InputHandler)` — multi-line text
    - `get_handler(input_type: str) -> InputHandler` — factory

MODULE 7 — JavaScript Stub (`browser/js/`):

39. Create `browser/js/__init__.py` — export JS classes

40. Create `browser/js/runtime.py`:
    - `JSValue` base class for JS values
    - `JSUndefined`, `JSNull`, `JSBoolean`, `JSNumber`, `JSString`, `JSObject`, `JSArray`
    - `JSEnvironment` class: variable scope, lookup
    - `convert_to_js(value: Any) -> JSValue` — Python to JS
    - `convert_from_js(value: JSValue) -> Any` — JS to Python

41. Create `browser/js/lexer.py`:
    - Token types: NUMBER, STRING, IDENTIFIER, KEYWORD, OPERATOR, PUNCTUATION
    - `Lexer` class:
      - `__init__(self, source: str)`
      - `tokenize(self) -> list[Token]`
      - Handle: numbers (int/float), strings (single/double quotes), identifiers,
        keywords (var, let, const, function, return, if, else, while, for, etc.),
        operators (+, -, *, /, %, =, ==, ===, !=, <, >, <=, >=, &&, ||, !),
        punctuation (parens, braces, brackets, semicolon, comma, dot)

42. Create `browser/js/parser.py`:
    - AST node classes: Program, VariableDecl, FunctionDecl, Expression, BinaryOp,
      UnaryOp, Call, MemberAccess, Identifier, Literal, Block, If, While, Return
    - `Parser` class:
      - `__init__(self, tokens: list[Token])`
      - `parse(self) -> Program` — parse full program
      - `parse_statement(self) -> ASTNode`
      - `parse_expression(self) -> ASTNode`
      - `parse_primary(self) -> ASTNode`
      - Handle operator precedence

43. Create `browser/js/evaluator.py`:
    - `Evaluator` class:
      - `__init__(self, global_env: JSEnvironment)`
      - `evaluate(self, node: ASTNode) -> JSValue` — evaluate AST node
      - `eval_program(self, program: Program) -> JSValue`
      - `eval_call(self, call: Call) -> JSValue` — function calls
      - `eval_binary_op(self, op: BinaryOp) -> JSValue` — arithmetic, comparison
    - Support: arithmetic (+, -, *, /), string concat (+), comparison (==, !=, <, >),
      logical (&&, ||, !), variable access, assignment

44. Create `browser/js/builtins.py`:
    - `console` object: log(), error(), warn() methods
    - `Math` object: floor(), ceil(), round(), random(), max(), min(), abs(), sqrt()
    - `parseInt()`, `parseFloat()` functions
    - `String` prototype: length property, charAt(), substring(), indexOf()
    - `Array` prototype: length, push(), pop(), shift(), unshift(), indexOf()

MODULE 8 — Config (`browser/config.py`):

45. Create `browser/config.py`:
    - `Config` class:
      - `user_agent: str` — default "TextBrowser/0.1"
      - `homepage: str` — default "about:blank"
      - `timeout: int` — HTTP timeout
      - `max_redirects: int` — redirect limit
      - `enable_js: bool` — JS execution toggle
      - `enable_images: bool` — show image placeholders
      - `colors: dict` — color scheme
      - `width: int` — terminal width
      - `height: int` — terminal height
      - `load(self, path: str) -> None` — load from config file
      - `save(self, path: str) -> None` — save to config file

MODULE 9 — Cache (`browser/cache.py`):

46. Create `browser/cache.py`:
    - `CacheEntry` dataclass: url, content, headers, timestamp, etag
    - `HTTPCache` class:
      - `__init__(self, max_size: int = 100)`
      - `get(self, url: str) -> CacheEntry | None`
      - `put(self, url: str, response: HTTPResponse) -> None`
      - `is_fresh(self, entry: CacheEntry) -> bool` — check Cache-Control, Expires
      - `invalidate(self, url: str) -> bool`
      - `clear(self) -> None`
      - `get_stats(self) -> dict` — hits, misses, size

MODULE 10 — CLI (`browser/cli/`):

47. Create `browser/cli/__init__.py`

48. Create `browser/cli/repl.py`:
    - `REPL` class:
      - `__init__(self, browser: Browser)`
      - `run(self) -> None` — main REPL loop
      - `prompt: str` — current prompt (URL)
      - `read_command(self) -> str` — read user input
      - `evaluate(self, cmd: str) -> str` — execute command, return output
      - `print_output(self, output: str) -> None` — display output

49. Create `browser/cli/commands.py`:
    - `Command` class: name, description, handler
    - `CommandRegistry` class:
      - `register(cmd: Command) -> None`
      - `execute(name: str, args: list[str]) -> str` — run command, return output
    - Commands to implement:
      - `go <url>` — navigate to URL
      - `back` — go back
      - `forward` — go forward
      - `reload` — reload page
      - `links` — show numbered list of links
      - `follow <n>` — follow link number n
      - `tabs` — list tabs
      - `tab <n>` — switch to tab n
      - `newtab <url>` — open new tab
      - `closetab <n>` — close tab
      - `bookmarks` — list bookmarks
      - `bookmark` — bookmark current page
      - `history` — show browsing history
      - `download <url>` — download file
      - `js <code>` — execute JavaScript
      - `source` — show page source
      - `headers` — show response headers
      - `cookies` — show cookies for domain
      - `config` — show/edit config
      - `help` — show commands
      - `quit` — exit browser

50. Create `browser/cli/keybindings.py`:
    - `KeyBinding` dataclass: key, command, description
    - `KeyMap` class:
      - `__init__(self)`
      - `bind(self, key: str, command: str) -> None`
      - `lookup(self, key: str) -> str | None` — get command for key
      - `get_help(self) -> str` — formatted help text
    - Default bindings:
      - g: prompt for URL (go)
      - b: back
      - f: forward
      - r: reload
      - l: show links
      - n: next link (focus)
      - p: previous link
      - Enter: follow focused link
      - t: new tab
      - w: close tab
      - Tab: next tab
      - h: help
      - q: quit

MODULE 11 — Tests (`tests/`):

51. Create `tests/net/` package with `__init__.py`:
    - `test_url.py` (4 tests): test_parse_full_url, test_resolve_relative,
      test_urlencode_urldecode, test_normalize_url
    - `test_headers.py` (3 tests): test_case_insensitive, test_parse_headers,
      test_get_content_type
    - `test_cookie_jar.py` (4 tests): test_set_get_cookie, test_domain_matching,
      test_cookie_expiration, test_to_header_value
    - `test_dns_cache.py` (2 tests): test_cache_hit, test_ttl_expiration
    - `test_connection_pool.py` (2 tests): test_get_put_connection, test_max_connections
    - `test_http_client.py` (4 tests): test_get_request, test_post_request,
      test_redirect_following, test_cookie_handling

52. Create `tests/parser/` package with `__init__.py`:
    - `test_html_tokenizer.py` (4 tests): test_tokenize_tags, test_tokenize_attrs,
      test_tokenize_entities, test_tokenize_comments
    - `test_entity_decoder.py` (2 tests): test_named_entities, test_numeric_entities
    - `test_dom.py` (4 tests): test_create_element, test_append_child,
      test_get_elements_by_tag_name, test_text_content
    - `test_html_parser.py` (3 tests): test_parse_simple, test_parse_with_implied,
      test_parse_nested
    - `test_css_parser.py` (3 tests): test_tag_selector, test_class_selector,
      test_descendant_selector
    - `test_css_properties.py` (2 tests): test_parse_inline_style, test_inherited_props

53. Create `tests/layout/` package with `__init__.py`:
    - `test_box_model.py` (3 tests): test_box_dimensions, test_calculate_boxes,
      test_parse_length
    - `test_block_layout.py` (2 tests): test_block_stacking, test_layout_calculation
    - `test_inline_layout.py` (2 tests): test_inline_flow, test_line_breaking
    - `test_text_layout.py` (2 tests): test_measure_text, test_word_wrap
    - `test_table_layout.py` (2 tests): test_column_widths, test_table_structure

54. Create `tests/render/` package with `__init__.py`:
    - `test_screen_buffer.py` (3 tests): test_write_read, test_scroll, test_clear
    - `test_viewport.py` (2 tests): test_scroll_to, test_visible_rect
    - `test_text_renderer.py` (2 tests): test_render_block, test_render_inline
    - `test_ansi_renderer.py` (2 tests): test_ansi_codes, test_style_to_ansi

55. Create `tests/engine/` package with `__init__.py`:
    - `test_browser.py` (3 tests): test_navigate, test_reload, test_stop
    - `test_tab.py` (3 tests): test_back_forward, test_history, test_current_url
    - `test_tab_manager.py` (2 tests): test_create_close_tab, test_switch_tab
    - `test_bookmark.py` (3 tests): test_add_bookmark, test_export_import, test_search
    - `test_history.py` (2 tests): test_add_get_recent, test_search_history
    - `test_download.py` (2 tests): test_download_file, test_cancel_download

56. Create `tests/forms/` package with `__init__.py`:
    - `test_form_parser.py` (3 tests): test_parse_input_fields, test_parse_select,
      test_parse_textarea
    - `test_form_data.py` (2 tests): test_encode_urlencoded, test_from_dict
    - `test_input_types.py` (2 tests): test_text_input, test_checkbox_input

57. Create `tests/js/` package with `__init__.py`:
    - `test_runtime.py` (2 tests): test_js_values, test_conversion
    - `test_lexer.py` (3 tests): test_tokenize_numbers, test_tokenize_strings,
      test_tokenize_operators
    - `test_parser.py` (2 tests): test_parse_expression, test_parse_function
    - `test_evaluator.py` (3 tests): test_eval_arithmetic, test_eval_comparison,
      test_eval_variables
    - `test_builtins.py` (2 tests): test_console_log, test_math_functions

Run `python -m pytest tests/ -v` to verify ALL 74 tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No requests, no beautifulsoup, no html5lib, no lxml.
- HTTP/1.1 implementation uses socket module directly or http.client.
- All parsing is custom implementation (tokenizer, not regex-based).
- Layout is simplified but real: actual box model calculations.
- Rendering outputs plain text or ANSI codes.
- JavaScript is minimal but functional: variables, arithmetic, functions.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=10,
        name="Full Text Browser",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=600,
        expected_test_count=74,
        max_planner_turns=200,
        max_planner_wall_time=2400,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
