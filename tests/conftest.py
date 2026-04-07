"""Shared fixtures for the test suite."""

import pytest
from pathlib import Path
import tempfile
import os


@pytest.fixture
def sample_s3_ast():
    """HCL2 dict representing an aws_s3_bucket resource."""
    return {
        "resource": [
            {
                "aws_s3_bucket": {
                    "my_bucket": {
                        "bucket": "my-test-bucket",
                        "acl": "private",
                        "tags": {"Name": "TestBucket", "Environment": "dev"},
                    }
                }
            }
        ]
    }


@pytest.fixture
def sample_instance_ast():
    """HCL2 dict representing an aws_instance resource."""
    return {
        "resource": [
            {
                "aws_instance": {
                    "web_server": {
                        "ami": "ami-12345",
                        "instance_type": "t2.micro",
                        "tags": {"Name": "WebServer"},
                    }
                }
            }
        ]
    }


@pytest.fixture
def sample_instance_ast_modified():
    """Same structure as sample_instance_ast but with different values (Type 2 clone)."""
    return {
        "resource": [
            {
                "aws_instance": {
                    "web_server": {
                        "ami": "ami-67890",
                        "instance_type": "t2.large",
                        "tags": {"Name": "WebServer-Prod"},
                    }
                }
            }
        ]
    }


@pytest.fixture
def sample_instance_ast_structural_diff():
    """Structurally different from sample_instance_ast (Type 3 clone)."""
    return {
        "resource": [
            {
                "aws_instance": {
                    "web_server": {
                        "ami": "ami-67890",
                        "instance_type": "t2.large",
                        "tags": {"Name": "WebServer-Prod"},
                        "monitoring": True,
                    }
                }
            }
        ]
    }


@pytest.fixture
def tmp_tf_dir(tmp_path):
    """Temporary directory with valid and invalid .tf files for file_finder tests."""
    valid = tmp_path / "main.tf"
    valid.write_text(
        'resource "aws_instance" "web" {\n  ami = "ami-123"\n  instance_type = "t2.micro"\n}\n',
        encoding="utf-8",
    )

    valid_module = tmp_path / "network.tf"
    valid_module.write_text(
        'module "vpc" {\n  source = "./modules/vpc"\n}\n',
        encoding="utf-8",
    )

    variables = tmp_path / "variables.tf"
    variables.write_text(
        'variable "region" {\n  default = "us-east-1"\n}\n',
        encoding="utf-8",
    )

    locals_file = tmp_path / "locals.tf"
    locals_file.write_text(
        'locals {\n  env = "dev"\n}\n',
        encoding="utf-8",
    )

    terraform_dir = tmp_path / ".terraform" / "modules"
    terraform_dir.mkdir(parents=True)
    vendor = terraform_dir / "main.tf"
    vendor.write_text(
        'resource "aws_instance" "vendor" {\n  ami = "ami-vendor"\n}\n',
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def simple_diff_map():
    """Diff map with a single parametric difference (ami)."""
    return {
        "resource[0].aws_instance.web_server.ami": {
            "val1": "ami-12345",
            "val2": "ami-67890",
            "type": "string",
        }
    }


@pytest.fixture
def multi_diff_map():
    """Diff map with two differences — tests variable collision handling."""
    return {
        "resource[0].aws_instance.web_server.ami": {
            "val1": "ami-12345",
            "val2": "ami-67890",
            "type": "string",
        },
        "resource[0].aws_instance.web_server.instance_type": {
            "val1": "t2.micro",
            "val2": "t2.large",
            "type": "string",
        },
    }
