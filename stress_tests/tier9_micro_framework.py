#!/usr/bin/env python3
"""Tier 9: Micro Web Framework (Mini Flask/Bottle).

Complexity: 15-25 workers, ~70 files, ~2000 LOC.
Task: Build a complete micro web framework with routing, middleware, templates,
sessions, forms, validation, ORM, blueprints, and testing utilities.

This tier tests the harness's ability to build a sophisticated framework with
many interlocking components including a mini ORM and full request/response cycle.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-9"
WORKER_TIMEOUT = 480

SCAFFOLD_FILES = {
    "framework/__init__.py": '''\
"""Micro Web Framework — A minimal web framework inspired by Flask."""

__version__ = "0.1.0"

from framework.app import App
from framework.request import Request
from framework.response import Response

__all__ = ["App", "Request", "Response"]
''',
    "framework/types.py": '''\
"""Core types for the framework."""

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class Request:
    """HTTP Request."""
    method: str = "GET"
    path: str = "/"
    query_string: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    
    @property
    def query_params(self) -> dict[str, str]:
        """Parse query string into dict."""
        result = {}
        if self.query_string:
            for part in self.query_string.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    result[k] = v
        return result
    
    @property
    def json(self) -> Any | None:
        """Parse JSON body."""
        import json
        try:
            return json.loads(self.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None


@dataclass
class Response:
    """HTTP Response."""
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    
    @classmethod
    def json(cls, data: Any, status: int = 200) -> "Response":
        """Create JSON response."""
        import json
        body = json.dumps(data).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        return cls(status=status, headers=headers, body=body)
    
    @classmethod
    def text(cls, text: str, status: int = 200) -> "Response":
        """Create text response."""
        body = text.encode("utf-8")
        headers = {"Content-Type": "text/plain"}
        return cls(status=status, headers=headers, body=body)
    
    @classmethod
    def redirect(cls, url: str, status: int = 302) -> "Response":
        """Create redirect response."""
        headers = {"Location": url}
        return cls(status=status, headers=headers)


Handler = Callable[[Request], Response | Awaitable[Response]]
Middleware = Callable[[Request, Callable[[Request], Response]], Response]
''',
    "tests/__init__.py": "",
    "tests/conftest.py": '''\
import pytest
from framework.app import App
from framework.request import Request
from framework.response import Response


@pytest.fixture
def app():
    """Provide a fresh app instance."""
    return App()


@pytest.fixture
def client(app):
    """Provide a test client."""
    from framework.testing import TestClient
    return TestClient(app)


@pytest.fixture
def sample_request():
    """Provide a sample request."""
    return Request(method="GET", path="/test", headers={"Accept": "text/html"})
''',
    "tests/test_types.py": """\
from framework.types import Request, Response


def test_request_query_params():
    req = Request(query_string="foo=bar&baz=qux")
    assert req.query_params == {"foo": "bar", "baz": "qux"}


def test_response_json():
    resp = Response.json({"key": "value"})
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "application/json"


def test_response_redirect():
    resp = Response.redirect("/other")
    assert resp.status == 302
    assert resp.headers["Location"] == "/other"
""",
}

INSTRUCTIONS = """\
Build a complete micro web framework called "framework". Use ONLY Python stdlib.
No external dependencies (no Flask, Bottle, Werkzeug, etc.). Build everything.

MODULE 1 — Request (`framework/request.py`):

1. Extend Request class from types.py:
   - `parse_form_data(self) -> dict[str, str]` — parse application/x-www-form-urlencoded
   - `parse_multipart(self) -> dict[str, Any]` — stub for multipart form data
   - `cookies(self) -> dict[str, str]` — parse Cookie header
   - `get_header(self, name: str, default=None)` — case-insensitive header lookup
   - `is_json(self) -> bool` — check Content-Type
   - `is_form(self) -> bool` — check Content-Type
   - `path_params(self) -> dict[str, str]` — storage for router-matched params
   - `__post_init__` to initialize path_params storage

MODULE 2 — Response (`framework/response.py`):

