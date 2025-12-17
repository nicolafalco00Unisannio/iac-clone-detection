"""
AST comparison and difference identification.
"""

def _find_ast_diff(d1, d2, path=""):
    """Helper to find differing values in two ASTs (dicts)."""
    diffs = set()
    # Check keys in d1 against d2
    for k in d1:
        p = f"{path}.{k}" if path else k
        if k not in d2:
            diffs.add(f"Key '{p}' only in first file.")
            continue
        
        v1, v2 = d1[k], d2[k]
        if isinstance(v1, dict) and isinstance(v2, dict):
            diffs.update(_find_ast_diff(v1, v2, path=p))
        elif isinstance(v1, list) and isinstance(v2, list):
            if len(v1) != len(v2):
                diffs.add(f"List length differs at '{p}' ({len(v1)} vs {len(v2)})")
            else:
                # Iterate through list items
                for i, (item1, item2) in enumerate(zip(v1, v2)):
                    item_path = f"{p}[{i}]"
                    if isinstance(item1, dict) and isinstance(item2, dict):
                        diffs.update(_find_ast_diff(item1, item2, path=item_path))
                    elif item1 != item2:
                        diffs.add(f"Value differs at '{item_path}': ('{item1}' vs '{item2}')")
        elif v1 != v2:
            diffs.add(f"Value differs at '{p}': ('{v1}' vs '{v2}')")

    # Check for keys in d2 that are not in d1
    for k in d2:
        p = f"{path}.{k}" if path else k
        if k not in d1:
            diffs.add(f"Key '{p}' only in second file.")
            
    return diffs

def _is_variable_candidate(value):
    """Determines if a value is a primitive that can be turned into a variable."""
    return isinstance(value, (str, int, float, bool))

def _infer_type(value):
    """Infers the Terraform type string."""
    if isinstance(value, bool): return "bool"
    if isinstance(value, int): return "number"
    if isinstance(value, float): return "number"
    if isinstance(value, list): return "list(any)"
    return "string"

def _identify_param_differences(ast1, ast2, current_path=""):
    """
    Compare two ASTs structure-wise. 
    Returns a dict: { 'path.to.param': {'val1': v1, 'val2': v2, 'type': 'string'} }
    """
    diffs = {}
    
    # If types differ completely, we can't parameterize easily
    if type(ast1) != type(ast2):
        return {}

    if isinstance(ast1, dict):
        all_keys = set(ast1.keys()) | set(ast2.keys())
        for k in all_keys:
            new_path = f"{current_path}.{k}" if current_path else k
            if k not in ast1 or k not in ast2:
                # Structural difference (block missing). 
                # Complex to handle in simple refactoring, ignoring for now.
                continue 
            diffs.update(_identify_param_differences(ast1[k], ast2[k], new_path))
            
    elif isinstance(ast1, list):
        # Naive list comparison: assumed fixed order for clones
        for i, (item1, item2) in enumerate(zip(ast1, ast2)):
            new_path = f"{current_path}[{i}]"
            diffs.update(_identify_param_differences(item1, item2, new_path))
            
    else:
        # Leaf node (Primitive value)
        if ast1 != ast2 and _is_variable_candidate(ast1):
            diffs[current_path] = {
                'val1': ast1,
                'val2': ast2,
                'type': _infer_type(ast1)
            }
            
    return diffs

