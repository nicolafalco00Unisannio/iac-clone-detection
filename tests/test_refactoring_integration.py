"""
Integration test: end-to-end refactoring suggestion validation.

Given two near-identical Terraform files (a Type-2 clone), the test:
  1. Writes them to a temp directory and parses them via parse_file.
  2. Extracts the diff via _identify_param_differences.
  3. Generates a shared module (variables.tf + main.tf) via _generate_smart_module_tf.
  4. Generates caller blocks via _generate_smart_module_call.
  5. Validates that the generated HCL is parseable with hcl2.
  6. Validates that every var.* reference in main.tf is declared in variables.tf.
  7. Validates the tfvars refactoring (_generate_tfvars_refactor) similarly.
  8. Optionally runs `terraform fmt -check` on the generated files if Terraform is present.
"""

import io
import re
import subprocess
from pathlib import Path

import hcl2
import pytest

from src.analysis.diff_analyzer import _identify_param_differences
from src.analysis.refactoring import (
    _generate_smart_module_call,
    _generate_smart_module_tf,
    _generate_tfvars_refactor,
)
from src.core.parser import parse_file

# ---------------------------------------------------------------------------
# Terraform source fixtures — a minimal Type-2 clone pair
# ---------------------------------------------------------------------------

LEFT_TF = """\
resource "aws_instance" "web" {
  ami           = "ami-11111"
  instance_type = "t2.micro"

  tags = {
    Name        = "WebServer-Dev"
    Environment = "dev"
  }
}
"""

RIGHT_TF = """\
resource "aws_instance" "web" {
  ami           = "ami-99999"
  instance_type = "t2.large"

  tags = {
    Name        = "WebServer-Prod"
    Environment = "prod"
  }
}
"""

# Regex to collect every var.<name> reference in a raw HCL string
_VAR_REF_RE = re.compile(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)\b")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_declared_variables(variables_tf_str: str) -> set[str]:
    """Parse variable declarations from a variables.tf string."""
    names: set[str] = set()
    try:
        ast = hcl2.load(io.StringIO(variables_tf_str))
        for block in ast.get("variable", []):
            names.update(block.keys())
    except Exception:
        pass
    return names


def _collect_var_refs(hcl_source: str) -> set[str]:
    """Collect all var.<name> references appearing in a raw HCL string."""
    return set(_VAR_REF_RE.findall(hcl_source))


