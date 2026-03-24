"""
Terraform module generation and refactoring suggestions.
"""

from src.utils.hcl_utils import _sanitize_var_name, _hcl_value
import re

_VAR_REF_RE = re.compile(r"\bvar\.([A-Za-z_][A-Za-z0-9_]*)\b")
_INTERP_VAR_REF_RE = re.compile(r"\$\{\s*var\.([A-Za-z_][A-Za-z0-9_]*)\s*\}")

_MODULE_SOURCE_PATH_RE = re.compile(r"^module\[\d+\]\.[^.]+\.source$")


def _split_tfvars_eligible_diffs(diff_map):
    """Split differences into tfvars-eligible and excluded ones.

    Excluded entries include paths that Terraform does not allow to be configured
    via input variables / tfvars.
    """
    eligible = {}
    excluded = {}

    for path, details in diff_map.items():
        reason = None

        # Terraform module source addresses must be literal strings at init time.
        if _MODULE_SOURCE_PATH_RE.match(path):
            reason = (
                "module source must be a literal string "
                "(cannot be parameterized with var/tfvars)"
            )

        if reason:
            excluded[path] = reason
            continue

        eligible[path] = details

    return eligible, excluded


def _signature_value(value):
    """Create a stable string signature for grouping equivalent diffs."""
    if isinstance(value, (dict, list, tuple, set)):
        return repr(value)
    return str(value)

def _extract_var_references(node):
    """
    Collects variable names referenced as var.<name> inside string leaves (and any raw strings).
    This is needed because when we move code into a module, any existing var.* references
    must be declared in the module and passed through by the caller.
    """
    refs = set()

    if isinstance(node, dict):
        for v in node.values():
            refs.update(_extract_var_references(v))
        return refs

    if isinstance(node, list):
        for item in node:
            refs.update(_extract_var_references(item))
        return refs

    if isinstance(node, str):
        for m in _VAR_REF_RE.finditer(node):
            refs.add(m.group(1))
        return refs

    return refs

def _render_hcl_recursive(node, variable_map, current_path="", indent_level=0, var_types=None):
    """
    Rebuilds HCL from AST, injecting variables where differences were found.
    """
    indent = "  " * indent_level
    lines = []
    var_types = var_types or {}

    # If this leaf node is a known variableized path, emit a var reference.
    if current_path in variable_map:
        var_name = variable_map[current_path]
        # Keep output compatible with legacy-style configs that heavily use interpolation strings.
        # For non-string types we still emit interpolation; Terraform will coerce in many cases.
        # (This is a generator; correctness > perfect typing.)
        return f'"${{var.{var_name}}}"'

    if isinstance(node, dict):
        for k, v in node.items():
            new_path = f"{current_path}.{k}" if current_path else k

            # Special handling for top-level blocks to resemble Terraform syntax
            if indent_level == 0 and k in ["resource", "data", "module"]:
                if isinstance(v, list):
                    for i, item in enumerate(v):
                        for type_name, resources in item.items():
                            for res_name, props in resources.items():
                                lines.append(f'\n{k} "{type_name}" "{res_name}" {{')
                                sub_path = f"{new_path}[{i}].{type_name}.{res_name}"
                                lines.append(_render_hcl_recursive(props, variable_map, sub_path, indent_level + 1, var_types))
                                lines.append("}\n")
                continue

            if isinstance(v, dict):
                lines.append(f"{indent}{k} {{")
                lines.append(_render_hcl_recursive(v, variable_map, new_path, indent_level + 1, var_types))
                lines.append(f"{indent}}}")
            elif isinstance(v, list):
                if len(v) > 0 and isinstance(v[0], dict):
                    for i, item in enumerate(v):
                        lines.append(f"{indent}{k} {{")
                        lines.append(_render_hcl_recursive(item, variable_map, f"{new_path}[{i}]", indent_level + 1, var_types))
                        lines.append(f"{indent}}}")
                else:
                    val_str = _render_hcl_recursive(v, variable_map, new_path, indent_level, var_types)
                    lines.append(f"{indent}{k} = {val_str}")
            else:
                val_str = _render_hcl_recursive(v, variable_map, new_path, indent_level, var_types)
                lines.append(f"{indent}{k} = {val_str}")

    elif isinstance(node, list):
        rendered_items = [
            _render_hcl_recursive(x, variable_map, f"{current_path}[{i}]", indent_level, var_types)
            for i, x in enumerate(node)
        ]
        return f"[{', '.join(rendered_items)}]"

    else:
        return _hcl_value(node)

    return "\n".join(lines)

