"""Direct tests for the shared tolerant JSON parser.

The helper is reused by both the ReAct agent (``react.parse_react_output``) and the
Evaluator-Optimizer agent (``eval_opt``), so it owns its own coverage here rather than relying on
either caller's tests.
"""

import pytest

from apps.llm_analysis._json import parse_json_object


class TestParseJsonObject:
    def test_plain_object(self):
        assert parse_json_object('{"score": 9, "pass": true}') == {"score": 9, "pass": True}

    def test_strips_json_fence(self):
        assert parse_json_object('```json\n{"answer": "hi"}\n```') == {"answer": "hi"}

    def test_strips_bare_fence(self):
        assert parse_json_object('```\n{"a": 1}\n```') == {"a": 1}

    def test_extracts_object_from_surrounding_prose(self):
        assert parse_json_object('Sure!\n{"a": 1}\nthanks') == {"a": 1}

    def test_whitespace_only_padding(self):
        assert parse_json_object('   {"a": 1}   ') == {"a": 1}

    def test_non_json_raises(self):
        with pytest.raises(ValueError):
            parse_json_object("not json at all")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_json_object("")

    def test_non_object_json_raises(self):
        # Valid JSON, but a list rather than an object.
        with pytest.raises(ValueError):
            parse_json_object("[1, 2, 3]")

    def test_scalar_json_raises(self):
        with pytest.raises(ValueError):
            parse_json_object("42")
