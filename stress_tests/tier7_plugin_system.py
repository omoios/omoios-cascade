#!/usr/bin/env python3
"""Tier 7: Plugin System Library (Extensible Architecture).

Complexity: 10-15 workers, ~40 files, ~1200 LOC.
Task: Build a full plugin system library with discovery, loading, hooks, events,
config, dependency resolution, sandboxing, lifecycle management, and CLI.

This tier tests the harness's ability to build a complex library with many
interconnected components and comprehensive test coverage.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.scaffold import create_repo
from stress_tests.runner_helpers import run_tier, print_summary

REPO_PATH = "/tmp/harness-tier-7"
WORKER_TIMEOUT = 360

SCAFFOLD_FILES = {
    "plugsys/__init__.py": '''\
"""Plugin System Library — Extensible plugin architecture for Python."""

from plugsys.base import Plugin
from plugsys.registry import PluginRegistry

__version__ = "0.1.0"
__all__ = ["Plugin", "PluginRegistry"]
''',
    "plugsys/base.py": '''\
"""Base plugin class and interfaces."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginMetadata:
    """Metadata for a plugin."""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)


class Plugin(ABC):
    """Abstract base class for all plugins."""
    
    def __init__(self):
        self.metadata = PluginMetadata(name=self.__class__.__name__)
        self._enabled = False
        self._config: dict[str, Any] = {}
    
    @property
    def name(self) -> str:
        return self.metadata.name
    
    @property
    def version(self) -> str:
        return self.metadata.version
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    @abstractmethod
    def activate(self) -> None:
        """Called when the plugin is activated."""
        pass
    
    @abstractmethod
    def deactivate(self) -> None:
        """Called when the plugin is deactivated."""
        pass
    
    def configure(self, config: dict[str, Any]) -> None:
        """Configure the plugin with settings."""
        self._config.update(config)
''',
    "tests/__init__.py": "",
    "tests/conftest.py": '''\
import pytest
from plugsys.registry import PluginRegistry


@pytest.fixture
def registry():
    """Provide a fresh plugin registry."""
    return PluginRegistry()