def _generate_smart_module_tf(ast1, diff_map):
    """
    Generates variables.tf and main.tf using the AST and Diff Map.

    Returns:
      (variables_tf_str, main_tf_str, diff_variable_map, passthrough_vars)
    """
    # 1) Variables created from actual differences (path -> var_name)
    variable_map = {}
    var_definitions = []
    var_types = {}  # var_name -> terraform type string

    used_var_names = set()
    signature_to_var = {}

    for path, details in diff_map.items():
        diff_type = details.get("type", "string")
        signature = (
            _signature_value(details.get("val1")),
            _signature_value(details.get("val2")),
            diff_type,
        )

        # Collapse repeated equivalent differences (same val1/val2/type) into one input variable.
        if signature in signature_to_var:
            variable_map[path] = signature_to_var[signature]
            continue

        preferred = _extract_single_var_name_from_value(details.get("val1")) or _extract_single_var_name_from_value(details.get("val2"))
        base_name = preferred or _sanitize_var_name(path)

        var_name = base_name
        counter = 1
        while var_name in used_var_names:
            var_name = f"{base_name}_{counter}"
            counter += 1

        used_var_names.add(var_name)
        signature_to_var[signature] = var_name
        variable_map[path] = var_name
        var_types[var_name] = diff_type

        var_def = f'variable "{var_name}" {{\n'
        var_def += f'  description = "Refactored from {path}"\n'
        var_def += f'  type        = {diff_type}\n'
        var_def += "}\n"
        var_definitions.append(var_def)

    # 2) Detect existing var.* references inside the code we are moving into the module
    referenced_vars = _extract_var_references(ast1)

    # Don’t re-declare variables we already created for differences
    diff_var_names = set(variable_map.values())

    passthrough_vars = {}
    for name in sorted(referenced_vars):
        if name in diff_var_names:
            continue
        passthrough_vars[name] = "any"
        var_definitions.append(
            f'variable "{name}" {{\n'
            f'  description = "Pass-through variable (referenced in cloned code)"\n'
            f"  type        = any\n"
            f"}}\n"
        )

    # 3) Render the module main.tf using AST1 as skeleton
    main_tf_content = _render_hcl_recursive(ast1, variable_map, var_types=var_types)

    return "\n".join(var_definitions), main_tf_content, variable_map, passthrough_vars

def _generate_smart_module_call(module_name, diff_map, variable_map, specific_ast_values, passthrough_vars=None):
    """
    Generates the module usage block.
    - For diff variables: use concrete values from val1/val2
    - For pass-through variables: wire caller var.<name> into module input <name>
    """
    passthrough_vars = passthrough_vars or {}

    call_lines = [
        f'module "{module_name}" {{',
        f'  source = "./modules/{module_name}"'
    ]

    # Parameters that actually differ
    assigned_vars = set()
    for path, var_name in variable_map.items():
        if var_name in assigned_vars:
            continue
        val = diff_map[path]["val1"] if specific_ast_values == "left" else diff_map[path]["val2"]
        call_lines.append(f"  {var_name} = {_hcl_value(val)}")
        assigned_vars.add(var_name)

    # Variables already used in the code (must be passed through)
    for name in sorted(passthrough_vars.keys()):
        # Use interpolation to stay consistent with legacy-style configs
        call_lines.append(f'  {name} = "${{var.{name}}}"')

    call_lines.append("}")
    return "\n".join(call_lines)


def _collect_defined_resources(ast):
    """Collect top-level Terraform resources defined in an AST."""
    resources = []
    for item in ast.get("resource", []) if isinstance(ast, dict) else []:
        if not isinstance(item, dict):
            continue
        for resource_type, named_resources in item.items():
            if not isinstance(named_resources, dict):
                continue
            for resource_name in named_resources.keys():
                resources.append((resource_type, resource_name))
    return resources


