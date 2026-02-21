import json
import subprocess

import pytest

import harness_core

pytestmark = pytest.mark.slow


class TestRustPythonParity:
    def test_grep_rust_vs_python_parity(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("line one hello\nline two world\nline three hello again\n")

        rust_results = harness_core.rust_grep(str(tmp_path), "hello", "*.py", 100)
        python_hits = []
        for line_num, line in enumerate(f.read_text().splitlines(), 1):
            if "hello" in line:
                python_hits.append((str(f), line_num, line))

        assert len(rust_results) == len(python_hits)

    def test_glob_rust_vs_python_parity(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "c.py").write_text("c")

        rust_results = harness_core.rust_glob(str(tmp_path), "*.py", 1000)
        rust_names = {r.split("/")[-1] for r in rust_results}

        assert rust_names == {"a.py", "c.py"}

    def test_snapshot_rust_vs_python_parity(self, tmp_path):
        (tmp_path / "x.txt").write_text("content-x")
        (tmp_path / "y.txt").write_text("content-y")

        result = harness_core.snapshot_workspace(str(tmp_path))

        assert isinstance(result, dict)
        keys = {k.split("/")[-1] for k in result}
        assert "x.txt" in keys
        assert "y.txt" in keys

    def test_hash_consistency(self, tmp_path):
        f = tmp_path / "stable.txt"
        f.write_text("the same content")

        h1 = harness_core.rust_hash_files([str(f)])[0][1]
        h2 = harness_core.rust_hash_files([str(f)])[0][1]
        h3 = harness_core.rust_hash_files([str(f)])[0][1]

        assert h1 == h2 == h3

    def test_json_roundtrip_parity(self, tmp_path):
        data = {"key": "value", "nums": [1, 2, 3], "nested": {"a": True}}

        serialized = harness_core.rust_serialize_json(data)
        parsed_rust = harness_core.rust_parse_json(serialized)
        parsed_python = json.loads(serialized)

        assert parsed_rust == parsed_python

    def test_multi_grep_matches_regex(self, tmp_path):
        text = "the cat sat on the mat with a cat"
        patterns = ["cat", "mat"]

        rust_results = harness_core.rust_multi_grep(text, patterns, None)

        for offset, pidx, matched in rust_results:
            assert text[offset : offset + len(matched)] == matched

    def test_read_files_matches_python(self, tmp_path):
        f1 = tmp_path / "r1.txt"
        f2 = tmp_path / "r2.txt"
        f1.write_text("content one")
        f2.write_text("content two")

        rust_result = dict(harness_core.rust_read_files([str(f1), str(f2)]))

        assert rust_result[str(f1)] == f1.read_text()
        assert rust_result[str(f2)] == f2.read_text()

    def test_shell_matches_subprocess(self, tmp_path):
        cmd = "echo integration-test"

        rust_code, rust_out, rust_err = harness_core.rust_run_command(cmd, None, None)
        py_result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

        assert rust_code == py_result.returncode
        assert rust_out.strip() == py_result.stdout.strip()

    def test_hash_bytes_format(self, tmp_path):
        digest = harness_core.rust_hash_bytes(b"test data")

        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)
