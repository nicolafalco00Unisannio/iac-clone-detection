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
    files = find_iac_files(root_dir, limit)
    logging.info(f"Found {len(files)} files. Starting parsing and bucketing...")
    
    buckets = defaultdict(list)
    skipped = 0
    
    # 1. Parsing & Bucketing Phase
    for path in files:
        data = parse_file(path)
        if data is None: continue
        
        tree = to_zss_tree(data)
        
        # --- NUOVO FILTRO ---
        # Se l'albero è troppo piccolo (es. < 15 nodi), è boilerplate. Ignoralo.
        # Il tuo esempio della variabile "config" avrà circa 4-5 nodi.
        if count_nodes(tree) < 100: 
            continue 
        # --------------------

        sig = get_ast_signature(data)
        buckets[sig].append((path, tree))
        
    logging.info(f"Parsing complete. Skipped {skipped} files.")
    logging.info(f"Created {len(buckets)} distinct buckets based on structure.")
    
    # Filtriamo bucket con meno di 2 file (nessun clone possibile)
    active_buckets = {k: v for k, v in buckets.items() if len(v) > 1}
    logging.info(f"Active buckets to process: {len(active_buckets)}")

    clone_pairs = []
    
    # 2. Comparison Phase (Parallelizzata)
    # Calcoliamo il numero totale di task per la progress bar (opzionale)
    total_comparisons = sum(len(list(combinations(v, 2))) for v in active_buckets.values())
    logging.info(f"Estimated comparisons required: {total_comparisons} (instead of classic N^2)")
    
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        
        for sig, items in active_buckets.items():
            # Genera coppie SOLO all'interno dello stesso bucket
            pairs = combinations(items, 2)
            
            for (p1, t1), (p2, t2) in pairs:
                # Se sono lo stesso file (es. symlink o errore path), salta
                if p1 == p2: continue
                
                futures.append(executor.submit(compute_distance_task, (p1, t1, p2, t2, threshold)))
        
        # Raccolta risultati man mano che finiscono
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                clone_pairs.append(res)
                
    logging.info(f"Detection complete. Found {len(clone_pairs)} clone pairs.")
    return clone_pairs