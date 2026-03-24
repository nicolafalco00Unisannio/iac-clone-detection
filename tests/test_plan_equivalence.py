"""Tests for semantic Terraform plan equivalence checks."""

from copy import deepcopy
import json

from src.analysis.plan_equivalence import compare_plan_dicts, compare_plan_files


def _sample_plan() -> dict:
    return {
        "format_version": "1.2",
        "terraform_version": "1.8.2",
        "resource_changes": [
            {
                "address": "aws_instance.web",
                "mode": "managed",
                "type": "aws_instance",
                "name": "web",
                "change": {
                    "actions": ["update"],
                    "before": {"instance_type": "t2.micro", "tags": {"Env": "dev"}},
                    "after": {"instance_type": "t2.small", "tags": {"Env": "dev"}},
                    "after_unknown": {"id": True},
                },
            }
        ],
        "output_changes": {
            "instance_type": {
                "actions": ["update"],
                "before": "t2.micro",
                "after": "t2.small",
                "after_unknown": False,
            }
        },
    }


def test_equivalent_ignores_top_level_metadata():
    baseline = _sample_plan()
    candidate = _sample_plan()
    candidate["terraform_version"] = "1.9.0"
    candidate["format_version"] = "2.0"

    result = compare_plan_dicts(baseline, candidate)

    assert result.equivalent is True


def test_detects_resource_action_difference():
    baseline = _sample_plan()
    candidate = _sample_plan()
    candidate["resource_changes"][0]["change"]["actions"] = ["create"]

    result = compare_plan_dicts(baseline, candidate)

    assert result.equivalent is False


def test_detects_resource_after_value_difference():
    baseline = _sample_plan()
    candidate = _sample_plan()
    candidate["resource_changes"][0]["change"]["after"]["instance_type"] = "m5.large"

    result = compare_plan_dicts(baseline, candidate)

    assert result.equivalent is False


def test_ignore_output_changes_mode():
    baseline = _sample_plan()
    candidate = _sample_plan()
    candidate["output_changes"]["instance_type"]["after"] = "m5.large"

    result = compare_plan_dicts(baseline, candidate, include_output_changes=False)

    assert result.equivalent is True


def test_strict_mode_compares_after_unknown():
    baseline = _sample_plan()
    candidate = _sample_plan()
    candidate["resource_changes"][0]["change"]["after_unknown"] = {"id": False}

    non_strict = compare_plan_dicts(baseline, candidate, strict=False)
    strict = compare_plan_dicts(baseline, candidate, strict=True)

    assert non_strict.equivalent is True
    assert strict.equivalent is False


def test_resource_change_order_does_not_matter():
    baseline = _sample_plan()
    extra = deepcopy(baseline["resource_changes"][0])
    extra["address"] = "aws_security_group.web"
    extra["type"] = "aws_security_group"
    extra["name"] = "web"
    baseline["resource_changes"].append(extra)

    candidate = deepcopy(baseline)
    candidate["resource_changes"] = list(reversed(candidate["resource_changes"]))

    result = compare_plan_dicts(baseline, candidate)

    assert result.equivalent is True


def test_compare_plan_files_supports_utf16(tmp_path):
    baseline = _sample_plan()
    candidate = _sample_plan()

    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"

    baseline_path.write_text(json.dumps(baseline), encoding="utf-16")
    candidate_path.write_text(json.dumps(candidate), encoding="utf-16")

    result = compare_plan_files(baseline_path, candidate_path)

    assert result.equivalent is True
