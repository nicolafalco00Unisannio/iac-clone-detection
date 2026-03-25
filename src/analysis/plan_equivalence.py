"""Terraform plan equivalence checks for refactoring safety.

This module compares two ``terraform show -json`` plan outputs or
``terraform show`` TXT outputs and verifies that they are semantically
equivalent for infrastructure behavior.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


IGNORED_TOP_LEVEL_KEYS = {
    "terraform_version",
    "format_version",
    "configuration",
    "prior_state",
}


def _normalize_address_for_module_refactor(address: str) -> str:
    """Normalize addresses to ignore module wrapping for refactoring comparisons.
    
    Converts:
      - "module.impl.resource_type.name" -> "resource_type.name"
    
    This allows equivalence checks to recognize that extracting resources into 
    a module is semantically equivalent if the attributes remain unchanged.
    """
    parts = address.split(".")
    # If address starts with "module", skip module parts and return just resource type and name
    if parts[0] == "module" and len(parts) > 2:
        # module.impl.resource_type.name -> resource_type.name
        return ".".join(parts[-2:])
    return address


def _normalize_label_separators(value: str) -> str:
    """Normalize Terraform label separator style (dash vs underscore).

    This is useful when refactoring renamed internal labels from `foo-bar` to
    `foo_bar` while keeping the same effective infrastructure behavior.
    """
    return value.replace("-", "_")


def _normalize_value(value: Any) -> Any:
    """Recursively normalize values for deterministic comparisons."""
    if isinstance(value, dict):
        return {k: _normalize_value(value[k]) for k in sorted(value.keys())}
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    return value


def _normalize_change(change: dict[str, Any], strict: bool) -> dict[str, Any]:
    """Keep only semantically relevant fields from a resource/output change."""
    normalized = {
        "actions": tuple(change.get("actions", [])),
        "before": _normalize_value(change.get("before")),
        "after": _normalize_value(change.get("after")),
        "replace_paths": _normalize_value(change.get("replace_paths", [])),
    }

    if strict:
        normalized["after_unknown"] = _normalize_value(change.get("after_unknown"))

    return normalized


def _semantic_view(
    plan: dict[str, Any],
    *,
    include_output_changes: bool = True,
    strict: bool = False,
    normalize_modules: bool = False,
    normalize_label_separators: bool = False,
) -> dict[str, Any]:
    """Extract a semantic view of a Terraform plan for equivalence checks.
    
    Args:
        plan: The Terraform plan dict to process
        include_output_changes: Whether to include output_changes in comparison
        strict: Whether to include after_unknown fields in comparison
        normalize_modules: If True, normalize resource addresses to ignore module
                          wrapping (e.g., "module.impl.resource.name" -> "resource.name").
                          Useful for recognizing module refactorings as equivalent.
    """
    plan = {
        k: v for k, v in plan.items() if k not in IGNORED_TOP_LEVEL_KEYS
    }

    resource_changes = []
    for item in plan.get("resource_changes", []):
        address = item.get("address")
        if normalize_modules:
            address = _normalize_address_for_module_refactor(address)
        if normalize_label_separators and isinstance(address, str):
            address = _normalize_label_separators(address)

        name = item.get("name")
        if normalize_label_separators and isinstance(name, str):
            name = _normalize_label_separators(name)
        
        resource_changes.append(
            {
                "address": address,
                "mode": item.get("mode"),
                "type": item.get("type"),
                "name": name,
                "index": _normalize_value(item.get("index")),
                "change": _normalize_change(item.get("change", {}), strict=strict),
            }
        )

    resource_changes.sort(key=lambda item: str(item.get("address")))

    result = {"resource_changes": resource_changes}

    if include_output_changes:
        output_changes = []
        for name, item in sorted(plan.get("output_changes", {}).items()):
            output_changes.append(
                {
                    "name": name,
                    "change": _normalize_change(item, strict=strict),
                }
            )
        result["output_changes"] = output_changes

    return result


@dataclass(frozen=True)
class PlanComparisonResult:
    """Result object for plan comparisons."""

    equivalent: bool
    baseline_summary: dict[str, Any]
    candidate_summary: dict[str, Any]


def _load_plan_json(path: str | Path) -> dict[str, Any]:
    """Load plan JSON robustly across common Windows and Unix encodings."""
    file_path = Path(path)
    payload = file_path.read_bytes()

    # PowerShell redirection often produces UTF-16 LE with BOM.
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return json.loads(payload.decode(encoding))
        except UnicodeDecodeError:
            continue
        except json.JSONDecodeError:
            continue

    raise ValueError(
        "Could not decode JSON plan file "
        f"'{file_path}'. Ensure it is valid JSON from `terraform show -json`."
    )


def _parse_plan_txt(path: str | Path) -> dict[str, Any]:
    """Parse a Terraform plan TXT file from `terraform show` output.
    
    Converts the text format to a dict structure compatible with JSON plan format.
    """
    file_path = Path(path)
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    
    resource_changes: list[dict[str, Any]] = []
    output_changes: dict[str, dict[str, Any]] = {}
    current_resource: Optional[dict[str, Any]] = None
    current_output = None
    current_attrs: dict[str, Any] = {}
    in_resources_section = False
    in_outputs_section = False
    
    for line in content.split("\n"):
        # Skip empty lines
        if not line.strip():
            continue
        
        # Detect sections
        if line.strip().startswith("Plan:"):
            if current_resource:
                current_resource["change"]["after"] = current_attrs
                resource_changes.append(current_resource)
                current_resource = None
                current_attrs = {}
            if current_output:
                output_changes[current_output] = {"actions": ["create"], "after": current_attrs, "after_unknown": {}}
                current_output = None
            in_resources_section = False
            in_outputs_section = False
            continue
            
        if "Changes to Outputs:" in line:
            if current_resource:
                current_resource["change"]["after"] = current_attrs
                resource_changes.append(current_resource)
                current_resource = None
                current_attrs = {}
            in_resources_section = False
            in_outputs_section = True
            continue
            
        if "Terraform will perform the following actions:" in line:
            in_resources_section = True
            in_outputs_section = False
            continue
            
        if in_outputs_section:
            # Parse output lines
            # Example: "  + myoutput = {" or "  ~ otheroutput ="
            match = re.match(r"^\s*([\+\-~<=]+)\s+([^\s]+)\s+=", line)
            if match:
                if current_output:
                    output_changes[current_output] = {"actions": ["create"], "after": current_attrs, "after_unknown": {}}
                action_str, output_name = match.groups()
                current_output = output_name
                current_attrs = {}
            elif current_output and re.match(r"^\s{2,}\S+", line):
                attr_line = line.strip()
                if attr_line in ("{", "}", "[", "]", "(") or attr_line.startswith("("):
                    continue
                if "=" in attr_line:
                    parts = attr_line.split("=", 1)
                    key = parts[0].strip().lstrip("+~-=>").strip()
                    val = parts[1].strip()
                    if val != "(known after apply)":
                        current_attrs[key] = val
                    else:
                        current_attrs[key] = True  # treat known after apply loosely
            continue
        
        if not in_resources_section:
            continue
            
        # Skip comment lines but capture resource addresses from them
        if line.strip().startswith("#") and " will be " in line:
            # Parse address from comment
            comment = line.strip()[2:].split(" will be ")[0].strip()
            
            # Save previous resource if exists
            if current_resource:
                current_resource["change"]["after"] = current_attrs
                resource_changes.append(current_resource)
            
            # Extract action from comment
            if " will be created" in line:
                actions = ["create"]
            elif " will be updated" in line:
                actions = ["update"]
            elif " will be destroyed" in line:
                actions = ["delete"]
            elif " will be read" in line:
                actions = ["read"]
            else:
                actions = ["update"]
            
            # Parse the address to extract mode, type, and name
            parts = comment.split(".")
            if len(parts) >= 2:
                # Could be "resource.name" or "module.X.resource.name"
                if parts[0] == "module":
                    # module.impl.harness_platform_input_set.inputset
                    resource_type = parts[-2]
                    resource_name = parts[-1]
                    address = comment
                else:
                    # resource.name format
                    resource_type = parts[-2]
                    resource_name = parts[-1]
                    address = comment
                
                mode = "data" if resource_type.startswith("data.") else "managed"
                if mode == "data":
                    resource_type = resource_type.replace("data.", "")
                
                current_resource = {
                    "address": address,
                    "mode": mode,
                    "type": resource_type,
                    "name": resource_name,
                    "index": None,
                    "change": {
                        "actions": actions,
                        "before": None,
                        "after": {},
                        "replace_paths": [],
                    }
                }
                current_attrs = {}
            continue
        
        # Parse resource block line (e.g., "+ resource "harness_platform_input_set" "inputset" {")
        match = re.match(r"^\s*([\+\-~<=]+)\s+resource\s+\"([^\"]+)\"\s+\"([^\"]+)\"", line)
        if match:
            action_str, resource_type, resource_name = match.groups()
            
            # If we already captured this from comment, do nothing
            if current_resource and current_resource["name"] == resource_name and current_resource["type"] == resource_type:
                pass  # Already processed from comment
            else:
                # Save previous resource if exists
                if current_resource:
                    current_resource["change"]["after"] = current_attrs
                    resource_changes.append(current_resource)
                
                # Map action strings to terraform actions
                action_map = {
                    "+": ["create"],
                    "-": ["delete"],
                    "~": ["update"],
                    "<=": ["read"],
                    "<": ["delete"],
                    ">": ["create"],
                }
                actions = action_map.get(action_str[0], ["update"])
                
                current_resource = {
                    "address": f"{resource_type}.{resource_name}",
                    "mode": "managed",
                    "type": resource_type,
                    "name": resource_name,
                    "index": None,
                    "change": {
                        "actions": actions,
                        "before": None,
                        "after": {},
                        "replace_paths": [],
                    }
                }
                current_attrs = {}
        
        # Parse attribute lines (indented with spaces, but within resource block)
        elif current_resource and re.match(r"^\s{2,}\S+", line):
            attr_line = line.strip()
            # Skip structural lines
            if attr_line in ("{", "}", "[", "]", "("):
                continue
            
            if "=" in attr_line:
                # Extract key and value
                parts = attr_line.split("=", 1)
                key = parts[0].strip()
                value = parts[1].strip() if len(parts) > 1 else ""
                
                # Skip complex structures for now
                if value in ("{", "[", "<<-EOT"):
                    continue
                
                # Handle different value formats
                if value == "(known after apply)":
                    value = None
                elif value.startswith('"') and value.endswith('"'):
                    # Remove quotes and unescape
                    value = value[1:-1].replace('\\"', '"')
                elif value == "false":
                    value = False
                elif value == "true":
                    value = True
                elif value.isdigit():
                    value = int(value)
                
                current_attrs[key] = value
    
    # Don't forget the last resource or output
    if current_resource:
        current_resource["change"]["after"] = current_attrs
        resource_changes.append(current_resource)
    if current_output:
        output_changes[current_output] = {"actions": ["create"], "after": current_attrs, "after_unknown": {}}
    
    # Return a dict structure compatible with JSON plan format
    return {
        "resource_changes": resource_changes,
        "output_changes": output_changes,
    }


def _load_plan_file(path: str | Path) -> dict[str, Any]:
    """Load a Terraform plan file (JSON or TXT format)."""
    file_path = Path(path)
    
    # Try JSON first
    try:
        return _load_plan_json(file_path)
    except ValueError:
        pass
    
    # Try TXT format
    try:
        return _parse_plan_txt(file_path)
    except Exception as e:
        raise ValueError(
            f"Could not parse plan file '{file_path}' as JSON or TXT format. Error: {e}"
        )



def compare_plan_dicts(
    baseline_plan: dict[str, Any],
    candidate_plan: dict[str, Any],
    *,
    include_output_changes: bool = True,
    strict: bool = False,
    normalize_modules: bool = False,
    normalize_label_separators: bool = False,
) -> PlanComparisonResult:
    """Compare two Terraform plans represented as Python dicts.
    
    Args:
        baseline_plan: The baseline plan dict
        candidate_plan: The candidate plan dict  
        include_output_changes: Whether to include output_changes
        strict: Whether to compare after_unknown fields
        normalize_modules: If True, ignore module wrapping differences.
                          Useful for recognizing module refactorings as equivalent.
    """
    baseline_summary = _semantic_view(
        baseline_plan,
        include_output_changes=include_output_changes,
        strict=strict,
        normalize_modules=normalize_modules,
        normalize_label_separators=normalize_label_separators,
    )
    candidate_summary = _semantic_view(
        candidate_plan,
        include_output_changes=include_output_changes,
        strict=strict,
        normalize_modules=normalize_modules,
        normalize_label_separators=normalize_label_separators,
    )

    return PlanComparisonResult(
        equivalent=baseline_summary == candidate_summary,
        baseline_summary=baseline_summary,
        candidate_summary=candidate_summary,
    )


def compare_plan_files(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    include_output_changes: bool = True,
    strict: bool = False,
    normalize_modules: bool = False,
    normalize_label_separators: bool = False,
) -> PlanComparisonResult:
    """Load plan files (JSON or TXT format) and compare them semantically.
    
    Args:
        baseline_path: Path to baseline plan file
        candidate_path: Path to candidate plan file
        include_output_changes: Whether to include output_changes
        strict: Whether to compare after_unknown fields
        normalize_modules: If True, ignore module wrapping differences
    """
    baseline_data = _load_plan_file(baseline_path)
    candidate_data = _load_plan_file(candidate_path)
    return compare_plan_dicts(
        baseline_data,
        candidate_data,
        include_output_changes=include_output_changes,
        strict=strict,
        normalize_modules=normalize_modules,
        normalize_label_separators=normalize_label_separators,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two Terraform plan files (JSON from `terraform show -json` "
            "or TXT from `terraform show`) and fail if their semantic behavior differs."
        )
    )
    parser.add_argument("baseline_plan", help="Path to baseline plan file (JSON or TXT)")
    parser.add_argument("candidate_plan", help="Path to candidate plan file (JSON or TXT)")
    parser.add_argument(
        "--ignore-output-changes",
        action="store_true",
        help="Ignore output_changes differences",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also compare after_unknown payloads",
    )
    parser.add_argument(
        "--normalize-modules",
        action="store_true",
        help="Ignore module wrapping differences (treats 'module.X.resource.name' as equivalent to 'resource.name')",
    )
    parser.add_argument(
        "--normalize-label-separators",
        action="store_true",
        help="Treat Terraform label style differences as equivalent (e.g. 'name-with-dash' == 'name_with_dash')",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    result = compare_plan_files(
        args.baseline_plan,
        args.candidate_plan,
        include_output_changes=not args.ignore_output_changes,
        strict=args.strict,
        normalize_modules=args.normalize_modules,
        normalize_label_separators=args.normalize_label_separators,
    )

    if result.equivalent:
        print("Plan equivalence check: PASS")
        return 0

    print("Plan equivalence check: FAIL")
    print("--- Baseline semantic summary ---")
    print(json.dumps(result.baseline_summary, indent=2, sort_keys=True))
    print("--- Candidate semantic summary ---")
    print(json.dumps(result.candidate_summary, indent=2, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