2. Extend Response class:
   - `set_cookie(self, name: str, value: str, max_age: int | None = None,
     httponly: bool = False, secure: bool = False)` — add Set-Cookie header
   - `delete_cookie(self, name: str)` — set expired cookie
   - `set_header(self, name: str, value: str)` — set header
   - `html(cls, content: str, status: int = 200) -> Response` — HTML response
   - `file(cls, path: str, status: int = 200) -> Response` — file response (read file)
   - `not_found(cls, message: str = "Not Found")` — 404 response
   - `error(cls, message: str, status: int = 500)` — error response
   - `to_wsgi(self) -> tuple` — convert to WSGI response tuple (status, headers, body)

MODULE 3 — Router (`framework/router.py`):

3. Create URL router:
   - `Route` dataclass: pattern (str), handler (Handler), methods (list[str]),
     name (str | None)
   - `Router` class:
     - `__init__(self)` — empty list of routes
     - `add(self, pattern: str, handler: Handler, methods: list[str] | None = None,
       name: str | None = None)` — add route
     - `get(self, pattern: str, handler: Handler, name: str | None = None)` — shortcut
     - `post(self, pattern: str, handler: Handler, name: str | None = None)` — shortcut
     - `put(self, pattern: str, handler: Handler, name: str | None = None)` — shortcut
     - `delete(self, pattern: str, handler: Handler, name: str | None = None)` — shortcut
     - `match(self, method: str, path: str) -> tuple[Handler, dict[str, str]] | None` —
       find matching route, extract path params like `:id` or `<int:id>`
     - Support pattern syntax: `/users`, `/users/:id`, `/users/<int:id>`,
       `/files/<path:filename>`
     - `url_for(self, name: str, **kwargs) -> str` — reverse URL lookup

MODULE 4 — App (`framework/app.py`):

4. Create main application class:
   - `App` class:
     - `__init__(self, name: str = "app")` — create router, empty middleware list,
       error handlers dict
     - `route(self, pattern: str, methods: list[str] | None = None)` — decorator
       for registering routes
     - `get/post/put/delete/patch` — method-specific decorators
     - `add_middleware(self, middleware: Middleware)` — add middleware to chain
     - `errorhandler(self, code: int)` — decorator for error handlers
     - `dispatch(self, request: Request) -> Response` — dispatch request through
       middleware chain to router
     - `wsgi_app(self, environ: dict, start_response) -> Iterable` — WSGI interface
     - `run(self, host: str = "127.0.0.1", port: int = 5000)` — run with wsgiref
   - Middleware chain: each middleware calls next, returns response

MODULE 5 — Middleware Package (`framework/middleware/`):

5. Create `framework/middleware/__init__.py`:
   - Export all middleware classes
   - `MiddlewareStack` class for managing middleware chain

6. Create `framework/middleware/cors.py`:
   - `CorsMiddleware` class:
     - `__init__(self, allow_origins: list[str], allow_methods: list[str],
       allow_headers: list[str])`
     - `__call__(request, next_handler)` — add CORS headers, handle preflight

7. Create `framework/middleware/logging.py`:
   - `LoggingMiddleware` class:
     - Logs method, path, status code, duration
     - `__call__(request, next_handler)` — time the request, log after

8. Create `framework/middleware/auth.py`:
   - `AuthMiddleware` class:
     - `__init__(self, exempt_paths: list[str])` — paths that skip auth
     - `__call__(request, next_handler)` — check for auth header, set request.user
     - `verify_token(self, token: str) -> dict | None` — stub token verification

9. Create `framework/middleware/rate_limit.py`:
   - `RateLimitMiddleware` class:
     - `__init__(self, requests_per_minute: int)`
     - Track requests by IP (in-memory dict)
     - Return 429 if limit exceeded

10. Create `framework/middleware/compression.py`:
    - `CompressionMiddleware` class:
      - Check Accept-Encoding header
      - If gzip supported and response large enough, compress body
      - Use gzip module from stdlib

11. Create `framework/middleware/static_files.py`:
    - `StaticFilesMiddleware` class:
      - `__init__(self, directory: str, url_prefix: str = "/static")`
      - Serve files from directory if path starts with url_prefix
      - Set appropriate Content-Type based on extension

MODULE 6 — Template Engine (`framework/template.py`):

