"""Tests for src.utils.hcl_utils."""

from src.utils.hcl_utils import _sanitize_var_name, _hcl_value


def test_sanitize_simple():
    assert _sanitize_var_name("resource.aws_instance.web.ami") == "ami"


def test_sanitize_generic_name():
    result = _sanitize_var_name("resource.aws_instance.web.name")
    assert result == "web_name"


def test_sanitize_generic_tags():
    result = _sanitize_var_name("resource.aws_instance.web.tags")
    assert result == "web_tags"


def test_hcl_value_bool():
    assert _hcl_value(True) == "true"
    assert _hcl_value(False) == "false"


def test_hcl_value_int():
    assert _hcl_value(42) == "42"


def test_hcl_value_string():
    assert _hcl_value("hello") == '"hello"'


def test_hcl_value_list():
    assert _hcl_value([1, 2, 3]) == "[1, 2, 3]"


def test_hcl_value_empty_list():
    assert _hcl_value([]) == "[]"


def test_hcl_value_nested_list():
    result = _hcl_value([[1, 2], [3, 4]])
    assert result == "[[1, 2], [3, 4]]"
