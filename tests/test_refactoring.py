"""Tests for src.analysis.refactoring."""

from src.analysis.refactoring import (
    _extract_single_var_name_from_value,
    _extract_var_references,
    _render_hcl_recursive,
    _generate_smart_module_tf,
    _generate_smart_module_call,
    _generate_tfvars_refactor,
)


# ---------------------------------------------------------------------------
# _extract_single_var_name_from_value
# ---------------------------------------------------------------------------


def test_extract_single_var_bare():
    assert _extract_single_var_name_from_value("var.region") == "region"


def test_extract_single_var_interpolation():
    assert _extract_single_var_name_from_value("${var.region}") == "region"


def test_extract_single_var_two_different_vars():
    """Two distinct variable names → ambiguous → None."""
    assert _extract_single_var_name_from_value("${var.a}-${var.b}") is None


def test_extract_single_var_non_string():
    assert _extract_single_var_name_from_value(42) is None
    assert _extract_single_var_name_from_value(None) is None


def test_extract_single_var_no_match():
    assert _extract_single_var_name_from_value("just a plain string") is None


# ---------------------------------------------------------------------------
# _extract_var_references
# ---------------------------------------------------------------------------


def test_extract_refs_from_string():
    assert _extract_var_references("var.region") == {"region"}


def test_extract_refs_from_dict():
    node = {"ami": "var.ami_id", "region": "us-east-1"}
    assert _extract_var_references(node) == {"ami_id"}


def test_extract_refs_from_nested():
    node = {"outer": {"inner": "prefix-${var.env}-suffix"}, "list": ["var.zone"]}
    assert _extract_var_references(node) == {"env", "zone"}


def test_extract_refs_none():
    assert _extract_var_references({"key": "no refs here"}) == set()
    assert _extract_var_references(42) == set()


# ---------------------------------------------------------------------------
# _render_hcl_recursive
# ---------------------------------------------------------------------------


def test_render_leaf_string():
    result = _render_hcl_recursive("hello", {})
    assert result == '"hello"'


def test_render_leaf_with_variable_injection():
    variable_map = {"ami": "ami_var"}
    result = _render_hcl_recursive("ami-12345", variable_map, current_path="ami")
    assert result == '"${var.ami_var}"'


def test_render_flat_dict():
    node = {"ami": "ami-123", "type": "t2.micro"}
    result = _render_hcl_recursive(node, {})
    assert 'ami = "ami-123"' in result
    assert 'type = "t2.micro"' in result


def test_render_list_of_primitives():
    result = _render_hcl_recursive([1, 2, 3], {})
    assert result == "[1, 2, 3]"


def test_render_resource_block(sample_instance_ast):
    """Top-level resource block renders with Terraform syntax."""
    result = _render_hcl_recursive(sample_instance_ast, {})
    assert 'resource "aws_instance" "web_server"' in result
    assert 'ami = "ami-12345"' in result


# ---------------------------------------------------------------------------
# _generate_smart_module_tf
# ---------------------------------------------------------------------------


def test_smart_module_single_diff(sample_instance_ast, simple_diff_map):
    vars_tf, main_tf, var_map, passthrough = _generate_smart_module_tf(
        sample_instance_ast, simple_diff_map
    )
    # One variable declared
    assert 'variable "ami"' in vars_tf
    assert "type        = string" in vars_tf

    # main.tf injects the variable reference
    assert "${var.ami}" in main_tf

    # variable_map has the path mapped
    assert "resource[0].aws_instance.web_server.ami" in var_map
    assert var_map["resource[0].aws_instance.web_server.ami"] == "ami"

    # No passthrough vars (no var.* in original AST)
    assert passthrough == {}


def test_smart_module_multi_diff(sample_instance_ast, multi_diff_map):
    vars_tf, main_tf, var_map, _ = _generate_smart_module_tf(
        sample_instance_ast, multi_diff_map
    )
    # Two variables declared
    assert 'variable "ami"' in vars_tf
    assert 'variable "instance_type"' in vars_tf
    assert len(var_map) == 2


