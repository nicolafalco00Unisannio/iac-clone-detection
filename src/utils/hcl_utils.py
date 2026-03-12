"""
HCL formatting utilities.
"""

def _sanitize_var_name(path):
    """Converts an AST path (resource.aws_instance.web.ami) into a variable name (ami)."""
    # Heuristic: try to use the last segment. If generic (e.g. 'name', 'tags'), prepend parent.
    parts = path.split('.')
    name = parts[-1]
    if name in ['name', 'tags', 'type', 'id', 'enabled'] and len(parts) > 1:
        return f"{parts[-2]}_{name}"
    return name

def _hcl_value(val):
    """Formats a Python value into an HCL string."""
    if isinstance(val, bool):
        return str(val).lower()
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        # Handle HEREDOC or multiline if necessary, strict quoting for now
        return f'"{val}"'
    if isinstance(val, list):
        items = [_hcl_value(x) for x in val]
        return f"[{', '.join(items)}]"
    return f'"{val}"' # Fallback
