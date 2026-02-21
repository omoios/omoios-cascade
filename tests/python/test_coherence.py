import pytest

from harness.models.state import StateSnapshot, TaskBoardSnapshot
from harness.orchestration.compression import (
    CompressionTracker,
    auto_compact,
    estimate_tokens,
    microcompact,
)
from harness.orchestration.scratchpad import Scratchpad


class TestScratchpad:
    def test_read_rewrite_roundtrip(self):
        scratchpad = Scratchpad()
        content = "## Goal\nShip\n## Active Workers\n[]"
        scratchpad.rewrite("root", content)
        assert scratchpad.read("root") == content

    def test_read_missing_returns_none(self):
        scratchpad = Scratchpad()
        assert scratchpad.read("missing") is None

    def test_validate_rejects_missing_sections(self):
        scratchpad = Scratchpad()
        is_valid, missing = scratchpad.validate("## Goal\nShip it")
        assert is_valid is False
        assert "## Active Workers" in missing
        assert "## Next Action" in missing

    def test_validate_accepts_valid_content(self):
        scratchpad = Scratchpad()
        content = "\n".join(
            [
                "## Goal",
                "Ship",
                "## Active Workers",
                "[]",
                "## Pending Handoffs",
                "[]",
                "## Error Budget",
                "healthy",
                "## Blockers",
                "[]",
                "## Next Action",
                "Run tests",
            ]
        )
        is_valid, missing = scratchpad.validate(content)
        assert is_valid is True
        assert missing == []

    def test_autosummarize_returns_placeholder(self):
        scratchpad = Scratchpad()
        summary = scratchpad.autosummarize(
            "root",
            [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
            client=object(),
        )
        assert "auto-summary" in summary
        assert "2" in summary


class TestCompression:
    def test_estimate_tokens_returns_positive(self):
        messages = [{"role": "user", "content": "hello world"}]
        value = estimate_tokens(messages)
        assert isinstance(value, int)
        assert value > 0
        assert value == pytest.approx(value)

    def test_microcompact_clears_old_tool_results(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "tool_result", "content": "old result"},
                ],
            },
            {"role": "assistant", "content": "ack"},
            {"role": "user", "content": [{"type": "text", "text": "second"}]},
            {"role": "assistant", "content": "ack"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "third"},
                    {"type": "tool_result", "content": "recent result"},
                ],
            },
            {"role": "assistant", "content": "ack"},
        ]

        compacted = microcompact(messages, keep_recent=1)

        assert compacted[0]["content"][1]["content"] == "[compacted]"
        assert compacted[4]["content"][1]["content"] == "recent result"
        assert messages[0]["content"][1]["content"] == "old result"

    def test_auto_compact_injects_state(self):
        snapshot = StateSnapshot(
            turn_number=3,
            total_tokens=1200,
            task_board=TaskBoardSnapshot(pending=1),
        )
        messages = [{"role": "user", "content": "hello"}]

        compacted = auto_compact(messages, client=object(), snapshot=snapshot)

        assert len(compacted) == 2
        assert compacted[0]["role"] == "user"
        assert snapshot.model_dump_json() in compacted[0]["content"]

    def test_compression_tracker_increments(self):
        tracker = CompressionTracker()
        tracker.record_compression()
        tracker.record_compression()
        assert tracker.count == 2
