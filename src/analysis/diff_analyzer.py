"""
AST comparison and difference identification.
"""

from src.core.parser import parse_file

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

def classify_clone_type(distance, ast1=None, ast2=None):
    """
    Classifies a clone pair based on Tree Edit Distance (TED) and Structural Analysis.
    
    Based on AST Clone Literature:
    - Type 1: Identical AST (TED=0).
    - Type 2: Isomorphic AST (Structure matches 1:1, only values differ).
              Rule: Edit Distance == Number of Value Changes.
    - Type 3: Structural differences (Insertions/Deletions/Gaps).
              Rule: Edit Distance > Number of Value Changes.
    """
    # 1. Exact Match
    if distance == 0:
        return "Type 1 (Exact Clone)"

    # 2. If we don't have ASTs, we can't verify Isomorphism. Fallback/Noise.
    if ast1 is None or ast2 is None:
        return "Type 3 (Near-miss Clone)"

    try:
        # Get parameter differences (values only)
        param_diffs = _identify_param_differences(ast1, ast2)
        num_param_changes = len(param_diffs)
        
        # STRICT ISOMORPHISM CHECK:
        # In our ZSS tree model, changing a value cost 1 operation.
        # If TED == param_changes, then NO structural nodes were added/removed.
        # The trees are isomorphic. -> Type 2.
        if distance == num_param_changes:
            return "Type 2 (Parameterized Clone)"
        
        # If we have extra edits (distance > params), it means structural changes occurred.
        # e.g., a resource block was added, or a list item removed. -> Type 3.
        return "Type 3 (Near-miss Clone)"
        
    except Exception:
        # Fallback
        return "Type 3 (Near-miss Clone)"

def get_clone_statistics(clone_pairs):
    """
    Aggregates statistics for a list of clone pairs.
    Now correctly parses ASTs to verify clone types using the strict literature definition,
    fixing the inaccuracy where Type 3 clones were miscounted as Type 2.
    """
    stats = {
        "Type 1 (Exact Clone)": 0,
        "Type 2 (Parameterized Clone)": 0,
        "Type 3 (Near-miss Clone)": 0
    }
    
    # Cache parsed ASTs to avoid re-parsing heavily used files
    ast_cache = {}

    def get_ast(path):
        if path not in ast_cache:
            ast_cache[path] = parse_file(path)
        return ast_cache[path]
    
    for item in clone_pairs:
        # Handle variations in tuple size (p1, p2, dist) vs (p1, t1, p2, t2, dist)
        if len(item) < 3: continue
        
        # Extract paths and distance
        if len(item) == 5:
            p1, _, p2, _, dist = item
        else:
            p1, p2, dist = item[0], item[1], item[-1]
            
        if dist == 0:
            stats["Type 1 (Exact Clone)"] += 1
            continue

        try:
            # Parse on demand to apply the Isomorphism Check
            ast1 = get_ast(p1)
            ast2 = get_ast(p2)
            c_type = classify_clone_type(dist, ast1, ast2)
            stats[c_type] += 1
        except Exception:
            # If parsing fails, use the safer Type 3 bucket
            stats["Type 3 (Near-miss Clone)"] += 1
            
    return stats