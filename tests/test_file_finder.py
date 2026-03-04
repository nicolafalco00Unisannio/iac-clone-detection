"""Tests for src.core.file_finder."""

from src.core.file_finder import find_iac_files


def test_find_with_valid_files(tmp_tf_dir):
    files = find_iac_files(str(tmp_tf_dir))
    names = [f.name for f in files]
    assert "main.tf" in names
    assert "network.tf" in names


def test_ignores_variables_tf(tmp_tf_dir):
    files = find_iac_files(str(tmp_tf_dir))
    names = [f.name for f in files]
    assert "variables.tf" not in names


def test_ignores_terraform_dir(tmp_tf_dir):
    files = find_iac_files(str(tmp_tf_dir))
    for f in files:
        assert ".terraform" not in f.parts


def test_ignores_no_resource(tmp_tf_dir):
    files = find_iac_files(str(tmp_tf_dir))
    names = [f.name for f in files]
    assert "locals.tf" not in names


def test_limit_parameter(tmp_tf_dir):
    files = find_iac_files(str(tmp_tf_dir), limit=1)
    assert len(files) == 1
