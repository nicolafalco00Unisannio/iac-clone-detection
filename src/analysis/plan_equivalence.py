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
) -> dict[str, Any]:
    """Extract a semantic view of a Terraform plan for equivalence checks."""
    plan = {
        k: v for k, v in plan.items() if k not in IGNORED_TOP_LEVEL_KEYS
    }

    resource_changes = []
    for item in plan.get("resource_changes", []):
        resource_changes.append(
            {
                "address": item.get("address"),
                "mode": item.get("mode"),
                "type": item.get("type"),
                "name": item.get("name"),
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
    current_resource: Optional[dict[str, Any]] = None
    current_attrs: dict[str, Any] = {}
    
    for line in content.split("\n"):
        # Skip empty lines
        if not line.strip():
            continue
            
        # Check for resource change header (e.g., "+ aws_instance.consul_0" or "<= data.template_file.consul_update")
        # Pattern allows optional leading whitespace
        match = re.match(r"^\s*([\+\-~<=]+)\s+([^.]+)\.([^\s]+)(?:\s*\(.*\))?$", line)
        if match:
            # Save previous resource if exists
            if current_resource:
                current_resource["change"]["after"] = current_attrs
                resource_changes.append(current_resource)
            
            action_str, resource_type, resource_name = match.groups()
            
            # Map action strings to terraform actions
            action_map = {
                "+": ["create"],
                "-": ["delete"],
                "~": ["update"],
                "<=": ["read"],  # data source read
                "<": ["delete"],
                ">": ["create"],
            }
            actions = action_map.get(action_str, ["update"])
            
            current_resource = {
                "address": f"{resource_type}.{resource_name}",
                "mode": "data" if resource_type.startswith("data.") else "managed",
                "type": resource_type.replace("data.", ""),
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
        
        # Parse attribute lines (indented with spaces, but more than resource lines)
        elif line.startswith("      ") and current_resource:
            # Extract key and value
            attr_line = line.strip()
            if ":" in attr_line:
                parts = attr_line.split(":", 1)
                key = parts[0].strip()
                value = parts[1].strip() if len(parts) > 1 else ""
                
                # Handle different value formats
                if value == "<computed>":
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
    
    # Don't forget the last resource
    if current_resource:
        current_resource["change"]["after"] = current_attrs
        resource_changes.append(current_resource)
    
    # Return a dict structure compatible with JSON plan format
    return {
        "resource_changes": resource_changes,
        "output_changes": {},
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
) -> PlanComparisonResult:
    """Compare two Terraform plans represented as Python dicts."""
    baseline_summary = _semantic_view(
        baseline_plan,
        include_output_changes=include_output_changes,
        strict=strict,
    )
    candidate_summary = _semantic_view(
        candidate_plan,
        include_output_changes=include_output_changes,
        strict=strict,
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
) -> PlanComparisonResult:
    """Load plan files (JSON or TXT format) and compare them semantically."""
    baseline_data = _load_plan_file(baseline_path)
    candidate_data = _load_plan_file(candidate_path)
    return compare_plan_dicts(
        baseline_data,
        candidate_data,
        include_output_changes=include_output_changes,
        strict=strict,
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
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    result = compare_plan_files(
        args.baseline_plan,
        args.candidate_plan,
        include_output_changes=not args.ignore_output_changes,
        strict=args.strict,
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
