"""Tests for src.core.parser."""

import json
import pytest
from pathlib import Path
from src.core.parser import parse_file


def test_parse_valid_tf(tmp_path):
    tf_file = tmp_path / "main.tf"
    tf_file.write_text(
        'resource "aws_instance" "web" {\n  ami = "ami-123"\n}\n',
        encoding="utf-8",
    )
    result = parse_file(tf_file)
    assert result is not None
    assert isinstance(result, dict)
    assert "resource" in result


def test_parse_invalid_tf(tmp_path):
    tf_file = tmp_path / "bad.tf"
    tf_file.write_text("this is { not valid {{ hcl", encoding="utf-8")
    result = parse_file(tf_file)
    assert result is None


def test_parse_nonexistent(tmp_path):
    fake_path = tmp_path / "nonexistent.tf"
    result = parse_file(fake_path)
    assert result is None


def test_parse_yaml(tmp_path):
    yaml_file = tmp_path / "playbook.yaml"
    yaml_file.write_text("key: value\nlist:\n  - a\n  - b\n", encoding="utf-8")
    result = parse_file(yaml_file)
    assert result is not None
    assert result["key"] == "value"


def test_parse_json(tmp_path):
    json_file = tmp_path / "config.json"
    json_file.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    result = parse_file(json_file)
    assert result is not None
    assert result["key"] == "value"
