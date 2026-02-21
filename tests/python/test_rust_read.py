
import harness_core


class TestRustRead:
    def test_read_files_basic(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")

        result = harness_core.rust_read_files([str(f1), str(f2)])

        by_path = {path: content for path, content in result}
        assert by_path[str(f1)] == "hello"
        assert by_path[str(f2)] == "world"

    def test_read_files_missing(self, tmp_path):
        missing = tmp_path / "nope.txt"

        result = harness_core.rust_read_files([str(missing)])

        assert len(result) == 1
        assert result[0][0] == str(missing)
        assert result[0][1] is None

    def test_read_files_mixed(self, tmp_path):
        exists = tmp_path / "exists.txt"
        exists.write_text("data")
        missing = tmp_path / "missing.txt"

        result = harness_core.rust_read_files([str(exists), str(missing)])

        by_path = {path: content for path, content in result}
        assert by_path[str(exists)] == "data"
        assert by_path[str(missing)] is None

    def test_read_files_parallel(self, tmp_path):
        paths = []
        for i in range(60):
            p = tmp_path / f"f_{i}.txt"
            p.write_text(f"content-{i}")
            paths.append(str(p))

        result = harness_core.rust_read_files(paths)

        assert len(result) == 60
        by_path = {path: content for path, content in result}
        for i in range(60):
            assert by_path[paths[i]] == f"content-{i}"

    def test_read_files_bytes_basic(self, tmp_path):
        f = tmp_path / "bin.dat"
        f.write_bytes(b"\x00\x01\x02\xff")

        result = harness_core.rust_read_files_bytes([str(f)])

        assert len(result) == 1
        assert result[0][0] == str(f)
        assert result[0][1] == b"\x00\x01\x02\xff"

    def test_read_files_empty(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("")

        result = harness_core.rust_read_files([str(f)])

        assert result[0][1] == ""
