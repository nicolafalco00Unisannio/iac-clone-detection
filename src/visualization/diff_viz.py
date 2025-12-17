"""
Text and HTML diff visualization.
"""

import difflib
import webbrowser
from pathlib import Path
from itertools import combinations

def visualize_clones_diff(clone_groups):
    """
    Generates a text-based diff for each pair of files in a clone group.
    """
    if not clone_groups:
        print("No clones to visualize.")
        return

    print(f"\n--- Visualizing {len(clone_groups)} Clone Groups ---")

    for i, group in enumerate(clone_groups):
        # Iterate over every pair of files in the clone group
        for path1, path2 in combinations(sorted(list(group)), 2):
            print(f"\n{'='*80}")
            print(f"Clone Group {i+1}: DIFF between '{path1.name}' and '{path2.name}'")
            print(f"{'='*80}")

            try:
                with open(path1, 'r', encoding='utf-8') as f1, open(path2, 'r', encoding='utf-8') as f2:
                    file1_lines = f1.readlines()
                    file2_lines = f2.readlines()

                # Generate and print the diff
                diff = difflib.unified_diff(
                    file1_lines,
                    file2_lines,
                    fromfile=str(path1),
                    tofile=str(path2),
                )
                for line in diff:
                    print(line, end='')

            except Exception as e:
                print(f"Could not generate diff for {path1.name} and {path2.name}: {e}")

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
    html_diff = difflib.HtmlDiff(tabsize=4, wrapcolumn=50)

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
