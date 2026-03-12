"""
Comprehensive HTML report generation.
"""

from src.core.parser import parse_file
from src.visualization.graph_viz import _generate_clone_graph_html
from src.analysis.refactoring import (
    _generate_smart_module_tf,
    _generate_smart_module_call,
    _generate_tfvars_refactor,
)
from src.analysis.diff_analyzer import _identify_param_differences, classify_clone_type, get_clone_statistics

import difflib
import webbrowser
from pathlib import Path
from itertools import combinations
import hashlib
import re

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
            except:
                group_type = classify_clone_type(dist) # Fallback

        html_parts.append(f'<div class="clone-group">')
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
            except Exception as e:
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
                            html_parts.append(
                                f'<h4>Simple Deduplication</h4>'
                                f'<p>Files {path1.name} and {path2.name} appear structurally identical. Recommend simple file deduplication.</p>'
                            )
                        
                        elif len(diff_map) < 2:
                             # TFVars Strategy
                            only_path = next(iter(diff_map.keys()))

                            (
                                variables_tf,
                                left_main_tf,
                                right_main_tf,
                                left_tfvars,
                                right_tfvars,
                                var_map,
                            ) = _generate_tfvars_refactor(ast1, ast2, diff_map)

                            left_tfvars_name = _tfvars_name_for(path1)
                            right_tfvars_name = _tfvars_name_for(path2)
                            
                            left_apply = f"terraform apply -var-file={left_tfvars_name}" if _tfvars_has_assignments(left_tfvars) else "terraform apply"
                            right_apply = f"terraform apply -var-file={right_tfvars_name}" if _tfvars_has_assignments(right_tfvars) else "terraform apply"

                            html_parts.append(f"""
                                <h4>Refactoring Strategy: .tfvars Parameterization</h4>
                                <p>Detected <strong>{len(diff_map)}</strong> differing parameter (<code>{only_path}</code>).</p>

                                <h5>Generated <code>variables.tf</code></h5>
                                <div class="code-block"><pre>{variables_tf}</pre></div>

                                <h5>Updated <code>{path1.name}</code></h5>
                                <div class="code-block"><pre>{left_main_tf}</pre></div>

                                <h5>Updated <code>{path2.name}</code></h5>
                                <div class="code-block"><pre>{right_main_tf}</pre></div>

                                <h5>Generated <code>{left_tfvars_name}</code></h5>
                                <div class="code-block"><pre>{left_tfvars}</pre></div>
                                
                                <h5>Generated <code>{right_tfvars_name}</code></h5>
                                <div class="code-block"><pre>{right_tfvars}</pre></div>

                                <h5>How to apply</h5>
                                <ul>
                                    <li>Apply left: <code>{left_apply}</code></li>
                                    <li>Apply right: <code>{right_apply}</code></li>
                                </ul>
                            """)

                        else:
                            # Module Strategy
                            var_tf, main_tf, var_map, passthrough_vars = _generate_smart_module_tf(ast1, diff_map)
                            call_1 = _generate_smart_module_call(module_name, diff_map, var_map, "left", passthrough_vars)
                            call_2 = _generate_smart_module_call(module_name, diff_map, var_map, "right", passthrough_vars)

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
                                </div>

                                <h5>Replacement Code</h5>
                                <div class="code-container">
                                    <div class="code-section">
                                        <h5>Replaces original code in <code>{path1.name}</code></h5>
                                        <div class="code-block"><pre>{call_1}</pre></div>
                                    </div>
                                    <div class="code-section">
                                        <h5>Replaces original code in <code>{path2.name}</code></h5>
                                        <div class="code-block"><pre>{call_2}</pre></div>
                                    </div>
                                </div>
                            """)
                    else:
                         html_parts.append(f'<p>Could not parse files for refactoring analysis.</p>')
            
            except Exception as e:
                html_parts.append(f'<p>Error parsing or analyzing ASTs for refactoring: {e}</p>')

            html_parts.append('</div></details>')
        
        html_parts.append('</div>')
    
    html_parts.append('</div>') # Close container

    # Write the file
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))

    print(f"Comprehensive report generated: {output_filename}")
    webbrowser.open(f"file://{Path(output_filename).resolve()}")
