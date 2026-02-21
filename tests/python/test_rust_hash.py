
import harness_core


class TestRustHash:
    def test_hash_files_basic(self, tmp_path):
        file_a = tmp_path / "a.txt"
        file_b = tmp_path / "b.txt"
        file_a.write_text("hello")
        file_b.write_text("world")

        result = harness_core.rust_hash_files([str(file_a), str(file_b)])

        assert len(result) == 2
        by_path = {path: digest for path, digest in result}
        assert set(by_path) == {str(file_a), str(file_b)}
        assert len(by_path[str(file_a)]) == 64
        assert len(by_path[str(file_b)]) == 64
        assert all(c in "0123456789abcdef" for c in by_path[str(file_a)])
        assert all(c in "0123456789abcdef" for c in by_path[str(file_b)])

    def test_hash_files_empty_file(self, tmp_path):
        empty_file = tmp_path / "empty.txt"
        empty_file.write_text("")

        result = harness_core.rust_hash_files([str(empty_file)])

        assert len(result) == 1
        assert result[0][0] == str(empty_file)
        assert result[0][1] == "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"

    def test_hash_files_missing_file(self, tmp_path):
        missing = tmp_path / "missing.txt"

        result = harness_core.rust_hash_files([str(missing)])

        assert len(result) == 1
        assert result[0][0] == str(missing)
        assert result[0][1] == ""

    def test_hash_files_parallel(self, tmp_path):
        paths = []
        for i in range(60):
            path = tmp_path / f"file_{i}.txt"
            path.write_text(f"content-{i}")
            paths.append(str(path))

        result = harness_core.rust_hash_files(paths)

        assert len(result) == 60
        by_path = {path: digest for path, digest in result}
        assert set(by_path) == set(paths)
        assert all(len(digest) == 64 for digest in by_path.values())

    def test_hash_bytes_basic(self, tmp_path):
        _ = tmp_path
        digest_a = harness_core.rust_hash_bytes(b"hello")
        digest_b = harness_core.rust_hash_bytes(b"hello")

        assert len(digest_a) == 64
        assert digest_a == digest_b

    def test_hash_bytes_empty(self, tmp_path):
        _ = tmp_path
        digest = harness_core.rust_hash_bytes(b"")

        assert len(digest) == 64
        assert digest == "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"

    def test_hash_bytes_large(self, tmp_path):
        _ = tmp_path
        data = b"x" * (1024 * 1024)

        digest = harness_core.rust_hash_bytes(data)

        assert len(digest) == 64

    def test_hash_deterministic(self, tmp_path):
        file_path = tmp_path / "deterministic.txt"
        file_path.write_text("same-content")

        first = harness_core.rust_hash_files([str(file_path)])[0][1]
        second = harness_core.rust_hash_files([str(file_path)])[0][1]

        assert first == second
