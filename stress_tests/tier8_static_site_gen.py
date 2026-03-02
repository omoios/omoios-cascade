#!/usr/bin/env python3
"""Tier 8: Static Site Generator (Jekyll/Hugo-style).

Complexity: 12-18 workers, ~50 files, ~1500 LOC.
Task: Build a full static site generator with markdown parsing, frontmatter,
custom template engine, taxonomy, pagination, feeds, sitemaps, and asset handling.

This tier tests the harness's ability to build a complex content processing
pipeline with parsing, transformation, and output generation.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-8"
WORKER_TIMEOUT = 420

SCAFFOLD_FILES = {
    "sitegen/__init__.py": '''\
"""Static Site Generator — Build sites from markdown and templates."""

__version__ = "0.1.0"
''',
    "sitegen/types.py": '''\
"""Core types for the static site generator."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Page:
    """A single page in the site."""
    title: str
    content: str = ""
    slug: str = ""
    layout: str = "default"
    draft: bool = False
    date: datetime | None = None
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None
    output_path: str = ""


@dataclass
class Site:
    """The complete site being generated."""
    title: str = "My Site"
    base_url: str = "http://localhost:8000"
    pages: list[Page] = field(default_factory=list)
    tags: dict[str, list[Page]] = field(default_factory=dict)
    categories: dict[str, list[Page]] = field(default_factory=dict)
    static_files: list[Path] = field(default_factory=list)
