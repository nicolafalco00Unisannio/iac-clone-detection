"""
Terraform module generation and refactoring suggestions.
"""

from src.utils.hcl_utils import _sanitize_var_name, _hcl_value

def _render_hcl_recursive(node, variable_map, current_path="", indent_level=0):
    """
    Rebuilds HCL from AST, injecting 'var.xyz' where differences were found.
    FIX: Now correctly includes list indices [i] in paths for root-level resources.
    """
    indent = "  " * indent_level
    lines = []

    # Check if this specific leaf node is a known variable
    if current_path in variable_map:
        var_name = variable_map[current_path]
        return f"var.{var_name}"

    if isinstance(node, dict):
        for k, v in node.items():
            new_path = f"{current_path}.{k}" if current_path else k
            
            # Special handling for resource/module/data blocks to make them look like HCL
            if indent_level == 0 and k in ['resource', 'data', 'module']:
                if isinstance(v, list):
                    # FIX: Enumerate to track the index [i] matching the diff map
                    for i, item in enumerate(v):
                        for type_name, resources in item.items():
                            for res_name, props in resources.items():
                                lines.append(f'\n{k} "{type_name}" "{res_name}" {{')
                                # FIX: Include [i] in the path
                                sub_path = f"{new_path}[{i}].{type_name}.{res_name}" 
                                lines.append(_render_hcl_recursive(props, variable_map, sub_path, indent_level+1))
                                lines.append("}\n")
                continue

            # Standard attribute or child block
            if isinstance(v, dict):
                lines.append(f"{indent}{k} {{")
                lines.append(_render_hcl_recursive(v, variable_map, new_path, indent_level+1))
                lines.append(f"{indent}}}")
            elif isinstance(v, list):
                 # Heuristic: if list of dicts, it's likely repeated blocks (like ingress {})
                 if len(v) > 0 and isinstance(v[0], dict):
                     for i, item in enumerate(v):
                         lines.append(f"{indent}{k} {{")
                         lines.append(_render_hcl_recursive(item, variable_map, f"{new_path}[{i}]", indent_level+1))
                         lines.append(f"{indent}}}")
                 else:
                     val_str = _render_hcl_recursive(v, variable_map, new_path, indent_level)
                     lines.append(f"{indent}{k} = {val_str}")
            else:
                # Leaf node value
                val_str = _render_hcl_recursive(v, variable_map, new_path, indent_level)
                lines.append(f"{indent}{k} = {val_str}")

    elif isinstance(node, list):
        # Literal list (e.g. security_groups = [...])
        rendered_items = [_render_hcl_recursive(x, variable_map, f"{current_path}[{i}]", indent_level) for i, x in enumerate(node)]
        return f"[{', '.join(rendered_items)}]"
    
    else:
        # Literal value
        return _hcl_value(node)

    return "\n".join(lines)

def _generate_smart_module_tf(ast1, diff_map):
    """
    Generates variables.tf and main.tf using the AST and Diff Map.
    """
    # 1. Prepare Variable Map (Path -> Variable Name)
    variable_map = {} # path -> var_name
    var_definitions = [] # Lines for variables.tf
    
    for path, details in diff_map.items():
        var_name = _sanitize_var_name(path)
        # Ensure unique variable names
        counter = 1
        original_name = var_name
        while var_name in variable_map.values():
            var_name = f"{original_name}_{counter}"
            counter += 1
            
        variable_map[path] = var_name
        
        # Build variable definition
        var_def = f'variable "{var_name}" {{\n'
        var_def += f'  description = "Refactored from {path}"\n'
        var_def += f'  type        = {details["type"]}\n'
        var_def += '}\n'
        var_definitions.append(var_def)

    # 2. Render main.tf (The common code)
    # We use AST1 as the "Skeleton" and inject vars into it
    main_tf_content = _render_hcl_recursive(ast1, variable_map)

    return "\n".join(var_definitions), main_tf_content, variable_map

def _generate_smart_module_call(module_name, diff_map, variable_map, specific_ast_values):
    """
    Generates the module usage block.
    specific_ast_values: 'val1' (left file) or 'val2' (right file) to pick specific values.
    """
    call_lines = [f'module "{module_name}" {{', f'  source = "./modules/{module_name}"']
    
    for path, var_name in variable_map.items():
        # Get the specific value for this file instance
        if specific_ast_values == 'left':
            val = diff_map[path]['val1']
        else:
            val = diff_map[path]['val2']
            
        call_lines.append(f'  {var_name} = {_hcl_value(val)}')

    call_lines.append('}')
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
