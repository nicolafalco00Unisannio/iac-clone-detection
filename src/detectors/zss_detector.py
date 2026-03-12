"""
Smart bucketing + parallel ZSS detection.
"""

from src.core.file_finder import find_iac_files
from src.core.parser import parse_file
from src.core.ast_converter import to_zss_tree, count_nodes
from src.detectors.detector_utils import get_ast_signature, compute_distance_task

import concurrent.futures
import logging
import os
import time
from collections import defaultdict
from itertools import combinations

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def _terminate_pool_now(executor: concurrent.futures.ProcessPoolExecutor) -> None:
    """
    Hard-stop pool workers (needed for strict timeout behavior).
    Uses internal process handles; practical for Windows timeout enforcement.
    """
    processes = getattr(executor, "_processes", None) or {}
    for proc in processes.values():
        if proc.is_alive():
            proc.terminate()
    for proc in processes.values():
        proc.join(timeout=1)
    executor.shutdown(wait=False, cancel_futures=True)

def detect_clones_smart(root_dir, limit, threshold=5, max_workers=None, timeout_seconds=None):
    logging.debug(f"Finding files in {root_dir} with limit {limit}.")
    files = find_iac_files(root_dir, limit)
    logging.debug(f"Found {len(files)} files. Starting parsing and bucketing...")

    deadline = time.monotonic() + timeout_seconds if timeout_seconds else None

    def timed_out() -> bool:
        return deadline is not None and time.monotonic() >= deadline
    
    buckets = defaultdict(list)
    skipped = 0
    
    # 1. Parsing & Bucketing Phase
    for path in files:
        if timed_out():
            raise TimeoutError(f"Project analysis timed out after {timeout_seconds}s during parsing.")

        data = parse_file(path)
        if data is None: 
            continue
        
        tree = to_zss_tree(data)
        size = count_nodes(tree)
        
        # Se l'albero è troppo piccolo (es. < 100 nodi), è boilerplate.
        if size < 100: 
            continue 

        sig = get_ast_signature(data)
        buckets[sig].append((path, tree, size))
        
    logging.debug(f"Parsing complete. Skipped {skipped} files.")
    logging.debug(f"Created {len(buckets)} distinct buckets based on structure.")
    
    active_buckets = {k: v for k, v in buckets.items() if len(v) > 1}
    logging.debug(f"Active buckets to process: {len(active_buckets)}")

    clone_pairs = []
    
    total_comparisons = sum(len(list(combinations(v, 2))) for v in active_buckets.values())
    logging.debug(f"Estimated comparisons required: {total_comparisons}.")
    
    def task_iter():
        for _, items in active_buckets.items():
            for (p1, t1, s1), (p2, t2, s2) in combinations(items, 2):
                if p1 == p2:
                    continue
                if abs(s1 - s2) > threshold:
                    continue
                yield (p1, t1, p2, t2, threshold)

    executor = concurrent.futures.ProcessPoolExecutor(max_workers=max_workers)
    hit_timeout = False
    try:
        in_flight = set()
        tasks = task_iter()
        tasks_exhausted = False
        workers = max_workers or (os.cpu_count() or 1)
        max_in_flight = max(1, workers * 4)

        while True:
            while not tasks_exhausted and len(in_flight) < max_in_flight:
                if timed_out():
                    hit_timeout = True
                    break
                try:
                    task = next(tasks)
                except StopIteration:
                    tasks_exhausted = True
                    break
                in_flight.add(executor.submit(compute_distance_task, task))

            if hit_timeout:
                break

            if not in_flight:
                if tasks_exhausted:
                    break
                continue

            wait_timeout = None
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    hit_timeout = True
                    break
                wait_timeout = min(1.0, remaining)

            done, in_flight = concurrent.futures.wait(
                in_flight,
                timeout=wait_timeout,
                return_when=concurrent.futures.FIRST_COMPLETED
            )

            if not done:
                if timed_out():
                    hit_timeout = True
                continue

            for fut in done:
                try:
                    res = fut.result()
                    if res:
                        clone_pairs.append(res)
                except Exception as e:
                    logging.warning(f"Comparison task failed: {e}")

        if hit_timeout:
            raise TimeoutError(f"Project analysis timed out after {timeout_seconds}s during comparison.")

    finally:
        if hit_timeout:
            _terminate_pool_now(executor)
        else:
            executor.shutdown(wait=True)

    logging.debug(f"Detection complete. Found {len(clone_pairs)} clone pairs.")
    return clone_pairs