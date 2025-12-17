"""
CLI entry point for clone detection.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import networkx as nx
from src.detectors.zss_detector import detect_clones_smart
from src.visualization.report_generator import generate_comprehensive_report



def main():
    parser = argparse.ArgumentParser(description='IaC Clone Detector')
    parser.add_argument('--root_dir', default='C:/Users/Falco/Documents/Università/EQS/Materiale/TerraDS', help='Root directory to scan')
    parser.add_argument('--limit', type=int, default=1000, help='Max files to process')
    parser.add_argument('--threshold', type=int, default=5, help='Distance threshold')
    parser.add_argument('--output', default='clone_report.html', help='Output report filename')
    
    args = parser.parse_args()
    
    # Detect clones
    clone_pairs = detect_clones_smart(args.root_dir, args.limit, args.threshold)
    
    # Build clone groups
    clone_groups = list(nx.connected_components(nx.Graph([(p1, p2) for p1, p2, _ in clone_pairs])))
    
    # Generate report
    generate_comprehensive_report(clone_pairs, clone_groups, args.output)

if __name__ == "__main__":
    main()