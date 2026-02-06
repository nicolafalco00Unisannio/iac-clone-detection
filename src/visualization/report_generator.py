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
from src.analysis.diff_analyzer import _identify_param_differences

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
        'pre { background: #f4f4f4; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.9rem; }',
        'code { background: #f4f4f4; padding: 0.2rem 0.4rem; border-radius: 3px; font-family: "Courier New", monospace; }',
        '.refactoring { background: #e7f3ff; padding: 1rem; border-radius: 4px; margin: 1rem 0; border-left: 4px solid #2196F3; }',
        '.graph-container { width: 100%; height: 600px; border: 1px solid #ddd; border-radius: 4px; margin: 1rem 0; }',
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
    
    html_parts.extend([
        '<div class="stats">',
        '<div class="stat-card"><h3>{}</h3><p>Clone Groups</p></div>'.format(total_groups),
        '<div class="stat-card"><h3>{}</h3><p>Clone Pairs</p></div>'.format(total_pairs),
        '<div class="stat-card"><h3>{}</h3><p>Files Involved</p></div>'.format(total_files),
        '</div>'
    ])

    # Navigation
    html_parts.extend([
        '<nav>',
        '<a href="#graph"> Graph View</a>',
        '<a href="#diffs"> Code Diffs</a>',
        '<a href="#refactoring"> Refactoring</a>',
        '</nav>'
    ])

    # Generate the Pyvis network for embedding
    html_parts.append('<section id="graph" class="section"><h2>Clone Graph Visualization</h2>')
    
    graph_filename = _generate_clone_graph_html(clone_pairs)
    
    if graph_filename:
        html_parts.append(f"""
        <p>Click on nodes to view file paths. Edge thickness represents similarity (thicker = more similar).</p>
        <iframe src="{graph_filename}" width="100%" height="600" style="border: none;"></iframe>
        """)
    else:
        html_parts.append("<p>Not enough clone pairs found to generate a meaningful graph visualization.</p>")
        
    html_parts.append('</section>')

    # Code Diffs Section
    html_parts.extend([
        '<div class="section" id="diffs">',
        '<h2> Side-by-Side Code Comparisons</h2>'
    ])

    html_diff = difflib.HtmlDiff(tabsize=4, wrapcolumn=50)
    for i, group in enumerate(clone_groups):
        html_parts.append(f'<div class="clone-group">')
        html_parts.append(f'<h3>Clone Group {i+1}</h3>')
        html_parts.append('<ul class="file-list">')
        for path in sorted(list(group)):
            html_parts.append(f'<li>{path}</li>')
        html_parts.append('</ul>')
        
        for path1, path2 in combinations(sorted(list(group)), 2):
            try:
                with open(path1, 'r', encoding='utf-8') as f1, open(path2, 'r', encoding='utf-8') as f2:
                    file1_lines = f1.readlines()
                    file2_lines = f2.readlines()
                
                diff_table = html_diff.make_table(
                    file1_lines,
                    file2_lines,
                    fromdesc=str(path1.name),
                    todesc=str(path2.name),
                    context=True,
                    numlines=2
                )
                html_parts.append(diff_table)
            except Exception as e:
                html_parts.append(f'<p> Could not generate diff: {e}</p>')
        
        html_parts.append('</div>')
    
    html_parts.append('</div>')

# 4. Refactoring Suggestions (UPDATED SECTION)
    html_parts.append('<section id="refactoring" class="section"><h2>4. Refactoring Suggestions</h2>')

    if clone_groups:
        for i, group in enumerate(clone_groups):
            if len(group) < 2:
                continue

            paths = sorted(list(group))
            path1, path2 = paths[0], paths[1]
            module_name = f"common_module_{i+1}"

            try:
                ast1 = parse_file(path1)
                ast2 = parse_file(path2)
            except Exception as e:
                html_parts.append(f'<div class="refactoring-block"><h4>Error analyzing group {i+1}</h4><p>Failed to parse AST for file pair: {e}</p></div>')
                continue

            if ast1 and ast2:
                diff_map = _identify_param_differences(ast1, ast2)

                # If identical: suggest dedup
                if not diff_map:
                    html_parts.append(
                        f'<div class="refactoring-block"><h4>Refactoring Suggestion for Group {i+1}</h4>'
                        f'<p>Files {path1.name} and {path2.name} appear structurally identical. Recommend simple file deduplication.</p></div>'
                    )
                    continue

                # NEW: if only a tiny number of differing params, a module is usually not worth it
                if len(diff_map) < 2:
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

                    html_block = f"""
                    <div class="refactoring-block">
                        <h4>Refactoring Suggestion for Group {i+1} ({len(group)} files)</h4>
                        <p><strong>Prototype Files:</strong> <code>{path1.name}</code> and <code>{path2.name}</code>.
                        Detected <strong>{len(diff_map)}</strong> differing parameter (<code>{only_path}</code>).</p>

                        <p><strong>Automated refactor chosen:</strong> <code>.tfvars</code>-based parameterization.</p>

                        <h5> Generated <code>variables.tf</code></h5>
                        <div class="code-block"><pre>{variables_tf}</pre></div>

                        <h5> Updated <code>{path1.name}</code> (parameterized)</h5>
                        <div class="code-block"><pre>{left_main_tf}</pre></div>

                        <h5> Updated <code>{path2.name}</code> (parameterized)</h5>
                        <div class="code-block"><pre>{right_main_tf}</pre></div>

                        <h5> Generated <code>{left_tfvars_name}</code></h5>
                        <div class="code-block"><pre>{left_tfvars}</pre></div>

                        <h5> Generated <code>{right_tfvars_name}</code></h5>
                        <div class="code-block"><pre>{right_tfvars}</pre></div>

                        <h5>How to apply</h5>
                        <ul>
                            <li>Apply left: <code>{left_apply}</code></li>
                            <li>Apply right: <code>{right_apply}</code></li>
                        </ul>
                    </div>
                    """
                    html_parts.append(html_block)
                    continue

                # Generate module files (now also includes pass-through vars)
                var_tf, main_tf, var_map, passthrough_vars = _generate_smart_module_tf(ast1, diff_map)

                # Generate calls (now passes through existing var.* dependencies)
                call_1 = _generate_smart_module_call(module_name, diff_map, var_map, "left", passthrough_vars)
                call_2 = _generate_smart_module_call(module_name, diff_map, var_map, "right", passthrough_vars)

                # 3. Format into HTML
                html_block = f"""
                <div class="refactoring-block">
                    <h4>Refactoring Suggestion for Group {i+1} ({len(group)} files)</h4>
                    <p><strong>Prototype Files:</strong> <code>{path1.name}</code> and <code>{path2.name}</code>. Detected <strong>{len(diff_map)}</strong> parameters that differ.</p>

                    <h5> Proposed New Module Structure (<code>./modules/{module_name}</code>)</h5>
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

                    <h5> Replacement Code</h5>
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
                </div>
                """
                html_parts.append(html_block)
            else:
                html_parts.append(f'<div class="refactoring-block"><h4>Refactoring Suggestion for Group {i+1}</h4><p>Could not parse both files for structural analysis.</p></div>')

    else:
        html_parts.append("<p>No clone groups found to suggest refactoring.</p>")
        
    html_parts.append('</section>') # end section

    # ... (Closing HTML tags) ...
    html_parts.append('</div></body></html>')

    # Write the file
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))

    print(f"Comprehensive report generated: {output_filename}")
    webbrowser.open(f"file://{Path(output_filename).resolve()}")