def _generate_module_outputs(ast, consumer_texts=None):
    """Generate outputs.tf content for externally referenced resource attributes."""
    consumer_texts = consumer_texts or []
    resources = _collect_defined_resources(ast)
    used_attrs = {resource: set() for resource in resources}

    for resource_type, resource_name in resources:
        pattern = re.compile(
            rf"\b{re.escape(resource_type)}\.{re.escape(resource_name)}\.([A-Za-z_][A-Za-z0-9_]*)\b"
        )
        for text in consumer_texts:
            if not isinstance(text, str):
                continue
            used_attrs[(resource_type, resource_name)].update(pattern.findall(text))

    ref_output_map = {}
    used_output_names = set()
    output_blocks = []

    for resource_type, resource_name in resources:
        attrs = sorted(used_attrs[(resource_type, resource_name)] or {"id"})
        for attr in attrs:
            base_name = _sanitize_var_name(f"{resource_name}_{attr}")
            output_name = base_name
            counter = 1
            while output_name in used_output_names:
                output_name = f"{base_name}_{counter}"
                counter += 1

            used_output_names.add(output_name)
            ref_output_map[f"{resource_type}.{resource_name}.{attr}"] = output_name
            output_blocks.append(
                f'output "{output_name}" {{\n'
                f'  value = "${{{resource_type}.{resource_name}.{attr}}}"\n'
                f'}}\n'
            )

    return "\n".join(output_blocks), ref_output_map


def _rewrite_consumer_hcl(hcl_text, ref_output_map, module_name):
    """Rewrite direct resource attribute references to module outputs."""
    rewritten = hcl_text
    replacements = {}

    for old_ref, output_name in sorted(ref_output_map.items(), key=lambda item: len(item[0]), reverse=True):
        new_ref = f"module.{module_name}.{output_name}"
        pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(old_ref)}(?![A-Za-z0-9_])")
        updated = pattern.sub(new_ref, rewritten)
        if updated != rewritten:
            replacements[old_ref] = new_ref
            rewritten = updated

    return rewritten, replacements

def _generate_module_tf(base_ast, differences):
    """Generates the HCL for a new Terraform module."""
    variables = {}
    # Naively create variable names from the diff path
    for diff in differences:
        # Example diff: "Value differs at '.resource.aws_instance.web.instance_type': ('t2.micro' vs 't2.large')"
        try:
            path_part = diff.split("'")[1]
            # A simple heuristic for variable names
            var_name = path_part.split('.')[-1]
            variables[var_name] = {'path': path_part}
        except IndexError:
            continue

    # --- Generate variables.tf content ---
    var_tf_lines = ['# variables.tf for the new module\n']
    for name in sorted(variables.keys()):
        var_tf_lines.append(f'variable "{name}" {{')
        var_tf_lines.append('  description = "Autogenerated variable"')
        var_tf_lines.append('}\n')

    # --- Generate main.tf content (very simplified) ---
    # This is a complex task. For this example, we'll just show the concept
    # by replacing values in a string representation of the original resource.
    # A real implementation would need a robust HCL generator.
    main_tf_lines = ['# main.tf for the new module\n']
    
    # Handle that 'resource' can be a list of dicts or a single dict
    resource_block = base_ast.get('resource')
    if isinstance(resource_block, list):
        resource_block = resource_block[0] # Use the first resource block as a template
    
    # Let's find the first resource block to use as a template
    resource_key = next((k for k in resource_block), None) if resource_block else None
    if resource_key:
        resource_name = next(iter(resource_block[resource_key]), None)
        if resource_name:
            # Crude representation of the resource
            main_tf_lines.append(f'resource "{resource_key}" "{resource_name}" {{')
            
            # The resource block can be a list with one dict or just the dict
            resource_attributes = resource_block[resource_key][resource_name]
            if isinstance(resource_attributes, list):
                resource_attributes = resource_attributes[0]

            for key, value in resource_attributes.items():
                 # Check if this attribute is a variable
                is_variable = False
                for var_name, var_info in variables.items():
                    if var_info['path'].endswith(f'.{key}'):
                        main_tf_lines.append(f'  {key} = var.{var_name}')
                        is_variable = True
                        break
                if not is_variable:
                    main_tf_lines.append(f'  {key} = "{value}"') # Note: simplistic quoting
            main_tf_lines.append('}')

    return '\n'.join(var_tf_lines), '\n'.join(main_tf_lines)

