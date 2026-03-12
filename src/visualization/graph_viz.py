"""
Interactive graph visualization using NetworkX and Pyvis.
"""

import webbrowser
from pathlib import Path
import networkx as nx
from pyvis.network import Network

def _generate_clone_graph_html(clone_pairs, graph_filename="clone_graph.html"):
    """
    Generates an interactive clone graph visualization using NetworkX and Pyvis.
    Returns the path to the generated HTML file.
    """
    if not clone_pairs:
        return None

    # 1. Build NetworkX Graph
    G = nx.Graph()
    
    # clone_pairs is expected to be a list of tuples: [(path1, path2, distance), ...]
    for path1, path2, distance in clone_pairs:
        p1_name = path1.name
        p2_name = path2.name
        
        # Add nodes (files)
        G.add_node(p1_name, title=str(path1), group=1, size=15)
        G.add_node(p2_name, title=str(path2), group=1, size=15)
            
        # Add edge. Distance is inverted for value (smaller distance = stronger link/thicker edge)
        # We cap the distance value to make it visible
        edge_weight = max(1, 100 - distance*10) 
        G.add_edge(p1_name, p2_name, value=edge_weight, title=f"Distance: {distance:.2f}")

    # 2. Convert to Pyvis Network
    nt = Network(height="600px", width="100%", bgcolor="#222222", font_color="white", notebook=False)
    nt.from_nx(G)
    
    # 3. Save to HTML file
    nt.save_graph(graph_filename)
    
    return graph_filename

def visualize_clone_graph(clone_pairs, output_filename="clone_graph.html"):
    """
    Generates an interactive HTML graph of clone relationships.
    Writes the generated HTML using UTF-8 to avoid encoding errors on Windows.
    """
    if not clone_pairs:
        print("No clone pairs to visualize in a graph.")
        return

    net = Network(notebook=True, directed=False, cdn_resources='in_line')
    
    # Use NetworkX to handle graph properties like connected components (groups)
    G = nx.Graph()
    for path1, path2, distance in clone_pairs:
        G.add_edge(str(path1.name), str(path2.name), weight=distance, title=f"Distance: {distance}")

    # Assign a group ID to each component for coloring
    for i, component in enumerate(nx.connected_components(G)):
        for node in component:
            if node in G:
                G.nodes[node]['group'] = i

    net.from_nx(G)
    net.show_buttons(filter_=['physics'])

    # Generate the HTML and write it explicitly with UTF-8 encoding to avoid
    # UnicodeEncodeError on platforms that use a limited default encoding.
    try:
        html = net.generate_html()
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"Interactive graph saved to {output_filename}")
        webbrowser.open(f"file://{Path(output_filename).resolve()}")
    except Exception as e:
        print(f"Failed to generate or save interactive graph: {e}")
