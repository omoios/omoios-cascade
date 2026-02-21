from collections.abc import Callable


class ToolRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}
        self._role_restrictions: dict[str, set[str]] = {}

    def register(
        self,
        name: str,
        handler: Callable,
        schema: dict,
        allowed_roles: list[str] | None = None,
    ) -> None:
        self._handlers[name] = handler
        self._schemas[name] = schema
        if allowed_roles is None:
            self._role_restrictions.pop(name, None)
            return
        self._role_restrictions[name] = set(allowed_roles)

    def get_tools_for_role(self, role: str) -> list[dict]:
        tools: list[dict] = []
        for name, schema in self._schemas.items():
            allowed = self._role_restrictions.get(name)
            if allowed is not None and role not in allowed:
                continue
            tools.append(schema)
        return tools

    def get_handler(self, name: str) -> Callable | None:
        return self._handlers.get(name)

    def get_tool_names_for_role(self, role: str) -> list[str]:
        return [tool["name"] for tool in self.get_tools_for_role(role)]