def _generate_module_call(module_name, differences, _original_values):
    """Generates the HCL for calling the new module."""
    call_lines = [f'module "{module_name}" {{', '  source = "./modules/{module_name}"\n']
    
    variables = {}
    for diff in differences:
        try:
            path_part = diff.split("'")[1]
            var_name = path_part.split('.')[-1]
            # Extract the first value as an example
            value = diff.split("'")[3]
            variables[var_name] = value
        except IndexError:
            continue

    for name, value in sorted(variables.items()):
        call_lines.append(f'  {name} = "{value}"')

    call_lines.append('}')
    return '\n'.join(call_lines)

def _extract_single_var_name_from_value(val):
    """
    If val is a string containing var.X or ${var.X}, return 'X' (only if exactly one unique match).
    Otherwise return None.
    """
    if not isinstance(val, str):
        return None
    matches = set()
    matches.update(m.group(1) for m in _VAR_REF_RE.finditer(val))
    matches.update(m.group(1) for m in _INTERP_VAR_REF_RE.finditer(val))
    if len(matches) == 1:
        return next(iter(matches))
    return None

def _generate_tfvars_refactor(ast_left, ast_right, diff_map):
    """
    Generates:
      - variables.tf (only for newly introduced vars)
      - updated main.tf for left/right with injected var refs
      - left/right tfvars with ONLY literal assignments (no var.*)

    Special case:
      If one side already uses var.<x> for the differing value, we reuse <x>
      instead of creating a new variable name.
    """
    eligible_diff_map, _ = _split_tfvars_eligible_diffs(diff_map)

    variable_map = {}
    var_definitions = []
    var_types = {}

    used_names = set()
    signature_to_var = {}

    for path, details in eligible_diff_map.items():
        v1 = details.get("val1")
        v2 = details.get("val2")
        diff_type = details.get("type", "string")
        signature = (
            _signature_value(v1),
            _signature_value(v2),
            diff_type,
        )

        if signature in signature_to_var:
            variable_map[path] = signature_to_var[signature]
            continue

        # Prefer reusing an existing variable reference if present on either side
        preferred = _extract_single_var_name_from_value(v1) or _extract_single_var_name_from_value(v2)

        if preferred:
            var_name = preferred
        else:
            base = _sanitize_var_name(path)
            var_name = base
            n = 1
            while var_name in used_names:
                var_name = f"{base}_{n}"
                n += 1

        used_names.add(var_name)
        signature_to_var[signature] = var_name
        variable_map[path] = var_name
        var_types[var_name] = diff_type

        # Always declare variables referenced by the generated shared template.
        # Reused names (detected via existing var.<name> references) may not have
        # a matching variables.tf in the target location, which causes runtime
        # errors like "unknown variable referenced".
        var_definitions.append(
            f'variable "{var_name}" {{\n'
            f'  description = "Refactored from {path}"\n'
            f'  type        = {var_types[var_name]}\n'
            f'}}\n'
        )

    variables_tf_str = "\n".join(var_definitions).strip() + ("\n" if var_definitions else "")

    left_main_tf_str = _render_hcl_recursive(ast_left, variable_map, var_types=var_types)
    right_main_tf_str = _render_hcl_recursive(ast_right, variable_map, var_types=var_types)

    # tfvars: emit only literal values; skip those that already were var.* on that side
    left_tfvars_lines = []
    right_tfvars_lines = []
    left_assigned = set()
    right_assigned = set()

    for path, var_name in variable_map.items():
        v1 = eligible_diff_map[path]["val1"]
        v2 = eligible_diff_map[path]["val2"]

        if var_name not in left_assigned and _extract_single_var_name_from_value(v1) is None:
            left_tfvars_lines.append(f"{var_name} = {_hcl_value(v1)}")
            left_assigned.add(var_name)
        elif var_name not in left_assigned:
            left_tfvars_lines.append(f"# {var_name} already comes from var.{var_name} in original left file; no tfvars needed")
            left_assigned.add(var_name)

        if var_name not in right_assigned and _extract_single_var_name_from_value(v2) is None:
            right_tfvars_lines.append(f"{var_name} = {_hcl_value(v2)}")
            right_assigned.add(var_name)
        elif var_name not in right_assigned:
            right_tfvars_lines.append(f"# {var_name} already comes from var.{var_name} in original right file; no tfvars needed")
            right_assigned.add(var_name)

    left_tfvars_str = "\n".join(left_tfvars_lines).strip() + "\n"
    right_tfvars_str = "\n".join(right_tfvars_lines).strip() + "\n"

    return (
        variables_tf_str,
        left_main_tf_str,
        right_main_tf_str,
        left_tfvars_str,
        right_tfvars_str,
        variable_map,
    )


