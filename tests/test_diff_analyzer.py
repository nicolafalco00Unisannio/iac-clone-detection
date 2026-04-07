"""Tests for src.analysis.diff_analyzer."""

from src.analysis.diff_analyzer import (
    classify_clone_type,
    _identify_param_differences,
    _infer_type,
    _find_ast_diff,
)


def test_classify_type1():
    assert classify_clone_type(0) == "Type 1 (Exact Clone)"


def test_classify_type2(sample_instance_ast, sample_instance_ast_modified):
    param_diffs = _identify_param_differences(
        sample_instance_ast, sample_instance_ast_modified
    )
    distance = len(param_diffs)
    result = classify_clone_type(
        distance, sample_instance_ast, sample_instance_ast_modified
    )
    assert result == "Type 2 (Parameterized Clone)"


def test_classify_type3(sample_instance_ast, sample_instance_ast_structural_diff):
    result = classify_clone_type(
        10, sample_instance_ast, sample_instance_ast_structural_diff
    )
    assert result == "Type 3 (Near-miss Clone)"


def test_classify_no_asts():
    result = classify_clone_type(3, None, None)
    assert result == "Type 3 (Near-miss Clone)"


def test_identify_params_identical():
    ast = {"key": "value"}
    diffs = _identify_param_differences(ast, ast)
    assert diffs == {}


def test_identify_params_value_diff():
    a1 = {"ami": "ami-111", "type": "t2.micro"}
    a2 = {"ami": "ami-222", "type": "t2.micro"}
    diffs = _identify_param_differences(a1, a2)
    assert "ami" in diffs
    assert diffs["ami"]["val1"] == "ami-111"
    assert diffs["ami"]["val2"] == "ami-222"


def test_identify_params_type_mismatch():
    a1 = {"key": "string_value"}
    a2 = {"key": [1, 2, 3]}
    diffs = _identify_param_differences(a1, a2)
    assert diffs == {}


def test_infer_type_bool():
    assert _infer_type(True) == "bool"


def test_infer_type_string():
    assert _infer_type("hello") == "string"


def test_infer_type_number():
    assert _infer_type(42) == "number"


def test_infer_type_list():
    assert _infer_type([1, 2]) == "list(any)"


def test_find_ast_diff_identical():
    d = {"a": 1, "b": "hello"}
    diffs = _find_ast_diff(d, d)
    assert diffs == set()


def test_find_ast_diff_different():
    d1 = {"a": 1, "b": "hello"}
    d2 = {"a": 2, "b": "hello"}
    diffs = _find_ast_diff(d1, d2)
    assert len(diffs) == 1
    assert any("a" in d for d in diffs)
