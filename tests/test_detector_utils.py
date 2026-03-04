"""Tests for src.detectors.detector_utils."""

from src.detectors.detector_utils import get_ast_signature, compute_distance_task
from src.core.ast_converter import to_zss_tree


def test_signature_single_resource():
    data = {"resource": [{"aws_s3_bucket": {"b": {}}}]}
    assert get_ast_signature(data) == "res:aws_s3_bucket"


def test_signature_multiple_resources():
    data = {
        "resource": [
            {"aws_instance": {"web": {}}},
            {"aws_s3_bucket": {"data": {}}},
        ]
    }
    sig = get_ast_signature(data)
    assert sig == "res:aws_instance|res:aws_s3_bucket"


def test_signature_empty_dict():
    assert get_ast_signature({}) == "empty"


def test_signature_non_dict():
    assert get_ast_signature("not a dict") == "generic"
    assert get_ast_signature(42) == "generic"


def test_compute_distance_identical():
    data = {"ami": "ami-123"}
    t1 = to_zss_tree(data)
    t2 = to_zss_tree(data)
    from pathlib import Path

    result = compute_distance_task((Path("a.tf"), t1, Path("b.tf"), t2, 5))
    assert result is not None
    p1, p2, dist = result
    assert dist == 0


def test_compute_distance_above_threshold():
    d1 = {"a": "1", "b": "2", "c": "3", "d": "4", "e": "5", "f": "6"}
    d2 = {"a": "x", "b": "y", "c": "z", "d": "w", "e": "v", "f": "u"}
    t1 = to_zss_tree(d1)
    t2 = to_zss_tree(d2)
    from pathlib import Path

    result = compute_distance_task((Path("a.tf"), t1, Path("b.tf"), t2, 1))
    assert result is None