def _generate_tfvars_bundle(ast_left, ast_right, diff_map):
    """Generate an integration-ready tfvars refactoring bundle.

    Returns a dict with a canonical shared template plus per-variant tfvars.
    """
    eligible_diff_map, excluded_differences = _split_tfvars_eligible_diffs(diff_map)

    (
        variables_tf,
        left_main_tf,
        right_main_tf,
        left_tfvars,
        right_tfvars,
        variable_map,
    ) = _generate_tfvars_refactor(ast_left, ast_right, eligible_diff_map)

    shared_main_tf = left_main_tf
    if right_main_tf != left_main_tf:
        shared_main_tf = left_main_tf

    return {
        "variables_tf": variables_tf,
        "shared_main_tf": shared_main_tf,
        "left_main_tf": left_main_tf,
        "right_main_tf": right_main_tf,
        "left_tfvars": left_tfvars,
        "right_tfvars": right_tfvars,
        "variable_map": variable_map,
        "excluded_differences": excluded_differences,
        "template_equal": left_main_tf == right_main_tf,
    }


def _generate_wrapper_module_suggestion(
    ast_template,
    canonical_source,
    module_instance_name="impl",
    fixed_inputs=None,
    output_names=None,
):
    """Build a wrapper-module delegation suggestion for Type 1 clone removal.

    The wrapper keeps only a module call that forwards all referenced variables
    and optionally pins selected inputs to literal values.
    """
    fixed_inputs = fixed_inputs or {}
    output_names = output_names or []
    passthrough_vars = sorted(_extract_var_references(ast_template) - set(fixed_inputs.keys()))

    # Generate wrapper variables.tf to declare all passthrough variables
    var_blocks = []
    for name in passthrough_vars:
        var_blocks.append(
            f'variable "{name}" {{\n'
            f'  description = "Pass-through variable for canonical module"\n'
            f'  type        = any\n'
            f'}}\n'
        )
    variables_tf = "\n".join(var_blocks).strip() + ("\n" if var_blocks else "")

    wrapper_lines = [
        f'module "{module_instance_name}" {{',
        f'  source = "{canonical_source}"',
    ]

    for name in sorted(fixed_inputs.keys()):
        wrapper_lines.append(f"  {name} = {_hcl_value(fixed_inputs[name])}")

    for name in passthrough_vars:
        wrapper_lines.append(f'  {name} = "${{var.{name}}}"')

    wrapper_lines.append("}")

    if output_names:
        output_blocks = []
        for name in sorted(output_names):
            output_blocks.append(
                f'output "{name}" {{\n'
                f'  value = "${{module.{module_instance_name}.{name}}}"\n'
                f'}}\n'
            )
        outputs_tf = "\n".join(output_blocks).rstrip() + "\n"
    else:
        outputs_tf = (
            "# No output names were discovered automatically.\n"
            "# For each existing output in the duplicate module, forward it as:\n"
            f'# output "<output_name>" {{ value = "${{module.{module_instance_name}.<output_name>}}" }}\n'
        )

    return {
        "strategy": "module_wrapper_delegation",
        "canonical_source": canonical_source,
        "module_instance_name": module_instance_name,
        "passthrough_variables": passthrough_vars,
        "fixed_inputs": fixed_inputs,
        "wrapper_variables_tf": variables_tf,
        "wrapper_main_tf": "\n".join(wrapper_lines),
        "wrapper_outputs_tf": outputs_tf,
        "steps": [
            "Keep only one canonical implementation module.",
            "Replace duplicate implementation with the wrapper module call.",
            "Forward existing outputs from wrapper to module outputs.",
            "Keep per-environment values in tfvars or caller modules.",
        ],
    }
