"""
Terraform module generation and refactoring suggestions.
"""

from src.utils.hcl_utils import _sanitize_var_name, _hcl_value
import re

_VAR_REF_RE = re.compile(r"\bvar\.([A-Za-z_][A-ZaLz0-9_]*)\b")
_INTERP_VAR_REF_RE = re.compile(r"\$\{\s*var\.([A-Za-z_][A-Za-z0-9_]*)\s*\}")

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

    for path, details in diff_map.items():
        var_name = _sanitize_var_name(path)

        counter = 1
        original_name = var_name
        while var_name in variable_map.values():
            var_name = f"{original_name}_{counter}"
            counter += 1

        variable_map[path] = var_name
        var_types[var_name] = details["type"]

        var_def = f'variable "{var_name}" {{\n'
        var_def += f'  description = "Refactored from {path}"\n'
        var_def += f'  type        = {details["type"]}\n'
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
    for path, var_name in variable_map.items():
        val = diff_map[path]["val1"] if specific_ast_values == "left" else diff_map[path]["val2"]
        call_lines.append(f"  {var_name} = {_hcl_value(val)}")

    # Variables already used in the code (must be passed through)
    for name in sorted(passthrough_vars.keys()):
        # Use interpolation to stay consistent with legacy-style configs
        call_lines.append(f'  {name} = "${{var.{name}}}"')

    call_lines.append("}")
    return "\n".join(call_lines)

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

def _generate_module_call(module_name, differences, original_values):
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
    variable_map = {}
    var_definitions = []
    var_types = {}

    used_names = set()

    for path, details in diff_map.items():
        v1 = details.get("val1")
        v2 = details.get("val2")

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
        variable_map[path] = var_name
        var_types[var_name] = details.get("type", "string")

        # Declare the variable only if we *introduced* it (i.e., not clearly reused from existing var ref)
        # Heuristic: if preferred was detected, assume it already exists in at least one file.
        if not preferred:
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

    for path, var_name in variable_map.items():
        v1 = diff_map[path]["val1"]
        v2 = diff_map[path]["val2"]

        if _extract_single_var_name_from_value(v1) is None:
            left_tfvars_lines.append(f"{var_name} = {_hcl_value(v1)}")
        else:
            left_tfvars_lines.append(f"# {var_name} already comes from var.{var_name} in original left file; no tfvars needed")

        if _extract_single_var_name_from_value(v2) is None:
            right_tfvars_lines.append(f"{var_name} = {_hcl_value(v2)}")
        else:
            right_tfvars_lines.append(f"# {var_name} already comes from var.{var_name} in original right file; no tfvars needed")

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
