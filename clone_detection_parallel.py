from pathlib import Path
import json
import hcl2
import yaml
from zss import Node, simple_distance
from itertools import combinations
import concurrent.futures
import difflib
import webbrowser
import networkx as nx


def find_iac_files(root):
    exts = ('.tf',)
    return [p for p in Path(root).rglob('*') if p.is_file() and p.suffix in exts]

def parse_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            if path.suffix == '.tf':
                return hcl2.load(f)
            elif path.suffix in ('.yaml', '.yml'):
                return yaml.safe_load(f)
            elif path.suffix == '.json':
                return json.load(f)
    except Exception as e:
        print(f"Failed to parse {path}: {e}")
        return None

def to_zss_tree(node, label='root'):
    if isinstance(node, dict):
        zss_node = Node(label)
        for k, v in sorted(node.items()):
            zss_node.addkid(to_zss_tree(v, label=k))
        return zss_node
    elif isinstance(node, list):
        zss_node = Node(label)
        for item in node:
            zss_node.addkid(to_zss_tree(item, label='item'))
        return zss_node
    else:
        return Node(str(type(node).__name__))

def compare_asts(args):
    path1, ast1, path2, ast2, threshold = args
    distance = simple_distance(ast1, ast2)
    if distance <= threshold:
        print(f"Found potential clone pair: ({path1.name}, {path2.name}) with distance {distance}")
        return (path1, path2, distance)
    return None

def detect_clones_zss(files, threshold=5):
    print("Parsing files and building ASTs...")
    asts = {}
    for path in files:
        ast_tree = parse_file(path)
        if ast_tree:
            asts[path] = to_zss_tree(ast_tree)

    pairs_to_compare = list(combinations(asts.items(), 2))
    print(f"Comparing {len(pairs_to_compare)} pairs in parallel...")

    clone_pairs = []
    with concurrent.futures.ProcessPoolExecutor() as executor:
        tasks = [(p1_item[0], p1_item[1], p2_item[0], p2_item[1], threshold) for p1_item, p2_item in pairs_to_compare]
        results = executor.map(compare_asts, tasks)
        clone_pairs = [result for result in results if result is not None]

    print("Parallel comparison finished.")
    return clone_pairs

def visualize_clones_html(clone_groups, output_filename="clone_diff_report.html"):
    """
    Generates an HTML file with side-by-side diffs for clone pairs.
    """
    if not clone_groups:
        print("No clones to visualize.")
        return

    html_parts = [
        '<html><head><title>Clone Diff Report</title>',
        '<style>body { font-family: sans-serif; } table { border-collapse: collapse; }',
        'td { padding: 2px; } .diff_header { background-color: #e0e0e0; }',
        'h1, h2 { padding: 10px; background-color: #f0f0f0; border-radius: 5px; }',
        '</style></head><body><h1>Clone Detection Report</h1>'
    ]

    # Use HtmlDiff for a side-by-side comparison
    html_diff = difflib.HtmlDiff(tabsize=4, wrapcolumn=80)

    for i, group in enumerate(clone_groups):
        html_parts.append(f"<h2>Clone Group {i+1}</h2>")
        for path1, path2 in combinations(sorted(list(group)), 2):
            try:
                with open(path1, 'r', encoding='utf-8') as f1, open(path2, 'r', encoding='utf-8') as f2:
                    file1_lines = f1.readlines()
                    file2_lines = f2.readlines()

                # Generate the HTML table for the diff
                diff_table = html_diff.make_table(
                    file1_lines,
                    file2_lines,
                    fromdesc=str(path1.name),
                    todesc=str(path2.name)
                )
                html_parts.append(diff_table)

            except Exception as e:
                html_parts.append(f"<p>Could not generate diff for {path1.name} and {path2.name}: {e}</p>")

    html_parts.append('</body></html>')

    # Write the final HTML file
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))

    print(f"HTML report generated: {output_filename}")
    # Open the report in the default web browser
    webbrowser.open(f"file://{Path(output_filename).resolve()}")


if __name__ == "__main__":
    root_dir = 'C:/Users/Falco/Documents/Università/EQS/terraform-examples/'
    iac_files = find_iac_files(root_dir)
    clone_pairs_with_distance = detect_clones_zss(iac_files, threshold=1)
    clone_groups_from_pairs = list(nx.connected_components(nx.Graph([(p1, p2) for p1, p2, _ in clone_pairs_with_distance])))
    visualize_clones_html(clone_groups_from_pairs)
    