"""Tests for app.steps.resolver."""

import pytest

from app.steps.resolver import resolve


def test_lone_template_preserves_int():
    assert resolve("{{a}}", {"a": 1}) == 1


def test_lone_template_preserves_bool():
    assert resolve("{{a}}", {"a": True}) is True


def test_lone_template_preserves_none():
    assert resolve("{{a}}", {"a": None}) is None


def test_lone_template_preserves_dict():
    assert resolve("{{a}}", {"a": {"x": 1}}) == {"x": 1}


def test_lone_template_preserves_list():
    assert resolve("{{a}}", {"a": [1, 2]}) == [1, 2]


def test_lone_template_strips_around_whitespace():
    assert resolve("  {{a}}  ", {"a": 5}) == 5


def test_interpolation_coerces_to_string():
    assert resolve("item {{a}}", {"a": 1}) == "item 1"


def test_multiple_templates_in_one_string():
    assert resolve("{{a}}-{{b}}", {"a": 1, "b": 2}) == "1-2"


def test_dotted_path():
    assert resolve("{{a.b.c}}", {"a": {"b": {"c": 9}}}) == 9


def test_nested_dict_resolved():
    assert resolve({"a": "{{x}}", "b": "{{y}}"}, {"x": 1, "y": 2}) == {
        "a": 1,
        "b": 2,
    }


def test_nested_list_resolved():
    assert resolve(["{{x}}", "{{y}}"], {"x": 1, "y": 2}) == [1, 2]


def test_deeply_nested():
    out = resolve({"a": ["{{x}}", {"b": "{{y}}"}]}, {"x": 1, "y": 2})
    assert out == {"a": [1, {"b": 2}]}


def test_no_template_returns_string():
    assert resolve("hello", {"a": 1}) == "hello"


def test_non_string_passthrough():
    assert resolve(42, {"a": 1}) == 42


def test_missing_key_raises():
    with pytest.raises(KeyError):
        resolve("{{missing}}", {})


def test_missing_nested_key_raises():
    with pytest.raises(KeyError):
        resolve("{{a.b}}", {"a": {}})


def test_escaped_braces_are_literal():
    assert resolve("\\{{a}}", {"a": 1}) == "{{a}}"


def test_escaped_then_template():
    assert resolve("\\{{a}} {{b}}", {"b": 2}) == "{{a}} 2"