''',
    "content/post1.md": """\
---
title: "Hello World"
date: 2024-01-15
tags: [intro, welcome]
categories: [general]
---

# Welcome

This is the first post on our new site.

## Getting Started

- Install the generator
- Write content
- Build your site
""",
    "content/post2.md": """\
---
title: "Advanced Features"
date: 2024-02-01
tags: [advanced, tutorial]
categories: [docs]
---

# Advanced Features

Learn about the advanced features available.

## Topics

- Templates
- Taxonomies
- Plugins
""",
    "content/post3.md": """\
---
title: "Draft Post"
date: 2024-03-01
tags: [draft]
draft: true
---

# Draft

This post is a draft and should not be published.
""",
    "templates/base.html": """\
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
</head>
<body>
    {% block content %}{% endblock %}
</body>
</html>
""",
    "templates/post.html": """\
{% extends "base.html" %}

{% block content %}
<article>
    <h1>{{ title }}</h1>
    <time>{{ date }}</time>
    <div class="content">
        {{ content }}
    </div>
    <div class="tags">
        {% for tag in tags %}
        <span>{{ tag }}</span>
        {% endfor %}
    </div>
</article>
{% endblock %}
""",
    "static/style.css": """\
body {
    font-family: sans-serif;
    max-width: 800px;
    margin: 0 auto;
    padding: 20px;
}

h1 { color: #333; }

.tags span {
    background: #eee;
    padding: 4px 8px;
    margin-right: 8px;
    border-radius: 4px;
}
""",
    "tests/__init__.py": "",
    "tests/conftest.py": """\
import pytest
from sitegen.types import Page, Site


@pytest.fixture
def sample_page():
    return Page(
        title="Test Page",
        content="# Hello",
        slug="test-page",
        tags=["test", "demo"],
        categories=["general"]
    )


@pytest.fixture
def sample_site():
    return Site(title="Test Site", base_url="http://test.com")
""",
    "tests/test_types.py": """\
from sitegen.types import Page, Site


def test_page_defaults():
    p = Page(title="Test")
    assert p.slug == ""
    assert p.tags == []
    assert p.draft is False


def test_site_creation():
    s = Site(title="My Site")
    assert s.title == "My Site"
    assert s.pages == []
""",
}

INSTRUCTIONS = """\
Build a complete static site generator called "sitegen". Use ONLY Python stdlib.
No external dependencies (no Jinja2, no markdown, no yaml). Build everything from
scratch.

MODULE 1 — Frontmatter Parser (`sitegen/frontmatter.py`):

1. Create frontmatter parsing:
   - `parse_frontmatter(content: str) -> tuple[dict, str]` — extract YAML-like frontmatter
     between --- delimiters, return (metadata_dict, remaining_content)
   - Support string, int, bool, list values
   - Handle missing frontmatter (return empty dict, full content)
   - `dump_frontmatter(metadata: dict, content: str) -> str` — serialize back to string

MODULE 2 — Markdown Parser (`sitegen/parser.py`):

2. Create a custom markdown parser (NO external libs):
   - `parse_markdown(text: str) -> str` — convert markdown to HTML
   - Support:
     - Headers: # ## ### (with id slugs)
     - Bold: **text** and __text__ → <strong>
     - Italic: *text* and _text_ → <em>
     - Inline code: `code` → <code>
     - Code blocks: ```lang\ncode\n``` → <pre><code class="lang">
     - Links: [text](url) → <a href="url">
     - Images: ![alt](src) → <img alt="alt" src="src">
     - Unordered lists: - item or * item → <ul><li>
     - Ordered lists: 1. item → <ol><li>
     - Blockquotes: > text → <blockquote>
     - Horizontal rules: --- or *** → <hr>
     - Paragraphs: blank line separation → <p>
   - `extract_headers(html: str) -> list[tuple[int, str, str]]` — return (level, text, id)
   for TOC generation

MODULE 3 — Template Engine (`sitegen/template_engine.py`):

3. Create a template engine (NO Jinja2):
   - `Template` class:
     - `__init__(self, source: str)` — parse template source
     - `render(context: dict) -> str` — render with context variables
   - Support syntax:
     - `{{ variable }}` — variable substitution (with . access: post.title)
     - `{% for item in items %}` ... `{% endfor %}` — loops
     - `{% if condition %}` ... `{% elif condition %}` ... `{% else %}` ... `{% endif %}`
     - `{% include "template.html" %}` — include other templates
     - `{% extends "base.html" %}` + `{% block name %}` ... `{% endblock %}` — inheritance
   - `TemplateLoader` class for loading from directory:
     - `__init__(self, template_dir: str)`
     - `load(name: str) -> Template`
     - `exists(name: str) -> bool`

MODULE 4 — Content Loader (`sitegen/content_loader.py`):

4. Create content loading:
   - `ContentLoader` class:
     - `__init__(self, content_dir: str)`
     - `load_all() -> list[Page]` — recursively find all .md files
     - `load_file(path: Path) -> Page` — load single file, parse frontmatter+markdown
     - `should_process(path: Path) -> bool` — check if file should be processed
       (skip drafts in production mode, etc.)
   - `generate_slug(path: Path, title: str) -> str` — create URL-friendly slug

MODULE 5 — Taxonomy (`sitegen/taxonomy.py`):

5. Create taxonomy indexing:
   - `TaxonomyIndex` class:
     - `__init__(self)` — empty indexes for tags and categories
     - `add_page(page: Page) -> None` — add page to tag/category indexes
     - `get_pages_by_tag(tag: str) -> list[Page]`
     - `get_pages_by_category(category: str) -> list[Page]`
     - `get_all_tags() -> list[str]` — sorted list of tags
     - `get_all_categories() -> list[str]` — sorted list of categories
     - `get_tag_cloud() -> list[tuple[str, int]]` — list of (tag, count) sorted by count

MODULE 6 — Pagination (`sitegen/pagination.py`):

6. Create pagination:
   - `Paginator` class:
     - `__init__(self, items: list, per_page: int)`
     - `page_count() -> int`
     - `get_page(number: int) -> list` — 1-indexed page numbers
     - `get_page_info(number: int) -> dict` — return dict with:
       items, page_number, per_page, total_items, total_pages, has_prev, has_next,
       prev_page, next_page
   - `paginate_pages(pages: list[Page], per_page: int, base_path: str) -> list[tuple[str, dict]]`
     — return list of (output_path, context) for each page

MODULE 7 — Permalinks (`sitegen/permalink.py`):

7. Create permalink generation:
   - `PermalinkGenerator` class:
     - `__init__(self, pattern: str = "/:slug/")`
     - `generate(page: Page) -> str` — generate URL from pattern
   - Support patterns:
     - `:slug` — page slug
     - `:year`, `:month`, `:day` — from page.date
     - `:category` — first category
     - `:title` — URL-encoded title
   - `normalize_path(path: str) -> str` — ensure leading/trailing slashes

MODULE 8 — Feed Generator (`sitegen/feed.py`):

8. Create RSS/Atom feeds:
   - `FeedGenerator` class:
     - `__init__(self, site: Site)`
     - `generate_rss(pages: list[Page], feed_path: str) -> str` — generate RSS 2.0 XML
     - `generate_atom(pages: list[Page], feed_path: str) -> str` — generate Atom XML
   - Proper XML escaping, RFC 822 dates for RSS, ISO 8601 for Atom
   - Include title, link, description, pubDate/updated, items with guid/id

MODULE 9 — Sitemap Generator (`sitegen/sitemap.py`):

9. Create XML sitemap:
   - `SitemapGenerator` class:
     - `__init__(self, site: Site)`
     - `generate(pages: list[Page]) -> str` — generate sitemap.xml content
   - Include loc, lastmod (if available), changefreq (default weekly), priority
   - `save(path: str, content: str) -> None`

MODULE 10 — Asset Handling (`sitegen/assets.py`):

10. Create asset processing:
    - `AssetProcessor` class:
      - `__init__(self, static_dir: str, output_dir: str)`
      - `copy_static() -> list[str]` — copy all static files, return list of copied paths
      - `fingerprint(path: str) -> str` — add content hash to filename for cache busting
        (style.css → style.a1b2c3.css)
      - `process_assets() -> dict[str, str]` — copy with fingerprinting, return mapping
        of original -> fingerprinted paths for template use

MODULE 11 — Filters (`sitegen/filters.py`):

11. Create template filters:
    - `date_format(date: datetime, format: str) -> str` — format date using strftime
    - `slugify(text: str) -> str` — convert to URL-friendly slug
    - `truncate(text: str, length: int, suffix: str = "...") -> str`
    - `strip_html(html: str) -> str` — remove HTML tags
    - `sort_by(items: list, key: str) -> list` — sort list of dicts/objects by key
    - `group_by(items: list, key: str) -> dict[str, list]` — group into dict
    - `where(items: list, key: str, value) -> list` — filter items by key=value
    - `limit(items: list, count: int) -> list` — limit to N items
    - `FilterRegistry` class to register and lookup filters

MODULE 12 — Shortcodes (`sitegen/shortcodes.py`):

12. Create shortcode expansion:
    - `ShortcodeParser` class:
      - `__init__(self)` — empty dict of registered shortcodes
      - `register(name: str, handler: Callable) -> None` — register a shortcode handler
      - `parse(text: str) -> str` — expand all {{ shortcode param=value }} in text
    - Built-in shortcodes:
      - `youtube(id: str) -> str` — embed YouTube iframe
      - `gist(url: str) -> str` — link to gist
      - `figure(src: str, caption: str = "") -> str` — figure/caption HTML

MODULE 13 — Configuration (`sitegen/config.py`):

13. Create site configuration:
    - `Config` class:
      - `__init__(self, defaults: dict | None = None)`
      - `load(path: str) -> None` — load from YAML-like config file
      - `get(key: str, default=None)` — dot notation access ("build.per_page")
      - `to_dict() -> dict`
    - Support config options:
      - title, description, base_url
      - build.per_page, build.drafts, build.future
      - permalinks.pattern

MODULE 14 — Builder (`sitegen/builder.py`):

14. Create the main builder:
    - `SiteBuilder` class:
      - `__init__(self, config: Config, content_dir: str, template_dir: str,
        static_dir: str, output_dir: str)`
      - `build() -> BuildResult` — orchestrate full build
      - Steps:
        1. Load all content
        2. Filter drafts if not in draft mode
        3. Build taxonomy index
        4. Generate pages (content, tag pages, category pages)
        5. Copy/process assets
        6. Generate feeds
        7. Generate sitemap
      - `BuildResult` dataclass with pages_built, assets_copied, errors list

MODULE 15 — Watcher (`sitegen/watcher.py`):

15. Create file watcher (stub):
    - `FileWatcher` class:
      - `__init__(self, paths: list[str])`
      - `start(on_change: Callable[[str], None]) -> None` — start watching (stub)
      - `stop() -> None` — stop watching (stub)
      - `get_changed_files() -> list[str]` — return list of changed files (stub)
    - `should_rebuild_page(changed_path: str, page: Page) -> bool` — check if page
      needs rebuild based on changed file

MODULE 16 — Server (`sitegen/server.py`):

16. Create dev server:
    - `DevServer` class:
      - `__init__(self, output_dir: str, port: int = 8000)`
      - `start() -> None` — start http.server in thread
      - `stop() -> None` — stop server
      - `reload() -> None` — trigger rebuild

MODULE 17 — CLI (`sitegen/cli.py`):

17. Create CLI:
    - `main()` entry point with argparse
    - Subcommands:
      - `build` — build the site
      - `serve` — build and serve with auto-reload
      - `new <type> <name>` — create new content (post, page)
    - Proper exit codes and help text

MODULE 18 — Tests (`tests/`):

18. Create `tests/test_frontmatter.py` (4 tests):
    - test_parse_frontmatter_basic, test_parse_no_frontmatter,
    - test_parse_frontmatter_lists, test_dump_frontmatter

19. Create `tests/test_parser.py` (6 tests):
    - test_parse_headers, test_parse_bold_italic, test_parse_links_images,
    - test_parse_lists, test_parse_code_blocks, test_parse_blockquotes

20. Create `tests/test_template_engine.py` (6 tests):
    - test_render_variable, test_render_loop, test_render_if_else,
    - test_template_include, test_template_extends, test_complex_template

21. Create `tests/test_content_loader.py` (3 tests):
    - test_load_single_file, test_load_all_content, test_generate_slug

22. Create `tests/test_taxonomy.py` (4 tests):
    - test_add_page_tags, test_get_pages_by_tag, test_get_tag_cloud,
    - test_multiple_tags

23. Create `tests/test_pagination.py` (3 tests):
    - test_paginator_basic, test_paginator_edge_cases, test_page_info

24. Create `tests/test_permalink.py` (3 tests):
    - test_permalink_slug, test_permalink_date_components, test_permalink_category

25. Create `tests/test_feed.py` (2 tests):
    - test_generate_rss, test_generate_atom

26. Create `tests/test_sitemap.py` (2 tests):
    - test_generate_sitemap, test_sitemap_escaping

27. Create `tests/test_assets.py` (2 tests):
    - test_copy_static, test_fingerprint

28. Create `tests/test_filters.py` (4 tests):
    - test_slugify, test_truncate, test_sort_by, test_group_by

29. Create `tests/test_shortcodes.py` (3 tests):
    - test_shortcode_youtube, test_shortcode_gist, test_custom_shortcode

30. Create `tests/test_config.py` (2 tests):
    - test_config_load, test_config_dot_notation

31. Create `tests/test_builder.py` (3 tests):
    - test_build_site, test_build_with_drafts, test_build_result

Run `python -m pytest tests/ -v` to verify ALL 47 tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No markdown, no yaml, no jinja2, no beautifulsoup.
- Template syntax is Django/Jinja2-like but custom implementation.
- Config format is simple YAML-like (no complex nested structures needed).
- All file paths use pathlib.Path.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=8,
        name="Static Site Generator",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=420,
        expected_test_count=47,
        max_planner_turns=120,
        max_planner_wall_time=1500,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
