"""Tests for src.analysis.refactoring."""

from src.analysis.refactoring import (
    _extract_single_var_name_from_value,
    _extract_var_references,
    _render_hcl_recursive,
    _split_tfvars_eligible_diffs,
    _generate_smart_module_tf,
    _generate_smart_module_call,
    _generate_module_outputs,
    _rewrite_consumer_hcl,
    _generate_tfvars_bundle,
    _generate_tfvars_refactor,
    _generate_wrapper_module_suggestion,
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
    vars_tf, _, var_map, _ = _generate_smart_module_tf(
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


def test_smart_module_collapses_repeated_equivalent_diffs():
    """Repeated val1/val2/type diffs should map to one semantic variable."""
    diff_map = {
        "resource[0].aws_security_group.default_egress.vpc_id": {
            "val1": "${aws_vpc.main.id}",
            "val2": "${var.vpc_id}",
            "type": "string",
        },
        "resource[2].aws_security_group.admin_access.vpc_id": {
            "val1": "${aws_vpc.main.id}",
            "val2": "${var.vpc_id}",
            "type": "string",
        },
        "resource[4].aws_security_group.consul_client.vpc_id": {
            "val1": "${aws_vpc.main.id}",
            "val2": "${var.vpc_id}",
            "type": "string",
        },
        "resource[9].aws_security_group.consul.vpc_id": {
            "val1": "${aws_vpc.main.id}",
            "val2": "${var.vpc_id}",
            "type": "string",
        },
    }

    vars_tf, _, var_map, _ = _generate_smart_module_tf({}, diff_map)
    assert set(var_map.values()) == {"vpc_id"}
    assert vars_tf.count('variable "vpc_id"') == 1

    call_left = _generate_smart_module_call("firewalls", diff_map, var_map, "left")
    assert call_left.count("vpc_id =") == 1


def test_generate_module_outputs_and_rewire_consumer():
    ast = {
        "resource": [
            {
                "aws_security_group": {
                    "default_egress": {"vpc_id": "var.vpc_id"},
                    "admin_access": {"vpc_id": "var.vpc_id"},
                }
            }
        ]
    }
    consumer = (
        'resource "aws_instance" "web" {\n'
        '  vpc_security_group_ids = ["${aws_security_group.default_egress.id}", "${aws_security_group.admin_access.id}"]\n'
        '}\n'
    )

    outputs_tf, ref_output_map = _generate_module_outputs(ast, [consumer])

    assert 'output "default_egress_id"' in outputs_tf
    assert 'output "admin_access_id"' in outputs_tf
    assert ref_output_map["aws_security_group.default_egress.id"] == "default_egress_id"

    rewritten, replacements = _rewrite_consumer_hcl(consumer, ref_output_map, "consul_firewalls")

    assert "module.consul_firewalls.default_egress_id" in rewritten
    assert "module.consul_firewalls.admin_access_id" in rewritten
    assert replacements["aws_security_group.default_egress.id"] == "module.consul_firewalls.default_egress_id"


# ---------------------------------------------------------------------------
# _generate_tfvars_refactor
# ---------------------------------------------------------------------------


def test_tfvars_basic(sample_instance_ast, sample_instance_ast_modified, simple_diff_map):
    vars_tf, left_main, right_main, left_tfvars, right_tfvars, _ = (
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
    """If one side already uses var.X, reuse that name and declare it in generated variables.tf."""
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
    # Reused var name should still be declared for standalone validity.
    assert 'variable "my_ami"' in vars_tf

    # Left tfvars has a comment (already a var ref), right has literal
    assert "# my_ami already comes from" in left_tfvars
    assert 'my_ami = "ami-999"' in right_tfvars


def test_tfvars_collapses_repeated_equivalent_diffs():
    ast_left = {
        "resource": [
            {
                "aws_security_group": {
                    "default_egress": {"vpc_id": "${aws_vpc.main.id}"},
                    "admin_access": {"vpc_id": "${aws_vpc.main.id}"},
                }
            }
        ]
    }
    ast_right = {
        "resource": [
            {
                "aws_security_group": {
                    "default_egress": {"vpc_id": "${var.vpc_id}"},
                    "admin_access": {"vpc_id": "${var.vpc_id}"},
                }
            }
        ]
    }
    diff_map = {
        "resource[0].aws_security_group.default_egress.vpc_id": {
            "val1": "${aws_vpc.main.id}",
            "val2": "${var.vpc_id}",
            "type": "string",
        },
        "resource[0].aws_security_group.admin_access.vpc_id": {
            "val1": "${aws_vpc.main.id}",
            "val2": "${var.vpc_id}",
            "type": "string",
        },
    }

    vars_tf, left_main, right_main, left_tfvars, right_tfvars, var_map = _generate_tfvars_refactor(
        ast_left, ast_right, diff_map
    )

    assert set(var_map.values()) == {"vpc_id"}
    assert vars_tf.count('variable "vpc_id"') == 1
    assert left_main.count("${var.vpc_id}") == 2
    assert right_main.count("${var.vpc_id}") == 2
    assert left_tfvars.count("vpc_id =") == 1
    assert "already comes from var.vpc_id" in right_tfvars


def test_tfvars_bundle_uses_canonical_shared_template(sample_instance_ast):
    modified_ast = {
        "resource": [
            {
                "aws_instance": {
                    "web_server": {
                        "ami": "ami-67890",
                        "instance_type": "t2.micro",
                        "tags": {"Name": "WebServer"},
                    }
                }
            }
        ]
    }
    diff_map = {
        "resource[0].aws_instance.web_server.ami": {
            "val1": "ami-12345",
            "val2": "ami-67890",
            "type": "string",
        }
    }
    bundle = _generate_tfvars_bundle(
        sample_instance_ast,
        modified_ast,
        diff_map,
    )

    assert bundle["template_equal"] is True
    assert bundle["shared_main_tf"] == bundle["left_main_tf"] == bundle["right_main_tf"]
    assert "${var.ami}" in bundle["shared_main_tf"]


def test_split_tfvars_excludes_module_source_path():
    diff_map = {
        "module[0].dcos-mesos-master.source": {
            "val1": "git@github.com:mesosphere/terraform-dcos-enterprise//tf_dcos_core",
            "val2": "git@github.com:amitaekbote/terraform-dcos-enterprise//tf_dcos_core?ref=addnode",
            "type": "string",
        }
    }

    eligible, excluded = _split_tfvars_eligible_diffs(diff_map)

    assert not eligible
    assert "module[0].dcos-mesos-master.source" in excluded
    assert "literal string" in excluded["module[0].dcos-mesos-master.source"]


def test_tfvars_refactor_skips_non_parameterizable_module_source():
    ast_left = {
        "module": [
            {
                "dcos-mesos-master": {
                    "source": "git@github.com:mesosphere/terraform-dcos-enterprise//tf_dcos_core",
                    "role": "dcos-mesos-master",
                }
            }
        ]
    }
    ast_right = {
        "module": [
            {
                "dcos-mesos-master": {
                    "source": "git@github.com:amitaekbote/terraform-dcos-enterprise//tf_dcos_core?ref=addnode",
                    "role": "dcos-mesos-master",
                }
            }
        ]
    }
    diff_map = {
        "module[0].dcos-mesos-master.source": {
            "val1": ast_left["module"][0]["dcos-mesos-master"]["source"],
            "val2": ast_right["module"][0]["dcos-mesos-master"]["source"],
            "type": "string",
        }
    }

    vars_tf, left_main, right_main, left_tfvars, right_tfvars, var_map = _generate_tfvars_refactor(
        ast_left,
        ast_right,
        diff_map,
    )
    bundle = _generate_tfvars_bundle(ast_left, ast_right, diff_map)

    assert vars_tf == ""
    assert var_map == {}
    assert left_tfvars.strip() == ""
    assert right_tfvars.strip() == ""
    assert "${var." not in left_main
    assert "${var." not in right_main

    assert "module[0].dcos-mesos-master.source" in bundle["excluded_differences"]


def test_generate_wrapper_module_suggestion_forwards_vars_and_fixed_inputs():
    ast_template = {
        "resource": [
            {
                "aws_instance": {
                    "web": {
                        "ami": "${var.ami}",
                        "instance_type": "${var.instance_type}",
                        "tags": {
                            "Env": "${var.environment}",
                        },
                    }
                }
            }
        ]
    }

    suggestion = _generate_wrapper_module_suggestion(
        ast_template,
        canonical_source="../../canonical/web",
        fixed_inputs={"instance_type": "t2.micro"},
        output_names=["elb_dns_name", "asg_name"],
    )

    assert suggestion["strategy"] == "module_wrapper_delegation"
    assert suggestion["canonical_source"] == "../../canonical/web"
    assert suggestion["module_instance_name"] == "impl"

    wrapper_main = suggestion["wrapper_main_tf"]
    assert 'source = "../../canonical/web"' in wrapper_main
    assert 'instance_type = "t2.micro"' in wrapper_main
    assert 'ami = "${var.ami}"' in wrapper_main
    assert 'environment = "${var.environment}"' in wrapper_main
    assert 'instance_type = "${var.instance_type}"' not in wrapper_main

    wrapper_outputs = suggestion["wrapper_outputs_tf"]
    assert 'output "asg_name"' in wrapper_outputs
    assert 'value = "${module.impl.asg_name}"' in wrapper_outputs
    assert 'output "elb_dns_name"' in wrapper_outputs
    assert 'value = "${module.impl.elb_dns_name}"' in wrapper_outputs


def test_generate_wrapper_module_suggestion_outputs_fallback_is_comment_only():
    ast_template = {"resource": []}

    suggestion = _generate_wrapper_module_suggestion(
        ast_template,
        canonical_source="../canonical",
    )

    assert 'output ""' not in suggestion["wrapper_outputs_tf"]
    assert "No output names were discovered automatically" in suggestion["wrapper_outputs_tf"]
