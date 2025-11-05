from pathlib import Path
import argparse
import json
import hashlib
import hcl2
import yaml

def find_iac_files(root):
    exts = ('.tf', '.yaml', '.yml', '.json')
    return [p for p in Path(root).rglob('*') if p.suffix in exts]

def parse_file(path):
    with open(path, 'r') as f:
        if path.suffix == '.tf':
            return hcl2.load(f)
        elif path.suffix in ('.yaml', '.yml'):
            return yaml.safe_load(f)
        elif path.suffix == '.json':
            return json.load(f)

def normalize(node):
    if isinstance(node, dict):
        return {k: normalize(v) for k, v in node.items() if k not in ("name", "id")}
    elif isinstance(node, list):
        return [normalize(x) for x in node]
    elif isinstance(node, (int, float, str)):
        return "CONST"  # Replace literal values
    else:
        return node


def structural_hash(ast_node):
    json_str = json.dumps(ast_node, sort_keys=True)
    return hashlib.sha256(json_str.encode()).hexdigest()


from collections import defaultdict

def detect_clones(files):
    hash_map = defaultdict(list)
    for path in files:
        ast_tree = parse_file(path)
        norm_tree = normalize(ast_tree)
        h = structural_hash(norm_tree)
        hash_map[h].append(path)
    return {h: paths for h, paths in hash_map.items() if len(paths) > 1}


def report(clones):
    for h, paths in clones.items():
        print(f"Clone group {h[:8]}: {len(paths)} files")
        for p in paths:
            print(f"  - {p}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect IaC file clones.")
    parser.add_argument("root_dir", nargs="?", default=".", help="Root directory to scan (default: current directory)")
    args = parser.parse_args()

    iac_files = find_iac_files(args.root_dir)
    clones = detect_clones(iac_files)
    report(clones)