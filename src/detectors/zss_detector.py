"""
Smart bucketing + parallel ZSS detection.
"""

from src.core.file_finder import find_iac_files
from src.core.parser import parse_file
from src.core.ast_converter import to_zss_tree, count_nodes
from src.detectors.detector_utils import get_ast_signature, compute_distance_task

import concurrent.futures
import logging
from collections import defaultdict
from itertools import combinations

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def detect_clones_smart(root_dir, limit, threshold=5, max_workers=None):
    logging.debug(f"Finding files in {root_dir} with limit {limit}.")
    files = find_iac_files(root_dir, limit)
    logging.debug(f"Found {len(files)} files. Starting parsing and bucketing...")
    
    buckets = defaultdict(list)
    skipped = 0
    
    # 1. Parsing & Bucketing Phase
    for path in files:
        data = parse_file(path)
        if data is None: 
            continue
        
        tree = to_zss_tree(data)
        size = count_nodes(tree)
        
        # Se l'albero è troppo piccolo (es. < 100 nodi), è boilerplate.
        if size < 100: 
            continue 
        # --------------------

        sig = get_ast_signature(data)
        buckets[sig].append((path, tree, size))
        
    logging.debug(f"Parsing complete. Skipped {skipped} files.")
    logging.debug(f"Created {len(buckets)} distinct buckets based on structure.")
    
    # Filtriamo bucket con meno di 2 file (nessun clone possibile)
    active_buckets = {k: v for k, v in buckets.items() if len(v) > 1}
    logging.debug(f"Active buckets to process: {len(active_buckets)}")

    clone_pairs = []
    
    # 2. Comparison Phase (Parallelizzata)
    total_comparisons = sum(len(list(combinations(v, 2))) for v in active_buckets.values())
    logging.debug(f"Estimated comparisons required: {total_comparisons}.")
    
    def task_iter():
        for sig, items in active_buckets.items():
            for (p1, t1, s1), (p2, t2, s2) in combinations(items, 2):
                if p1 == p2:
                    continue
                # TED lower bound: distance >= |size1 - size2|
                if abs(s1 - s2) > threshold:
                    continue
                yield (p1, t1, p2, t2, threshold)

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        for res in executor.map(compute_distance_task, task_iter(), chunksize=50):
            if res:
                clone_pairs.append(res)
                
    logging.debug(f"Detection complete. Found {len(clone_pairs)} clone pairs.")
    return clone_pairs