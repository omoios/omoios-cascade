
import harness_core


class TestRustAho:
    def test_multi_grep_basic(self, tmp_path):
        _ = tmp_path
        text = "alpha beta gamma"
        patterns = ["beta", "gamma"]

        result = harness_core.rust_multi_grep(text, patterns, None)

        assert len(result) == 2
        assert result[0] == (6, 0, "beta")
        assert result[1] == (11, 1, "gamma")

    def test_multi_grep_no_match(self, tmp_path):
        _ = tmp_path
        result = harness_core.rust_multi_grep("no hits here", ["abc", "xyz"], None)

        assert result == []

    def test_multi_grep_max_results(self, tmp_path):
        _ = tmp_path
        text = "cat dog cat dog"

        result = harness_core.rust_multi_grep(text, ["cat", "dog"], 2)

        assert len(result) == 2

    def test_multi_grep_lines_basic(self, tmp_path):
        _ = tmp_path
        text = "line one\nline two has beta\nline three"

        result = harness_core.rust_multi_grep_lines(text, ["beta"], None)

        assert result == [(2, 0, "line two has beta")]

    def test_multi_grep_lines_dedup(self, tmp_path):
        _ = tmp_path
        text = "alpha beta gamma\nsecond line"

        result = harness_core.rust_multi_grep_lines(text, ["alpha", "gamma"], None)

        assert len(result) == 1
        assert result[0][0] == 1
        assert result[0][2] == "alpha beta gamma"

    def test_multi_grep_empty_patterns(self, tmp_path):
        _ = tmp_path
        result = harness_core.rust_multi_grep("anything", [], None)

        assert result == []
