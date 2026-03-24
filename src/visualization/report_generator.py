"""
Comprehensive HTML report generation.
"""

from src.core.parser import parse_file
from src.analysis.refactoring import (
    _generate_smart_module_tf,
    _generate_smart_module_call,
    _generate_module_outputs,
    _rewrite_consumer_hcl,
    _generate_tfvars_bundle,
    _generate_wrapper_module_suggestion,
)
from src.analysis.diff_analyzer import _identify_param_differences, classify_clone_type, get_clone_statistics

import difflib
import webbrowser
from pathlib import Path
from itertools import combinations
import hashlib
import re
import os

def _tfvars_name_for(path: Path) -> str:
    """
    Make tfvars filenames unique even when both files are named main.tf
    and sit in folders with the same name (e.g., envA/webserver-cluster/main.tf
    vs envB/webserver-cluster/main.tf).

    Example: webserver-cluster__main__a1b2c3d4.tfvars
    """
    folder = path.parent.name or "root"
    h = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{folder}__{path.stem}__{h}.tfvars"

def _tfvars_has_assignments(tfvars_text: str) -> bool:
    """
    True if tfvars contains at least one non-comment assignment like `x = ...`.
    """
    for line in (tfvars_text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if re.search(r"\S\s*=\s*\S", s):
            return True
    return False


def _extract_output_names_from_file(outputs_tf_path: Path):
    """Extract Terraform output names from an outputs.tf file."""
    try:
        text = outputs_tf_path.read_text(encoding="utf-8")
    except OSError:
        return []

    return re.findall(r'^\s*output\s+"([^"]+)"\s*\{', text, flags=re.MULTILINE)


def _extract_output_names_from_module_dir(module_dir: Path):
    """Extract Terraform output names from all .tf files in a module directory."""
    output_names = set()
    for tf_path in sorted(module_dir.glob("*.tf")):
        try:
            text = tf_path.read_text(encoding="utf-8")
        except OSError:
            continue
        output_names.update(
            re.findall(r'^\s*output\s+"([^"]+)"\s*\{', text, flags=re.MULTILINE)
        )
    return sorted(output_names)


def _count_top_level_blocks(ast, block_name: str) -> int:
    """Count top-level Terraform blocks of a given type inside a parsed AST."""
    if not isinstance(ast, dict):
        return 0

    blocks = ast.get(block_name, [])
    if not isinstance(blocks, list):
        return 0

    total = 0
    for item in blocks:
        if not isinstance(item, dict):
            continue
        for _block_type, named_blocks in item.items():
            if isinstance(named_blocks, dict):
                total += len(named_blocks)
    return total


def _looks_like_wrapper_module(ast) -> bool:
    """Heuristic: wrapper modules usually have module blocks but no resources/data."""
    module_count = _count_top_level_blocks(ast, "module")
    resource_count = _count_top_level_blocks(ast, "resource")
    data_count = _count_top_level_blocks(ast, "data")
    return module_count > 0 and resource_count == 0 and data_count == 0


def _choose_canonical_and_wrapper(path1_obj: Path, path2_obj: Path, ast1, ast2):
    """Choose canonical implementation and duplicate wrapper side deterministically."""
    ast1_is_wrapper = _looks_like_wrapper_module(ast1)
    ast2_is_wrapper = _looks_like_wrapper_module(ast2)

    if ast1_is_wrapper and not ast2_is_wrapper:
        return (path2_obj, ast2), (path1_obj, ast1)
    if ast2_is_wrapper and not ast1_is_wrapper:
        return (path1_obj, ast1), (path2_obj, ast2)

    # Stable fallback for equally-structured modules.
    return (path1_obj, ast1), (path2_obj, ast2)

def generate_comprehensive_report(clone_pairs, clone_groups, output_filename="clone_report.html"):
    """
    Generates a comprehensive HTML report with all visualizations:
    - Overview statistics
    - Interactive clone graph (embedded)
    - Side-by-side diffs
    - Refactoring suggestions
    """
    if not clone_pairs and not clone_groups:
        print("No clones to report.")
        return

    html_parts = [
        '<!DOCTYPE html><html><head><meta charset="UTF-8">',
        '<title>Clone Detection Report</title>',
        '<style>',
        '* { margin: 0; padding: 0; box-sizing: border-box; }',
        'body { font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif; background: #f5f5f5; color: #333; }',
        'header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 2rem; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }',
        'header h1 { font-size: 2.5rem; margin-bottom: 0.5rem; }',
        'header p { font-size: 1.1rem; opacity: 0.9; }',
        '.container { max-width: 1400px; margin: 0 auto; padding: 2rem; }',
        '.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }',
        '.stat-card { background: white; padding: 1.5rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); text-align: center; }',
        '.stat-card h3 { color: #667eea; font-size: 2rem; margin-bottom: 0.5rem; }',
        '.stat-card p { color: #666; font-size: 0.9rem; }',
        'nav { background: white; padding: 1rem; border-radius: 8px; margin-bottom: 2rem; box-shadow: 0 2px 8px rgba(0,0,0,0.1); position: sticky; top: 20px; z-index: 100; }',
        'nav a { color: #667eea; text-decoration: none; padding: 0.5rem 1rem; margin: 0 0.25rem; border-radius: 4px; transition: background 0.3s; display: inline-block; }',
        'nav a:hover { background: #f0f0f0; }',
        '.section { background: white; padding: 2rem; margin-bottom: 2rem; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }',
        '.section h2 { color: #667eea; margin-bottom: 1.5rem; padding-bottom: 0.5rem; border-bottom: 2px solid #667eea; }',
        '.clone-group { background: #f9f9f9; padding: 1.5rem; margin-bottom: 1.5rem; border-radius: 8px; border-left: 4px solid #667eea; }',
        '.clone-group h3 { color: #764ba2; margin-bottom: 1rem; }',
        '.file-list { background: white; padding: 1rem; border-radius: 4px; margin-bottom: 1rem; }',
        '.file-list li { padding: 0.5rem; border-bottom: 1px solid #eee; list-style-position: inside; }',
        '.file-list li:last-child { border-bottom: none; }',
        'table.diff { font-family: "Courier New", monospace; font-size: 0.85rem; width: 100%; border: 1px solid #ddd; margin: 1rem 0; }',
        'table.diff td { padding: 0.25rem 0.5rem; white-space: pre-wrap; word-wrap: break-word; }',
        '.diff_header { background-color: #667eea !important; color: white !important; font-weight: bold; }',
        '.diff_next { background-color: #e0e0e0; }',
        '.diff_add { background-color: #d4edda; }',
        '.diff_chg { background-color: #fff3cd; }',
        '.diff_sub { background-color: #f8d7da; }',
        'details.diff-details { background: #fff; border: 1px solid #dcdcdc; border-radius: 6px; margin: 0.75rem 0; overflow: hidden; }',
        'details.diff-details summary { cursor: pointer; font-weight: 600; color: #444; padding: 0.75rem 1rem; background: #f2f4f8; }',
        'details.diff-details summary:hover { background: #e9edf5; }',
        '.diff-content { padding: 0.5rem 1rem 1rem 1rem; }',
        'pre { background: #f4f4f4; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.9rem; }',
        'code { background: #f4f4f4; padding: 0.2rem 0.4rem; border-radius: 3px; font-family: "Courier New", monospace; }',
        'details.refactoring-details { background: #e7f3ff; border: 1px solid #b3d7ff; border-radius: 4px; padding: 0.5rem; margin-top: 1rem; }',
        'details.refactoring-details summary { cursor: pointer; font-weight: bold; color: #0056b3; outline: none; padding: 0.5rem; }',
        'details.refactoring-details summary:hover { background-color: #d0e7ff; border-radius: 4px; }',
        '.refactoring-content { padding: 1rem; border-top: 1px solid #b3d7ff; margin-top: 0.5rem; background: white; border-radius: 0 0 4px 4px; }',
        'footer { text-align: center; padding: 2rem; color: #666; font-size: 0.9rem; }',
        '</style>',
        '</head><body>',
        '<header>',
        '<div class="container">',
        '<h1> Clone Detection Report</h1>',
        '</div>',
        '</header>',
        '<div class="container">'
    ]

    # Statistics section
    total_files = len(set([p for pair in clone_pairs for p in [pair[0], pair[1]]]))
    total_groups = len(clone_groups)
    total_pairs = len(clone_pairs)
    
    type_stats = get_clone_statistics(clone_pairs)

    html_parts.extend([
        '<div class="stats">',
        '<div class="stat-card"><h3>{}</h3><p>Clone Groups</p></div>'.format(total_groups),
        '<div class="stat-card"><h3>{}</h3><p>Clone Pairs</p></div>'.format(total_pairs),
        '<div class="stat-card"><h3>{}</h3><p>Files Involved</p></div>'.format(total_files),
        '</div>'
    ])
    
    # Detailed Type Stats
    html_parts.extend([
        '<div class="stats">',
        '<div class="stat-card"><h3 style="color:#28a745">{}</h3><p>Type 1 (Exact)</p></div>'.format(type_stats.get("Type 1 (Exact Clone)", 0)),
        '<div class="stat-card"><h3 style="color:#ffc107">{}</h3><p>Type 2 (Param)</p></div>'.format(type_stats.get("Type 2 (Parameterized Clone)", 0)),
        '<div class="stat-card"><h3 style="color:#dc3545">{}</h3><p>Type 3 (Near-miss)</p></div>'.format(type_stats.get("Type 3 (Near-miss Clone)", 0)),
        '</div>'
    ])

    # Navigation
    html_parts.extend([
        '<nav>',
        '<a href="#diffs"> Code Diffs & Refactoring</a>',
        '</nav>'
    ])

    # Code Diffs Section
    html_parts.extend([
        '<div class="section" id="diffs">',
        '<h2> Code Comparisons & Refactoring Suggestions</h2>'
    ])

    html_diff = difflib.HtmlDiff(tabsize=4, wrapcolumn=50)
    for i, group in enumerate(clone_groups):
        paths = sorted(list(group))
        
        # Determine group type dynamically based on the first pair
        # (Assuming transitivity: if A~B is Type 2, and B~C is Type 2, group is likely Type 2)
        group_type = "Unknown"
        group_max_dist = 0
        
        if len(paths) >= 2:
            p1, p2 = paths[0], paths[1]
            
            # Find the specific distance for this pair
            dist = 0
            for start, end, d in clone_pairs:
                if (start == p1 and end == p2) or (start == p2 and end == p1):
                    dist = d
                    break
            
            group_max_dist = dist
            
            # Parse only ONCE here for classification
            try:
                ast1 = parse_file(p1)
                ast2 = parse_file(p2)
                group_type = classify_clone_type(dist, ast1, ast2)
            except OSError:
                group_type = classify_clone_type(dist) # Fallback

        html_parts.append('<div class="clone-group">')
        html_parts.append(f'<h3>Clone Group {i+1} <span style="font-size:0.6em; color:#666; border:1px solid #ccc; padding:2px 6px; border-radius:4px; vertical-align:middle; margin-left:10px;">{group_type}</span></h3>')
        html_parts.append('<ul class="file-list">')
        for path in sorted(list(group)):
            html_parts.append(f'<li>{path}</li>')
        html_parts.append('</ul>')
        
        for path1, path2 in combinations(sorted(list(group)), 2):
            try:
                path1_obj = Path(path1)
                path2_obj = Path(path2)

                with open(path1_obj, 'r', encoding='utf-8') as f1, open(path2_obj, 'r', encoding='utf-8') as f2:
                    file1_lines = f1.readlines()
                    file2_lines = f2.readlines()
                
                diff_table = html_diff.make_table(
                    file1_lines,
                    file2_lines,
                    fromdesc=str(path1_obj.name),
                    todesc=str(path2_obj.name),
                    context=True,
                    numlines=2
                )
                html_parts.append(
                    f'<details class="diff-details"><summary>View diff: {path1_obj.name} ↔ {path2_obj.name}</summary><div class="diff-content">{diff_table}</div></details>'
                )
            except OSError as e:
                html_parts.append(f'<p> Could not generate diff: {e}</p>')
        
        # --- REFACTORING SUGGESTION LOGIC (Embedded) ---
        if len(group) >= 2:
            paths = sorted(list(group))
            path1, path2 = paths[0], paths[1]
            module_name = f"common_module_{i+1}"
            
            html_parts.append('<details class="refactoring-details"><summary>View Refactoring Suggestion</summary><div class="refactoring-content">')
            
            try:
                # Type 3 check: If structural differences are too large, skip automated refactoring
                if "Type 3" in group_type:
                    html_parts.append(
                        f'<h4>Manual Refactoring Recommended</h4>'
                        f'<p>These files are classified as <strong>Near-miss Clones</strong> (Tree Edit Distance: {group_max_dist}).</p>'
                        f'<p>They differ structurally (e.g., extra resources or blocks), making automated refactoring unsafe.</p>'
                        f'<p>Review the diffs above to identify the common core.</p>'
                        f'<p>Extract the common subset of resources into a module manually.</p>'
                    )
                else:
                    ast1 = parse_file(path1)
                    ast2 = parse_file(path2)

                    if ast1 and ast2:
                        diff_map = _identify_param_differences(ast1, ast2)

                        if not diff_map:
                            path1_obj = Path(path1)
                            path2_obj = Path(path2)
                            (canonical_path, _canonical_ast), (wrapper_path, wrapper_ast) = _choose_canonical_and_wrapper(
                                path1_obj,
                                path2_obj,
                                ast1,
                                ast2,
                            )
                            canonical_dir = canonical_path.parent
                            wrapper_dir = wrapper_path.parent
                            canonical_source = Path(
                                os.path.relpath(canonical_dir, wrapper_dir)
                            ).as_posix()
                            output_names = _extract_output_names_from_module_dir(canonical_dir)
                            wrapper = _generate_wrapper_module_suggestion(
                                wrapper_ast,
                                canonical_source=canonical_source,
                                module_instance_name="impl",
                                output_names=output_names,
                            )

                            html_parts.append(
                                f'<h4>Refactoring Strategy: Wrapper Module Delegation (Type 1)</h4>'
                                f'<p>Files <code>{path1_obj.name}</code> and <code>{path2_obj.name}</code> are structurally identical.</p>'
                                f'<p>Keep <code>{canonical_path}</code> as canonical implementation and turn <code>{wrapper_path}</code> into a wrapper.</p>'
                                f'<h5>Wrapper <code>variables.tf</code> (in duplicate location)</h5>'
                                f'<div class="code-block"><pre>{wrapper["wrapper_variables_tf"]}</pre></div>'
                                f'<h5>Wrapper <code>main.tf</code> (in duplicate location)</h5>'
                                f'<div class="code-block"><pre>{wrapper["wrapper_main_tf"]}</pre></div>'
                                f'<h5>Wrapper <code>outputs.tf</code></h5>'
                                f'<div class="code-block"><pre>{wrapper["wrapper_outputs_tf"]}</pre></div>'
                            )
                        
                        elif len(diff_map) < 2:
                             # TFVars Strategy
                            only_path = next(iter(diff_map.keys()))

                            bundle = _generate_tfvars_bundle(ast1, ast2, diff_map)
                            variables_tf = bundle["variables_tf"]
                            shared_main_tf = bundle["shared_main_tf"]
                            left_tfvars = bundle["left_tfvars"]
                            right_tfvars = bundle["right_tfvars"]
                            excluded = bundle.get("excluded_differences", {})
                            eligible_count = len(bundle.get("variable_map", {}))

                            left_tfvars_name = _tfvars_name_for(path1)
                            right_tfvars_name = _tfvars_name_for(path2)

                            if eligible_count == 0 and excluded:
                                excluded_html = "".join(
                                    f"<li><code>{p}</code>: {r}</li>" for p, r in sorted(excluded.items())
                                )
                                html_parts.append(f"""
                                    <h4>Manual Refactoring Recommended</h4>
                                    <p>Detected <strong>{len(diff_map)}</strong> differing parameter (<code>{only_path}</code>), but it cannot be safely parameterized via <code>.tfvars</code>.</p>
                                    <p>Use a literal value per file (or extract a shared local module while keeping this attribute fixed in each root module).</p>
                                    <h5>Excluded from .tfvars parameterization</h5>
                                    <ul>{excluded_html}</ul>
                                """)
                            else:
                                left_apply = f"terraform apply -var-file={left_tfvars_name}" if _tfvars_has_assignments(left_tfvars) else "terraform apply"
                                right_apply = f"terraform apply -var-file={right_tfvars_name}" if _tfvars_has_assignments(right_tfvars) else "terraform apply"

                                excluded_note = ""
                                if excluded:
                                    excluded_note = "".join(
                                        f"<li><code>{p}</code>: {r}</li>" for p, r in sorted(excluded.items())
                                    )
                                    excluded_note = (
                                        "<h5>Excluded from .tfvars parameterization</h5>"
                                        f"<ul>{excluded_note}</ul>"
                                    )

                                html_parts.append(f"""
                                    <h4>Refactoring Strategy: .tfvars Parameterization</h4>
                                    <p>Detected <strong>{len(diff_map)}</strong> differing parameter (<code>{only_path}</code>).</p>

                                    <h5>Generated <code>variables.tf</code></h5>
                                    <div class="code-block"><pre>{variables_tf}</pre></div>

                                    <h5>Canonical Shared <code>main.tf</code></h5>
                                    <div class="code-block"><pre>{shared_main_tf}</pre></div>

                                    <h5>Generated <code>{left_tfvars_name}</code></h5>
                                    <div class="code-block"><pre>{left_tfvars}</pre></div>

                                    <h5>Generated <code>{right_tfvars_name}</code></h5>
                                    <div class="code-block"><pre>{right_tfvars}</pre></div>

                                    {excluded_note}

                                    <h5>How to apply</h5>
                                    <ul>
                                        <li>Use the shared <code>main.tf</code> template in both locations.</li>
                                        <li>Apply left: <code>{left_apply}</code></li>
                                        <li>Apply right: <code>{right_apply}</code></li>
                                    </ul>
                                """)

                                if bundle.get("template_equal"):
                                    path1_obj = Path(path1)
                                    path2_obj = Path(path2)
                                    (canonical_path, _canonical_ast), (wrapper_path, wrapper_ast) = _choose_canonical_and_wrapper(
                                        path1_obj,
                                        path2_obj,
                                        ast1,
                                        ast2,
                                    )
                                    canonical_dir = canonical_path.parent
                                    wrapper_dir = wrapper_path.parent
                                    canonical_source = Path(
                                        os.path.relpath(canonical_dir, wrapper_dir)
                                    ).as_posix()
                                    output_names = _extract_output_names_from_module_dir(canonical_dir)
                                    wrapper = _generate_wrapper_module_suggestion(
                                        wrapper_ast,
                                        canonical_source=canonical_source,
                                        module_instance_name="impl",
                                        output_names=output_names,
                                    )

                                    html_parts.append(f"""
                                        <h4>Follow-up Strategy: Wrapper Module Delegation</h4>
                                        <p>After .tfvars normalization, both templates are identical (<strong>Type 1</strong>).</p>
                                        <p>Keep one canonical implementation and replace the other with a wrapper module.</p>

                                        <h5>Wrapper <code>main.tf</code> (in duplicate location)</h5>
                                        <div class="code-block"><pre>{wrapper["wrapper_main_tf"]}</pre></div>

                                        <h5>Wrapper <code>outputs.tf</code></h5>
                                        <div class="code-block"><pre>{wrapper["wrapper_outputs_tf"]}</pre></div>
                                    """)

                        else:
                            # Module Strategy
                            path1_obj = Path(path1)
                            path2_obj = Path(path2)
                            var_tf, main_tf, var_map, passthrough_vars = _generate_smart_module_tf(ast1, diff_map)
                            call_1 = _generate_smart_module_call(module_name, diff_map, var_map, "left", passthrough_vars)
                            call_2 = _generate_smart_module_call(module_name, diff_map, var_map, "right", passthrough_vars)
                            consumer_candidates = []

                            for base_path in {path1_obj.parent, path2_obj.parent}:
                                for tf_path in sorted(base_path.glob("*.tf")):
                                    if tf_path in {path1_obj, path2_obj}:
                                        continue
                                    try:
                                        consumer_candidates.append((tf_path, tf_path.read_text(encoding="utf-8")))
                                    except OSError:
                                        continue

                            outputs_tf, ref_output_map = _generate_module_outputs(
                                ast1,
                                [text for _, text in consumer_candidates],
                            )

                            rewritten_consumers = []
                            for consumer_path, consumer_text in consumer_candidates:
                                rewritten_text, replacements = _rewrite_consumer_hcl(
                                    consumer_text,
                                    ref_output_map,
                                    module_name,
                                )
                                if replacements:
                                    rewritten_consumers.append((consumer_path, rewritten_text))

                            html_parts.append(f"""
                                <h4>Refactoring Strategy: Module Extraction</h4>
                                <p>Detected <strong>{len(diff_map)}</strong> differing parameters.</p>

                                <h5>Proposed New Module Structure (<code>./modules/{module_name}</code>)</h5>
                                <div class="code-container">
                                    <div class="code-section">
                                        <h5>variables.tf</h5>
                                        <div class="code-block"><pre>{var_tf}</pre></div>
                                    </div>
                                    <div class="code-section">
                                        <h5>main.tf (Abstracted Logic)</h5>
                                        <div class="code-block"><pre>{main_tf}</pre></div>
                                    </div>
                                    <div class="code-section">
                                        <h5>outputs.tf</h5>
                                        <div class="code-block"><pre>{outputs_tf}</pre></div>
                                    </div>
                                </div>

                                <h5>Replacement Code</h5>
                                <div class="code-container">
                                    <div class="code-section">
                                        <h5>Replaces original code in <code>{path1_obj.name}</code></h5>
                                        <div class="code-block"><pre>{call_1}</pre></div>
                                    </div>
                                    <div class="code-section">
                                        <h5>Replaces original code in <code>{path2_obj.name}</code></h5>
                                        <div class="code-block"><pre>{call_2}</pre></div>
                                    </div>
                                </div>
                            """)

                            if rewritten_consumers:
                                html_parts.append('<h5>Updated Consumer Files</h5>')
                                for consumer_path, rewritten_text in rewritten_consumers:
                                    html_parts.append(
                                        f'<div class="code-section"><h5><code>{consumer_path.name}</code></h5>'
                                        f'<div class="code-block"><pre>{rewritten_text}</pre></div></div>'
                                    )
                    else:
                        html_parts.append('<p>Could not parse files for refactoring analysis.</p>')
            
            except (OSError, ValueError, TypeError, KeyError) as e:
                html_parts.append(f'<p>Error parsing or analyzing ASTs for refactoring: {e}</p>')

            html_parts.append('</div></details>')
        
        html_parts.append('</div>')
    
    html_parts.append('</div>') # Close container

    # Write the file
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))

    print(f"Comprehensive report generated: {output_filename}")
    webbrowser.open(f"file://{Path(output_filename).resolve()}")