12. Create standalone template engine (reuse concepts from tier 8):
    - `Template` class with render method
    - Support: {{ var }}, {% for %}, {% if %}, {% include %}, {% extends %}
    - `TemplateLoader` to load from directory
    - Built-in filters: escape, upper, lower, truncate, date
    - `render_template(app, name: str, **context) -> Response` helper

MODULE 7 — Sessions (`framework/session.py`):

13. Create cookie-based sessions:
    - `Session` class:
      - Dict-like interface for storing session data
      - `_modified` flag to track changes
    - `SessionStore` base class with methods: get, set, delete, clear
    - `SignedCookieSessionStore(SessionStore)`:
      - `__init__(self, secret_key: str, cookie_name: str = "session")`
      - Use hmac + hashlib to sign/verify cookies
      - JSON encode session data, sign with HMAC-SHA256
      - `load_from_cookie(self, cookie_value: str) -> Session`
      - `save_to_cookie(self, session: Session) -> str` — return signed cookie value
    - `get_session(request: Request, store: SessionStore) -> Session` helper
    - `save_session(response: Response, session: Session, store: SessionStore) -> None`

MODULE 8 — Forms (`framework/forms.py`):

14. Create form handling:
    - `Form` base class:
      - `__init__(self, data: dict)` — store form data
      - `is_valid(self) -> bool` — validate, return True if no errors
      - `errors(self) -> dict[str, list[str]]` — validation errors
      - `cleaned_data(self) -> dict` — validated/cleaned data
    - Field classes:
      - `Field` — base with required, validators list
      - `CharField(Field)` — min/max length validation
      - `EmailField(CharField)` — email format validation
      - `IntegerField(Field)` — integer conversion, min/max
      - `BooleanField(Field)` — bool conversion
      - `ChoiceField(Field)` — choices list validation
    - `Validator` callable type: (value) -> None or raise ValidationError
    - `ValidationError` exception

MODULE 9 — Validation (`framework/validation.py`):

15. Create request validation decorators:
    - `validate_json(schema: dict)` — decorator that validates request.json against schema
      Schema: {"field": (type, required)} e.g., {"name": (str, True), "age": (int, False)}
    - `validate_params(schema: dict)` — validates request.query_params
    - `validate_form(schema: dict)` — validates form data
    - On validation error, return 400 with {"errors": {...}}

MODULE 10 — Errors (`framework/errors.py`):

16. Create HTTP exception hierarchy:
    - `HTTPException(Exception)` — base with status_code, message, headers
    - `BadRequest(HTTPException)` — 400
    - `Unauthorized(HTTPException)` — 401
    - `Forbidden(HTTPException)` — 403
    - `NotFound(HTTPException)` — 404
    - `MethodNotAllowed(HTTPException)` — 405
    - `InternalServerError(HTTPException)` — 500
    - `abort(status: int, message: str = "")` — raise appropriate exception

MODULE 11 — Testing (`framework/testing.py`):

17. Create test utilities:
    - `TestClient` class:
      - `__init__(self, app: App)`
      - `get(path, query=None, headers=None) -> TestResponse`
      - `post(path, data=None, json=None, headers=None) -> TestResponse`
      - `put/delete/patch` — similar
      - `session` — access session data between requests
    - `TestResponse` class:
      - Wraps Response with test helpers
      - `status_code` property
      - `json()` — parse JSON body
      - `text` — decode body as text
      - `headers` — response headers
      - `cookies` — parsed Set-Cookie headers
      - `assert_status(self, code: int)` — assert helper
      - `assert_json(self, path: str, value)` — assert JSON path has value

MODULE 12 — Hooks (`framework/hooks.py`):

18. Create lifecycle hooks:
    - `HookManager` class:
      - `register(self, name: str, handler: Callable)` — register hook handler
      - `call(self, name: str, *args, **kwargs)` — call all handlers for hook
    - Hooks fired by App: before_request, after_request, teardown_request

MODULE 13 — Blueprints (`framework/blueprints.py`):

19. Create modular blueprints:
    - `Blueprint` class:
      - `__init__(self, name: str, url_prefix: str = "")`
      - `route(pattern, methods=None)` — decorator like App.route
      - `add_middleware(middleware)` — blueprint-specific middleware
      - `register(self, app: App, url_prefix: str | None = None)` — register to app
    - Routes registered on blueprint get prefixed with url_prefix
    - Middleware runs before app-level middleware

