class Scratchpad:
    REQUIRED_SECTIONS = [
        "## Goal",
        "## Active Workers",
        "## Pending Handoffs",
        "## Error Budget",
        "## Blockers",
        "## Next Action",
    ]

    def __init__(self):
        self._pads: dict[str, str] = {}

    def read(self, name: str) -> str | None:
        return self._pads.get(name)

    def rewrite(self, name: str, content: str) -> None:
        self._pads[name] = content

    def validate(self, content: str) -> tuple[bool, list[str]]:
        missing_sections = [section for section in self.REQUIRED_SECTIONS if section not in content]
        if missing_sections:
            return False, missing_sections
        return True, []

    def autosummarize(self, name: str, messages: list[dict], client: object) -> str:
        _ = name
        _ = client
        return f"[auto-summary of {len(messages)} messages]"
