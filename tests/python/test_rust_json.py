import json

import pytest

import harness_core


class TestRustJson:
    def test_parse_json_object(self, tmp_path):
        _ = tmp_path
        result = harness_core.rust_parse_json('{"key": "value"}')

        assert isinstance(result, dict)
        assert result == {"key": "value"}

    def test_parse_json_nested(self, tmp_path):
        _ = tmp_path
        payload = '{"outer": {"inner": [1, {"x": true}, null]}}'

        result = harness_core.rust_parse_json(payload)

        assert result["outer"]["inner"][0] == 1
        assert result["outer"]["inner"][1]["x"] is True
        assert result["outer"]["inner"][2] is None

    def test_parse_json_types(self, tmp_path):
        _ = tmp_path
        payload = '{"n": null, "b": false, "i": 42, "f": 3.14, "s": "txt", "a": [1, 2]}'

        result = harness_core.rust_parse_json(payload)

        assert result["n"] is None
        assert isinstance(result["b"], bool)
        assert isinstance(result["i"], int)
        assert isinstance(result["f"], float)
        assert isinstance(result["s"], str)
        assert isinstance(result["a"], list)

    def test_parse_json_invalid(self, tmp_path):
        _ = tmp_path
        with pytest.raises(ValueError):
            harness_core.rust_parse_json('{"key": }')

    def test_serialize_json_basic(self, tmp_path):
        _ = tmp_path
        data = {"key": "value", "count": 2}

        json_str = harness_core.rust_serialize_json(data)

        parsed = json.loads(json_str)
        assert parsed == data

    def test_serialize_json_roundtrip(self, tmp_path):
        _ = tmp_path
        original = '{"name":"rust","nums":[1,2,3],"ok":true}'

        parsed = harness_core.rust_parse_json(original)
        serialized = harness_core.rust_serialize_json(parsed)

        assert json.loads(serialized) == json.loads(original)

    def test_serialize_json_pretty(self, tmp_path):
        _ = tmp_path
        data = {"key": "value", "nested": {"a": 1}}

        json_str = harness_core.rust_serialize_json_pretty(data)

        assert "\n" in json_str
        assert json.loads(json_str) == data

    def test_serialize_json_unicode(self, tmp_path):
        _ = tmp_path
        data = {"greeting": "olá", "city": "Asunción"}

        json_str = harness_core.rust_serialize_json(data)

        assert json.loads(json_str) == data