MODULE 14 — Config (`framework/config.py`):

20. Create configuration management:
    - `Config` class:
      - `__init__(self, root_path: str)`
      - `from_object(self, obj)` — load from object/module
      - `from_pyfile(self, filename)` — load from Python file
      - `from_envvar(self, varname)` — load from env var pointing to file
      - `get(self, key: str, default=None)` — dot notation access
      - `__getitem__`, `__setitem__` for dict-like access
    - Support common config: DEBUG, SECRET_KEY, DATABASE_URL, etc.

MODULE 15 — Utils (`framework/utils.py`):

21. Create utility functions:
    - `url_quote(s: str) -> str` — URL encode
    - `url_unquote(s: str) -> str` — URL decode
    - `parse_cookie_header(header: str) -> dict[str, str]`
    - `parse_multipart_boundary(content_type: str) -> str | None`
    - `MultiDict` class — dict that can have multiple values per key
    - `ImmutableMultiDict` — read-only version
    - `secure_filename(filename: str) -> str` — sanitize filename

MODULE 16 — Security (`framework/security.py`):

22. Create security utilities:
    - `generate_csrf_token() -> str` — random token
    - `validate_csrf_token(token: str, expected: str) -> bool` — constant-time compare
    - `hash_password(password: str) -> str` — use hashlib.pbkdf2_hmac
    - `verify_password(password: str, hash: str) -> bool` — verify PBKDF2 hash
    - `generate_random_string(length: int = 32) -> str` — cryptographically secure random

MODULE 17 — Cache (`framework/cache.py`):

23. Simple in-memory cache:
    - `Cache` class:
      - `__init__(self, default_ttl: int = 300)`
      - `get(self, key: str) -> Any | None`
      - `set(self, key: str, value: Any, ttl: int | None = None)` — ttl in seconds
      - `delete(self, key: str) -> bool`
      - `clear(self) -> None`
      - `keys(self) -> list[str]`
    - `cached(ttl: int)` — decorator to cache function results

MODULE 18 — Signals (`framework/signals.py`):

24. Create signal system:
    - `Signal` class:
      - `__init__(self, name: str)`
      - `connect(self, handler: Callable)` — connect handler
      - `disconnect(self, handler: Callable)`
      - `send(self, sender, **kwargs)` — call all handlers
    - `Namespace` class for organizing signals
    - `signal(name: str) -> Signal` — get or create signal

MODULE 19 — CLI (`framework/cli.py`):

25. Create CLI:
    - `main()` entry point
    - Subcommands:
      - `run` — run development server
      - `routes` — list all registered routes
      - `shell` — interactive shell with app context
    - Use argparse

MODULE 20 — ORM Package (`framework/orm/`):

26. Create `framework/orm/__init__.py`:
    - Export Model, Field, QuerySet, etc.

27. Create `framework/orm/fields.py`:
    - `Field` base class: name, type, nullable, default, primary_key
    - `CharField(Field)` — max_length, validation
    - `TextField(Field)` — long text
    - `IntegerField(Field)` — min, max
    - `FloatField(Field)`
    - `BooleanField(Field)`
    - `DateTimeField(Field)` — auto_now, auto_now_add
    - `ForeignKey(Field)` — to_model, on_delete (CASCADE, SET_NULL, PROTECT)
    - `ManyToManyField(Field)` — through table handling

28. Create `framework/orm/query.py`:
    - `QuerySet` class:
      - `__init__(self, model_class)`
      - `filter(self, **kwargs) -> QuerySet` — chainable filtering
      - `exclude(self, **kwargs) -> QuerySet` — chainable exclusion
      - `order_by(self, *fields) -> QuerySet` — sorting (+field asc, -field desc)
      - `limit(self, n: int) -> QuerySet`
      - `offset(self, n: int) -> QuerySet`
      - `first(self) -> Model | None`
      - `all(self) -> list[Model]`
      - `count(self) -> int`
      - `exists(self) -> bool`
      - `delete(self) -> int` — delete matching, return count
      - `_execute(self)` — internal: build and execute SQL

