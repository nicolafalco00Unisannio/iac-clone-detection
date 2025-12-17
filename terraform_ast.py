import hcl2
from zss import Node

# ------------------------------
#  Utility: Normalization helpers
# ------------------------------

def normalize_identifier(name):
    """
    Replace identifiers and variable/resource names with a canonical placeholder.
    """
    return "IDENTIFIER"

def normalize_literal(value):
    """
    Normalize literals to coarse types to avoid irrelevant differences.
    """
    if isinstance(value, bool):
        return "BOOL_LITERAL"
    if isinstance(value, int) or isinstance(value, float):
        return "NUM_LITERAL"
    if isinstance(value, str):
        return "STRING_LITERAL"
    return "LITERAL"

# ------------------------------
#  AST node builders
# ------------------------------

def make_node(label, children=None):
    """
    Create a ZSS-compatible node with children.
    """
    if children is None:
        children = []
    n = Node(label)
    for child in children:
        n.addkid(child)
    return n

# ------------------------------
#  Expression builder
# ------------------------------

def build_expr(expr):
    """
    Build an expression node with coarse-grained normalization.

    Terraform expression types vary:
    - literals
    - lists
    - dicts
    - expressions like '${var.foo}' parsed as strings
    """
    if isinstance(expr, (str, int, float, bool)):  # literals
        return make_node(normalize_literal(expr))

    if expr is None:
        return make_node("NULL")

    if isinstance(expr, list):  # list expressions
        children = [build_expr(e) for e in expr]
        return make_node("ListExpr", children)

    if isinstance(expr, dict):  # map/object expressions
        # Sort keys to normalize structure
        items = sorted(expr.items(), key=lambda x: x[0])
        children = [make_node(f"Key={k}", [build_expr(v)]) for k, v in items]
        return make_node("MapExpr", children)

    # Fallback generic node
    return make_node("Expr")

# ------------------------------
#  Attribute builder
# ------------------------------

def build_attribute(name, value):
    """
    Build Attribute(name, Expr) node.
    """
    return make_node(f"Attribute:{name}", [build_expr(value)])

# ------------------------------
#  Terraform Block builder
# ------------------------------

def build_block(block_type, labels, body_dict):
    """
    Build a Block node:
        Block
          ├── type
          ├── labels
          └── attributes + nested blocks
    """
    label_nodes = [make_node(f"Label:{l}") for l in labels]

    # Split attributes vs nested blocks
    attr_nodes = []
    nested_nodes = []

    for key, value in sorted(body_dict.items()):
        if isinstance(value, list) and value and isinstance(value[0], dict):
            # Nested block(s)
            for nested_block in value:
                nested_nodes.append(
                    build_nested_block(key, nested_block)
                )
        else:
            # Attribute
            attr_nodes.append(build_attribute(key, value))

    children = label_nodes + attr_nodes + nested_nodes
    return make_node(f"Block:{block_type}", children)

# ------------------------------
#  Nested block builder
# ------------------------------

def build_nested_block(blockname, body):
    """
    Nested block like:

    ingress {
      from_port = 80
      to_port   = 80
    }
    """
    attr_nodes = []
    for key, value in sorted(body.items()):
        attr_nodes.append(build_attribute(key, value))
    return make_node(f"NestedBlock:{blockname}", attr_nodes)

# ------------------------------
#  Terraform File → AST
# ------------------------------

def build_terraform_ast(text):
    """
    Parse Terraform source and build the canonical AST root.
    """
    parsed = hcl2.loads(text)
    root = make_node("TerraformFile")

    # For each top-level block:
    for block in parsed.get("resource", []):
        for rtype, instances in block.items():
            for name, body in instances.items():
                root.addkid(build_block("resource", [rtype, name], body))

    for block in parsed.get("data", []):
        for dtype, instances in block.items():
            for name, body in instances.items():
                root.addkid(build_block("data", [dtype, name], body))

    for block in parsed.get("module", []):
        for name, body in block.items():
            root.addkid(build_block("module", [name], body))

    for block in parsed.get("variable", []):
        for name, body in block.items():
            root.addkid(build_block("variable", [name], body))

    for block in parsed.get("output", []):
        for name, body in block.items():
            root.addkid(build_block("output", [name], body))

    for block in parsed.get("provider", []):
        for name, body in block.items():
            root.addkid(build_block("provider", [name], body))

    if "locals" in parsed:
        root.addkid(build_block("locals", [], parsed["locals"]))

    if "terraform" in parsed:
        root.addkid(build_block("terraform", [], parsed["terraform"]))

    return root
