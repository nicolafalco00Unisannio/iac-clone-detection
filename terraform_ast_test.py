from zss import simple_distance, Node
import terraform_ast

tf1 = """
resource "aws_s3_bucket" "example" {
  bucket = "mybucket"
  tags = {
    Environment = "dev"
    Project     = "clone-test"
  }
}
"""

tf2 = """
resource "aws_s3_bucket" "example" {
  bucket = "mybucket"
    tags = {
    Environment = "prod"
    Project     = "clone-test"
    Pippo       = "extra"
    }
}
"""

ast1 = terraform_ast.build_terraform_ast(tf1)
ast2 = terraform_ast.build_terraform_ast(tf2)


def print_tree(node, level=0):
    """Recursively prints the tree structure."""
    print('  ' * level + f'- {node.label}')
    for child in node.children:
        print_tree(child, level + 1)

print_tree(ast1)
print("\nAST Distance:", simple_distance(ast1, ast2))

#print(ast)                 # Print AST
