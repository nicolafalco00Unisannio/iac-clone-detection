"""
CLI entry point for clone detection.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import networkx as nx
import time
import logging
from src.detectors.zss_detector import detect_clones_smart
from src.visualization.report_generator import generate_comprehensive_report

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    parser = argparse.ArgumentParser(description='IaC Clone Detector')
    parser.add_argument('--root_dir', default='C:/Users/Falco/Documents/Università/EQS/Materiale/TerraDS', help='Root directory to scan')
    parser.add_argument('--limit', type=int, default=1000, help='Max files to process')
    parser.add_argument('--threshold', type=int, default=5, help='Distance threshold')
    parser.add_argument('--output', default='clone_report.html', help='Output report filename')
    parser.add_argument('--per_project', action='store_true', help='Analyze each immediate subdirectory as a project and aggregate into one report')
    parser.add_argument('--project_limit', type=int, default=None, help='Max number of projects to analyze when using --per_project')
    
    args = parser.parse_args()
    
    if args.per_project:
        root = Path(args.root_dir)
        project_dirs = [p for p in root.iterdir() if p.is_dir()]
        if args.project_limit:
            project_dirs = project_dirs[:args.project_limit]
        
        total_projects = len(project_dirs)
        logging.info(f"Starting analysis on {total_projects} projects.")
        
        all_clone_pairs = []
        all_clone_groups = []
        
        start_time = time.time()

        for i, project_dir in enumerate(project_dirs, 1):
            logging.info(f"[{i}/{total_projects}] Analyzing: {project_dir.name}...")
            
            clone_pairs = detect_clones_smart(str(project_dir), args.limit, args.threshold)
            
            if clone_pairs:
                clone_groups = list(nx.connected_components(nx.Graph([(p1, p2) for p1, p2, _ in clone_pairs])))
                all_clone_pairs.extend(clone_pairs)
                all_clone_groups.extend(clone_groups)
                logging.info(f"   -> Found {len(clone_pairs)} clones in {project_dir.name}")
            
            elapsed = time.time() - start_time
            avg_time = elapsed / i
            eta = (total_projects - i) * avg_time
            logging.info(f"   -> Elapsed: {elapsed:.1f}s | ETA: {eta:.1f}s")
        
        logging.info(f"Analysis complete. Generating report for {len(all_clone_pairs)} total pairs...")
        generate_comprehensive_report(all_clone_pairs, all_clone_groups, args.output)
    else:
        # Detect clones for entire root
        clone_pairs = detect_clones_smart(args.root_dir, args.limit, args.threshold)
        
        # Build clone groups
        clone_groups = list(nx.connected_components(nx.Graph([(p1, p2) for p1, p2, _ in clone_pairs])))
        
        # Generate report
        generate_comprehensive_report(clone_pairs, clone_groups, args.output)

if __name__ == "__main__":
    main()