def test_smart_module_passthrough_var():
    """AST containing var.existing_var → detected as passthrough."""
    ast_with_var = {
        "resource": [
            {
                "aws_instance": {
                    "web": {
                        "ami": "var.my_ami",
                        "instance_type": "t2.micro",
                    }
                }
            }
        ]
    }
    diff_map = {
        "resource[0].aws_instance.web.instance_type": {
            "val1": "t2.micro",
            "val2": "t2.large",
            "type": "string",
        }
    }
    vars_tf, _, _, passthrough = _generate_smart_module_tf(ast_with_var, diff_map)

    # my_ami is detected as passthrough
    assert "my_ami" in passthrough
    assert 'variable "my_ami"' in vars_tf
    assert "Pass-through variable" in vars_tf


def test_smart_module_name_collision():
    """Two diff paths that sanitize to the same var name get suffixed."""
    diff_map = {
        "a.b.ami": {"val1": "v1", "val2": "v2", "type": "string"},
        "c.d.ami": {"val1": "v3", "val2": "v4", "type": "string"},
    }
    _, _, var_map, _ = _generate_smart_module_tf({}, diff_map)
    names = list(var_map.values())
    assert len(set(names)) == 2  # no duplicates
    assert "ami" in names
    assert "ami_1" in names


# ---------------------------------------------------------------------------
# _generate_smart_module_call
# ---------------------------------------------------------------------------


def test_module_call_left_values(simple_diff_map):
    var_map = {"resource[0].aws_instance.web_server.ami": "ami"}
    result = _generate_smart_module_call(
        "web_server", simple_diff_map, var_map, "left"
    )
    assert 'module "web_server"' in result
    assert 'source = "./modules/web_server"' in result
    assert 'ami = "ami-12345"' in result  # val1


def test_module_call_right_values(simple_diff_map):
    var_map = {"resource[0].aws_instance.web_server.ami": "ami"}
    result = _generate_smart_module_call(
        "web_server", simple_diff_map, var_map, "right"
    )
    assert 'ami = "ami-67890"' in result  # val2


def test_module_call_with_passthrough(simple_diff_map):
    var_map = {"resource[0].aws_instance.web_server.ami": "ami"}
    passthrough = {"region": "any"}
    result = _generate_smart_module_call(
        "web_server", simple_diff_map, var_map, "left", passthrough
    )
    assert "${var.region}" in result


# ---------------------------------------------------------------------------
# _generate_tfvars_refactor
# ---------------------------------------------------------------------------


def test_tfvars_basic(sample_instance_ast, sample_instance_ast_modified, simple_diff_map):
    vars_tf, left_main, right_main, left_tfvars, right_tfvars, var_map = (
        _generate_tfvars_refactor(
            sample_instance_ast, sample_instance_ast_modified, simple_diff_map
        )
    )
    # Variable declared
    assert 'variable "ami"' in vars_tf

    # Both main files inject var reference
    assert "${var.ami}" in left_main
    assert "${var.ami}" in right_main

    # tfvars contain concrete values
    assert 'ami = "ami-12345"' in left_tfvars
    assert 'ami = "ami-67890"' in right_tfvars


def test_tfvars_reuses_existing_var_name():
    """If one side already uses var.X, reuse that name and skip new declaration."""
    ast_left = {"ami": "var.my_ami"}
    ast_right = {"ami": "ami-999"}
    diff_map = {
        "ami": {
            "val1": "var.my_ami",
            "val2": "ami-999",
            "type": "string",
        }
    }
    vars_tf, _, _, left_tfvars, right_tfvars, _ = _generate_tfvars_refactor(
        ast_left, ast_right, diff_map
    )
    # No new variable declared (reused existing var.my_ami)
    assert 'variable "my_ami"' not in vars_tf

    # Left tfvars has a comment (already a var ref), right has literal
    assert "# my_ami already comes from" in left_tfvars
    assert 'my_ami = "ami-999"' in right_tfvars