''',
    "tests/test_base.py": """\
from plugsys.base import Plugin, PluginMetadata


class TestPlugin(Plugin):
    def activate(self):
        pass
    
    def deactivate(self):
        pass


def test_plugin_metadata():
    p = TestPlugin()
    assert p.name == "TestPlugin"
    assert p.version == "0.1.0"
    assert not p.enabled
""",
}

INSTRUCTIONS = """\
Build a full plugin system library called "plugsys". Use ONLY Python stdlib.
No external dependencies. Create a professional-grade plugin architecture.

MODULE 1 — Types (`plugsys/types.py`):

1. Create Protocol classes and TypedDict definitions:
   - `PluginProtocol` (Protocol) — defines activate(), deactivate(), name, version
   - `ConfigDict` (TypedDict) — settings: dict[str, Any]
   - `HookCallable` (Protocol) — callable that takes **kwargs and returns Any
   - `EventHandler` (Protocol) — callable that takes Event and returns None
   - `PluginInfo` (TypedDict) — name, version, enabled, metadata dict

MODULE 2 — Version Utilities (`plugsys/versioning.py`):

2. Create semver parsing and comparison:
   - `parse_version(version: str) -> tuple[int, int, int, str, int]` — parse "1.2.3-alpha.1"
     into (major, minor, patch, prerelease, prerelease_num). Handle "1.0", "1.0.0", "v1.0.0"
   - `compare_versions(v1: str, v2: str) -> int` — returns -1, 0, 1 for <, =, >
   - `satisfies_constraint(version: str, constraint: str) -> bool` — check if version
     satisfies constraint like ">=1.0", "^1.2.3", "~1.2.0"
   - `VersionConstraintError` exception for invalid constraint syntax

MODULE 3 — Exceptions (`plugsys/exceptions.py`):

3. Create exception hierarchy:
   - `PlugsysError(Exception)` — base exception
   - `PluginNotFoundError(PlugsysError)` — plugin not found in registry
   - `PluginLoadError(PlugsysError)` — failed to load plugin from file/package
   - `DependencyConflictError(PlugsysError)` — circular or missing dependency
   - `HookError(PlugsysError)` — hook registration or execution error
   - `EventError(PlugsysError)` — event handling error
   - `ConfigError(PlugsysError)` — configuration error
   - `SandboxError(PlugsysError)` — sandbox violation

MODULE 4 — Utilities (`plugsys/utils.py`):

4. Create helper functions:
   - `normalize_name(name: str) -> str` — convert to lowercase, replace spaces with hyphens
   - `safe_import(module_name: str, package: str | None = None) -> ModuleType` — safe import
     that catches ImportError and raises PluginLoadError with context
   - `validate_plugin_class(cls) -> None` — verify class is a valid Plugin subclass,
     raises PluginLoadError if not
   - `extract_entry_points(content: str) -> list[tuple[str, str]]` — parse entry points
     from a setup.py-like string, return list of (name, module_path) tuples

MODULE 5 — Registry (`plugsys/registry.py`):

5. Create `PluginRegistry` class:
   - `__init__(self)` — empty dict of plugins, empty set of enabled plugins
   - `register(plugin_class: type[Plugin]) -> None` — register a plugin class,
     instantiate it, store by name. Raise ConflictError if name already registered.
   - `unregister(name: str) -> bool` — remove plugin, return True if existed
   - `get(name: str) -> Plugin | None` — get plugin instance by name
   - `list_all() -> list[PluginInfo]` — list all registered plugins with info
   - `enable(name: str) -> bool` — enable plugin, call activate(), return success
   - `disable(name: str) -> bool` — disable plugin, call deactivate(), return success
   - `is_enabled(name: str) -> bool`
   - `get_enabled() -> list[str]` — list names of enabled plugins

MODULE 6 — Plugin Loader (`plugsys/loader.py`):

6. Create `PluginLoader` class:
   - `__init__(self, registry: PluginRegistry)`
   - `load_from_file(path: str) -> Plugin` — load single .py file, find Plugin subclass,
     instantiate and return it
   - `load_from_directory(dir_path: str) -> list[Plugin]` — load all .py files in dir
   - `load_from_package(package_name: str) -> list[Plugin]` — import package, find
     plugins in __all__ or by scanning module
   - `load_from_zip(zip_path: str) -> list[Plugin]` — extract to temp, load from there
   - All methods validate plugin class and register to registry

MODULE 7 — Hook System (`plugsys/hooks.py`):

7. Create `HookManager` class:
   - `__init__(self)` — empty dict mapping hook_name -> list of (priority, handler)
   - `register(hook_name: str, handler: HookCallable, priority: int = 10) -> None` —
     higher priority runs first (lower number = higher priority)
   - `unregister(hook_name: str, handler: HookCallable) -> bool`
   - `fire(hook_name: str, **kwargs) -> list[Any]` — call all handlers in priority order,
     return list of results
   - `fire_filter(hook_name: str, value: Any, **kwargs) -> Any` — pass value through
     handlers in sequence, each can modify. Return final value.
   - `get_registered(hook_name: str) -> list[tuple[int, HookCallable]]` — get sorted list

MODULE 8 — Event Bus (`plugsys/events.py`):

8. Create Event dataclass and EventBus:
   - `Event` dataclass: name (str), data (dict), source (str), timestamp (float)
   - `EventBus` class:
     - `__init__(self)` — empty dict mapping event_pattern -> list of handlers
     - `subscribe(event_pattern: str, handler: EventHandler) -> None` — pattern can be
       exact name or wildcard like "plugin.*.activated"
     - `unsubscribe(event_pattern: str, handler: EventHandler) -> bool`
     - `emit(event: Event) -> None` — synchronous emit, call all matching handlers
     - `emit_async(event: Event) -> asyncio.Task` — return task for async handlers
     - `_match(pattern: str, event_name: str) -> bool` — match pattern with * wildcards

MODULE 9 — Configuration (`plugsys/config.py`):

9. Create `PluginConfig` class:
   - `__init__(self, plugin_name: str, defaults: dict[str, Any])`
   - `get(key: str, default: Any = None) -> Any` — get value with dot notation "section.key"
   - `set(key: str, value: Any) -> None`
   - `load_from_file(path: str) -> None` — load TOML-like format (simple key = value lines)
   - `save_to_file(path: str) -> None` — save config to file
   - `validate(schema: dict[str, type]) -> list[str]` — validate types against schema,
     return list of validation errors
   - `to_dict() -> dict[str, Any]` — export as dict

MODULE 10 — Dependencies (`plugsys/dependencies.py`):

10. Create `DependencyResolver` class:
    - `__init__(self, registry: PluginRegistry)`
    - `resolve(plugins: list[str]) -> list[str]` — topological sort of plugin names based
      on their metadata.dependencies. Returns list in load order.
    - `detect_cycles() -> list[list[str]]` — detect circular dependencies, return list of
      cycles found (each cycle is list of plugin names)
    - `check_conflicts(plugin_name: str) -> list[str]` — check if plugin's dependencies
      can be satisfied, return list of missing/conflicting dependencies
    - `get_dependency_tree(plugin_name: str) -> dict` — return nested dict showing
      dependency tree

MODULE 11 — Sandbox (`plugsys/sandbox.py`):

11. Create `PluginSandbox` class:
    - `__init__(self, allowed_modules: list[str] | None = None)` — list of allowed stdlib
      modules (default: os, sys, json, re, datetime, collections, itertools, functools)
    - `execute(plugin_code: str, context: dict | None = None) -> dict` — exec code in
      restricted namespace with only allowed modules, return resulting namespace
    - `create_restricted_import(allowed: list[str]) -> Callable` — return import function
      that only allows specified modules
    - `check_resource_usage() -> dict` — stub that returns {"memory_mb": 0, "cpu_ms": 0}
    - `SandboxViolationError` exception for attempted access to forbidden modules

MODULE 12 — Lifecycle (`plugsys/lifecycle.py`):

12. Create `LifecycleManager` class:
    - States: UNINSTALLED, INSTALLED, CONFIGURED, ACTIVATED, DEACTIVATED, ERROR
    - `__init__(self, registry: PluginRegistry)`
    - `get_state(plugin_name: str) -> str` — get current state
    - `install(plugin_name: str) -> bool` — transition to INSTALLED
    - `configure(plugin_name: str, config: dict) -> bool` — transition to CONFIGURED
    - `activate(plugin_name: str) -> bool` — resolve deps, activate in order
    - `deactivate(plugin_name: str) -> bool` — deactivate this plugin and dependents
    - `uninstall(plugin_name: str) -> bool` — deactivate, then remove
    - `get_available_transitions(plugin_name: str) -> list[str]` — list valid next states

MODULE 13 — Discovery (`plugsys/discovery.py`):

13. Create `PluginDiscovery` class:
    - `__init__(self, registry: PluginRegistry)`
    - `discover_by_entry_points(group: str = "plugsys.plugins") -> list[str]` — scan
      sys.path for packages with entry points, return list of discovered plugin names
    - `discover_by_naming(path: str, pattern: str = "*_plugin.py") -> list[str]` — find
      files matching pattern, return list of module names
    - `discover_in_namespace(namespace: str) -> list[str]` — find modules in namespace
      package
    - `auto_discover(paths: list[str] | None = None) -> list[str]` — combine all methods

MODULE 14 — CLI (`plugsys/cli.py`):

14. Create CLI module with argument parsing:
    - `main()` entry point using argparse
    - Subcommands:
      - `list` — list all plugins with status
      - `enable <name>` — enable a plugin
      - `disable <name>` — disable a plugin
      - `install <path>` — install plugin from file/directory
      - `config <name>` — show/edit config for plugin
    - Each subcommand returns appropriate exit code (0 success, 1 error)

MODULE 15 — Example Plugins (`plugins/`):

15. Create `plugins/__init__.py` — empty

16. Create `plugins/hello_plugin.py`:
    - HelloPlugin class extending Plugin
    - activate() prints "Hello Plugin activated!"
    - deactivate() prints "Hello Plugin deactivated!"

17. Create `plugins/logger_plugin.py`:
    - LoggerPlugin with config for log_level
    - Logs events to stdout when hooks fire

18. Create `plugins/auth_plugin.py`:
    - AuthPlugin with user authentication hooks
    - Provides authenticate(username, password) hook handler

19. Create `plugins/metrics_plugin.py`:
    - MetricsPlugin that tracks hook call counts
    - Provides get_metrics() method returning counts

MODULE 16 — Tests (`tests/`):

20. Create `tests/test_versioning.py` (6 tests):
    - test_parse_full_semver, test_parse_short_version,
    - test_compare_versions_equal, test_compare_versions_greater,
    - test_satisfies_caret_constraint, test_satisfies_tilde_constraint

21. Create `tests/test_registry.py` (5 tests):
    - test_register_plugin, test_unregister_plugin,
    - test_enable_disable_plugin, test_get_enabled_plugins,
    - test_register_duplicate_raises_error

22. Create `tests/test_hooks.py` (5 tests):
    - test_register_and_fire_hook, test_hook_priority_ordering,
    - test_fire_filter_chain, test_unregister_hook,
    - test_fire_no_handlers_returns_empty

23. Create `tests/test_events.py` (5 tests):
    - test_subscribe_and_emit, test_wildcard_matching,
    - test_unsubscribe_handler, test_emit_async,
    - test_multiple_handlers_same_event

24. Create `tests/test_dependencies.py` (5 tests):
    - test_resolve_linear_deps, test_resolve_complex_deps,
    - test_detect_cycle, test_detect_no_cycle,
    - test_check_missing_dependency

25. Create `tests/test_loader.py` (4 tests):
    - test_load_from_file, test_load_from_directory,
    - test_load_invalid_plugin_raises_error,
    - test_load_from_package

26. Create `tests/test_config.py` (4 tests):
    - test_get_set_config, test_load_from_file,
    - test_validate_config, test_to_dict

27. Create `tests/test_lifecycle.py` (4 tests):
    - test_lifecycle_transitions, test_get_state_initial,
    - test_activate_resolves_deps, test_deactivate_cascade

28. Create `tests/test_sandbox.py` (3 tests):
    - test_execute_allowed_module, test_execute_forbidden_module_raises,
    - test_restricted_import

29. Create `tests/test_discovery.py` (3 tests):
    - test_discover_by_naming, test_discover_in_directory,
    - test_auto_discover_finds_plugins

30. Create `tests/test_integration.py` (3 tests):
    - test_full_plugin_lifecycle, test_hook_integration_with_plugins,
    - test_event_integration_with_plugins

Run `python -m pytest tests/ -v` to verify ALL 47 tests pass.

CONSTRAINTS:
- ONLY Python stdlib. No click, no toml, no packaging, no importlib_metadata.
- All file operations use pathlib or os.
- Event async handling uses asyncio.create_task (Python 3.7+).
- Config format is simple: "key = value" lines, sections with "[section]" headers.
"""

TEST_COMMAND = f"cd {REPO_PATH} && python -m pytest tests/ -v"


async def main():
    create_repo(REPO_PATH, SCAFFOLD_FILES)
    result = await run_tier(
        tier=7,
        name="Plugin System Library",
        repo_path=REPO_PATH,
        instructions=INSTRUCTIONS,
        test_command=TEST_COMMAND,
        worker_timeout=360,
        expected_test_count=47,
        max_planner_turns=100,
        max_planner_wall_time=1200,
    )
    return print_summary([result])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