29. Create `framework/orm/model.py`:
    - `Model` base class:
      - `__init__(self, **kwargs)` — set field values
      - `__init_subclass__` — collect fields, set up table name
      - `save(self) -> None` — insert or update
      - `delete(self) -> None` — delete instance
      - `to_dict(self) -> dict`
      - `@classmethod objects(cls) -> QuerySet` — get QuerySet for model
      - `@classmethod get(cls, **kwargs) -> Model | None`
      - `@classmethod create(cls, **kwargs) -> Model`

30. Create `framework/orm/manager.py`:
    - `Manager` class — similar to QuerySet but bound to Model
    - Custom manager support via `objects = CustomManager()`

31. Create `framework/orm/migrations.py`:
    - `Migration` class: version, dependencies, operations list
    - `CreateTable(Operation)` — create table op
    - `AddField(Operation)` — add column op
    - `MigrationRunner` class:
      - `apply(migration)` — apply a migration
      - `rollback(migration)` — rollback a migration
      - `get_applied()` — list applied migrations
      - `get_pending()` — list pending migrations

MODULE 21 — Examples (`examples/`):

32. Create `examples/todo_app.py`:
    - Complete TODO API using the framework
    - Models: Todo with title, completed, created_at
    - Routes: GET/POST /todos, GET/PUT/DELETE /todos/:id
    - Use ORM, JSON responses

33. Create `examples/blog_app.py`:
    - Blog with templates
    - Models: Post, Comment
    - Routes: index, post detail, create post
    - Use templates, forms, sessions

MODULE 22 — Tests (`tests/`):

34. Create `tests/test_request.py` (3 tests):
    - test_request_cookies, test_request_form_data, test_request_json_parsing

35. Create `tests/test_response.py` (3 tests):
    - test_response_set_cookie, test_response_to_wsgi, test_response_html

36. Create `tests/test_router.py` (5 tests):
    - test_add_route, test_match_static_route, test_match_param_route,
    - test_match_method_filtering, test_url_for_reverse

37. Create `tests/test_app.py` (4 tests):
    - test_route_decorator, test_dispatch_request, test_error_handler,
    - test_middleware_chain

38. Create `tests/test_middleware/` (6 tests across 3 files):
    - test_cors.py: test_cors_headers, test_cors_preflight
    - test_logging.py: test_logging_middleware
    - test_static_files.py: test_serve_static_file, test_static_404

39. Create `tests/test_template.py` (4 tests):
    - test_render_variable, test_render_loop, test_render_if, test_template_inheritance

40. Create `tests/test_session.py` (3 tests):
    - test_session_store_get_set, test_signed_cookie_roundtrip, test_session_modified

41. Create `tests/test_forms.py` (4 tests):
    - test_char_field_validation, test_email_field, test_integer_field_range,
    - test_form_is_valid

42. Create `tests/test_validation.py` (3 tests):
    - test_validate_json_decorator, test_validate_params, test_validation_error_response

43. Create `tests/test_testing.py` (3 tests):
    - test_client_get, test_client_post_json, test_client_session

44. Create `tests/test_blueprints.py` (2 tests):
    - test_blueprint_register, test_blueprint_url_prefix

45. Create `tests/test_security.py` (3 tests):
    - test_password_hash_verify, test_csrf_token_generation, test_secure_filename

46. Create `tests/test_cache.py` (3 tests):
    - test_cache_get_set, test_cache_ttl_expiration, test_cached_decorator

47. Create `tests/test_orm/` (8 tests across 4 files):
    - test_fields.py: test_char_field, test_integer_validation
    - test_query.py: test_queryset_filter, test_queryset_order_by, test_queryset_chain
    - test_model.py: test_model_save, test_model_delete, test_model_to_dict
    - test_migrations.py: test_create_table_migration

Run `python -m pytest tests/ -v` to verify ALL 55 tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No Flask, no Django, no external packages.
- WSGI compatibility: app.wsgi_app must work with wsgiref.simple_server
- All SQL in ORM uses sqlite3 with parameterized queries
- All crypto uses hashlib/hmac from stdlib
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=9,
        name="Micro Web Framework",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=480,
        expected_test_count=55,
        max_planner_turns=150,
        max_planner_wall_time=1800,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