def _terraform_available() -> bool:
    try:
        result = subprocess.run(
            ["terraform", "version"], capture_output=True, timeout=10
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Shared fixture: two clone .tf files + their parsed ASTs + diff map
# ---------------------------------------------------------------------------

@pytest.fixture()
def clone_setup(tmp_path):
    """
    Write LEFT_TF / RIGHT_TF to disk, parse them, and compute the diff.

    Returns a dict with keys:
      left_path, right_path, ast_left, ast_right, diff_map
    """
    left_path = tmp_path / "left.tf"
    right_path = tmp_path / "right.tf"
    left_path.write_text(LEFT_TF, encoding="utf-8")
    right_path.write_text(RIGHT_TF, encoding="utf-8")

    ast_left = parse_file(left_path)
    ast_right = parse_file(right_path)

    assert ast_left is not None, "hcl2 failed to parse left.tf"
    assert ast_right is not None, "hcl2 failed to parse right.tf"

    diff_map = _identify_param_differences(ast_left, ast_right)

    return {
        "left_path": left_path,
        "right_path": right_path,
        "ast_left": ast_left,
        "ast_right": ast_right,
        "diff_map": diff_map,
        "tmp_path": tmp_path,
    }


# ---------------------------------------------------------------------------
# Tests: _generate_smart_module_tf + _generate_smart_module_call
# ---------------------------------------------------------------------------

class TestModuleRefactoring:

    def test_diff_map_non_empty(self, clone_setup):
        """Sanity check: the two clone files must yield at least one difference."""
        assert clone_setup["diff_map"], (
            "No differences found between clone files — check LEFT_TF / RIGHT_TF"
        )

    def test_variables_tf_parseable(self, clone_setup):
        """Generated variables.tf must be valid HCL that hcl2 can re-parse."""
        vars_tf, _, _, _ = _generate_smart_module_tf(
            clone_setup["ast_left"], clone_setup["diff_map"]
        )
        ast = hcl2.load(io.StringIO(vars_tf))
        assert "variable" in ast, "variables.tf contains no variable blocks"

    def test_all_var_refs_declared(self, clone_setup):
        """
        Every var.<name> reference in the generated main.tf must be declared
        in the generated variables.tf (no unresolved references).
        """
        vars_tf, main_tf, _, _ = _generate_smart_module_tf(
            clone_setup["ast_left"], clone_setup["diff_map"]
        )
        declared = _collect_declared_variables(vars_tf)
        used = _collect_var_refs(main_tf)

        assert declared, "No variables declared in variables.tf"
        missing = used - declared
        assert not missing, (
            f"var(s) referenced in main.tf but not declared in variables.tf: {missing}\n"
            f"--- variables.tf ---\n{vars_tf}\n"
            f"--- main.tf ---\n{main_tf}"
        )

    def test_module_call_wires_all_diff_vars(self, clone_setup):
        """
        Both left and right module call blocks must assign every variable
        that was introduced for a diff (i.e. every entry in var_map).
        """
        _, _, var_map, passthrough = _generate_smart_module_tf(
            clone_setup["ast_left"], clone_setup["diff_map"]
        )
        call_left = _generate_smart_module_call(
            "web", clone_setup["diff_map"], var_map, "left", passthrough
        )
        call_right = _generate_smart_module_call(
            "web", clone_setup["diff_map"], var_map, "right", passthrough
        )

        for var_name in var_map.values():
            assert var_name in call_left, (
                f"'{var_name}' missing from left module call:\n{call_left}"
            )
            assert var_name in call_right, (
                f"'{var_name}' missing from right module call:\n{call_right}"
            )

    def test_left_and_right_calls_differ(self, clone_setup):
        """Left and right module calls must produce different concrete values."""
        _, _, var_map, passthrough = _generate_smart_module_tf(
            clone_setup["ast_left"], clone_setup["diff_map"]
        )
        call_left = _generate_smart_module_call(
            "web", clone_setup["diff_map"], var_map, "left", passthrough
        )
        call_right = _generate_smart_module_call(
            "web", clone_setup["diff_map"], var_map, "right", passthrough
        )
        assert call_left != call_right, (
            "Left and right module calls are identical — refactoring produces no variation"
        )

    def test_left_call_contains_original_left_values(self, clone_setup):
        """Left call block should reference values from LEFT_TF."""
        _, _, var_map, passthrough = _generate_smart_module_tf(
            clone_setup["ast_left"], clone_setup["diff_map"]
        )
        call_left = _generate_smart_module_call(
            "web", clone_setup["diff_map"], var_map, "left", passthrough
        )
        assert "ami-11111" in call_left, (
            f"Expected 'ami-11111' in left call:\n{call_left}"
        )

    def test_right_call_contains_original_right_values(self, clone_setup):
        """Right call block should reference values from RIGHT_TF."""
        _, _, var_map, passthrough = _generate_smart_module_tf(
            clone_setup["ast_left"], clone_setup["diff_map"]
        )
        call_right = _generate_smart_module_call(
            "web", clone_setup["diff_map"], var_map, "right", passthrough
        )
        assert "ami-99999" in call_right, (
            f"Expected 'ami-99999' in right call:\n{call_right}"
        )

    @pytest.mark.skipif(not _terraform_available(), reason="terraform CLI not installed")
    def test_terraform_fmt_accepts_generated_files(self, clone_setup):
        """
        If terraform is installed, `terraform fmt -check` must accept
        the generated variables.tf and main.tf without complaints.

        Note: this only validates HCL syntax/formatting — it does NOT
        require `terraform init` or provider downloads.
        """
        vars_tf, main_tf, _, _ = _generate_smart_module_tf(
            clone_setup["ast_left"], clone_setup["diff_map"]
        )
        module_dir: Path = clone_setup["tmp_path"] / "module_out"
        module_dir.mkdir()
        (module_dir / "variables.tf").write_text(vars_tf, encoding="utf-8")
        (module_dir / "main.tf").write_text(main_tf, encoding="utf-8")

        result = subprocess.run(
            ["terraform", "fmt", "-check", str(module_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"`terraform fmt -check` reported formatting issues:\n{result.stdout}\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Tests: _generate_tfvars_refactor
# ---------------------------------------------------------------------------

class TestTfvarsRefactoring:

    def test_all_var_refs_declared_left(self, clone_setup):
        """Every var.* ref in the updated left main.tf must be declared."""
        vars_tf, left_main, _, _, _, _ = _generate_tfvars_refactor(
            clone_setup["ast_left"], clone_setup["ast_right"], clone_setup["diff_map"]
        )
        declared = _collect_declared_variables(vars_tf)
        missing = _collect_var_refs(left_main) - declared
        assert not missing, (
            f"Left main.tf refs undeclared vars: {missing}\n"
            f"--- variables.tf ---\n{vars_tf}\n"
            f"--- left main.tf ---\n{left_main}"
        )

    def test_all_var_refs_declared_right(self, clone_setup):
        """Every var.* ref in the updated right main.tf must be declared."""
        vars_tf, _, right_main, _, _, _ = _generate_tfvars_refactor(
            clone_setup["ast_left"], clone_setup["ast_right"], clone_setup["diff_map"]
        )
        declared = _collect_declared_variables(vars_tf)
        missing = _collect_var_refs(right_main) - declared
        assert not missing, (
            f"Right main.tf refs undeclared vars: {missing}\n"
            f"--- variables.tf ---\n{vars_tf}\n"
            f"--- right main.tf ---\n{right_main}"
        )

    def test_left_tfvars_contains_left_values(self, clone_setup):
        """Left .tfvars should contain the concrete values from LEFT_TF."""
        _, _, _, left_tfvars, _, _ = _generate_tfvars_refactor(
            clone_setup["ast_left"], clone_setup["ast_right"], clone_setup["diff_map"]
        )
        assert "ami-11111" in left_tfvars, (
            f"Expected 'ami-11111' in left tfvars:\n{left_tfvars}"
        )

    def test_right_tfvars_contains_right_values(self, clone_setup):
        """Right .tfvars should contain the concrete values from RIGHT_TF."""
        _, _, _, _, right_tfvars, _ = _generate_tfvars_refactor(
            clone_setup["ast_left"], clone_setup["ast_right"], clone_setup["diff_map"]
        )
        assert "ami-99999" in right_tfvars, (
            f"Expected 'ami-99999' in right tfvars:\n{right_tfvars}"
        )

    def test_left_and_right_tfvars_differ(self, clone_setup):
        """The two generated .tfvars files must be different."""
        _, _, _, left_tfvars, right_tfvars, _ = _generate_tfvars_refactor(
            clone_setup["ast_left"], clone_setup["ast_right"], clone_setup["diff_map"]
        )
        assert left_tfvars != right_tfvars, (
            "Left and right .tfvars are identical — no parameterization occurred"
        )
