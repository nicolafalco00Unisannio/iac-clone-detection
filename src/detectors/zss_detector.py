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

MIN_TREE_NODES = 100
MAX_TREE_NODES = 500
SIZE_DIFF_RATIO_THRESHOLD = 0.20

def _terminate_pool_now(executor: concurrent.futures.ProcessPoolExecutor) -> None:
    """
    Hard-stop pool workers (needed for strict timeout behavior).
    Uses internal process handles; practical for Windows timeout enforcement.
    """
    processes = getattr(executor, "_processes", None) or {}
    for proc in processes.values():
        if proc.is_alive():
            # kill() is more reliable than terminate() for hard-stopping stuck workers on Windows.
            proc.kill()
    for proc in processes.values():
        proc.join(timeout=1)
    executor.shutdown(wait=False, cancel_futures=True)

def detect_clones_smart(
    root_dir,
    limit,
    threshold=5,
    max_workers=None,
    timeout_seconds=None,
    max_tree_nodes=MAX_TREE_NODES,
    size_diff_ratio_threshold=SIZE_DIFF_RATIO_THRESHOLD,
    progress_callback=None,
    checkpoint_interval_seconds=None,
):
    logging.debug("Finding files in %s with limit %s.", root_dir, limit)
    files = find_iac_files(root_dir, limit)
    logging.debug("Found %s files. Starting parsing and bucketing...", len(files))

    deadline = time.monotonic() + timeout_seconds if timeout_seconds else None

    def timed_out() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    last_progress_emit = 0.0
    files_processed = 0
    comparisons_completed = 0

    def emit_progress(phase, total_comparisons=0, force=False):
        nonlocal last_progress_emit
        if progress_callback is None:
            return

        now = time.monotonic()
        interval = checkpoint_interval_seconds or 0
        if not force and interval > 0 and (now - last_progress_emit) < interval:
            return

        progress_callback({
            "phase": phase,
            "root_dir": root_dir,
            "files_total": len(files),
            "files_processed": files_processed,
            "skipped_files": skipped,
            "bucket_count": len(buckets),
            "total_comparisons": total_comparisons,
            "comparisons_completed": comparisons_completed,
            "clone_pairs": list(clone_pairs),
        })
        last_progress_emit = now
    
    buckets = defaultdict(list)
    skipped = 0
    clone_pairs = []
    
    # 1. Parsing & Bucketing Phase
    for path in files:
        if timed_out():
            raise TimeoutError(f"Project analysis timed out after {timeout_seconds}s during parsing.")

        data = parse_file(path)
        files_processed += 1
        if data is None:
            skipped += 1
            emit_progress("parsing")
            continue
        
        tree = to_zss_tree(data)
        size = count_nodes(tree)
        
        # Skip boilerplate and avoid pathological ZSS costs on very large trees.
        if size < MIN_TREE_NODES:
            skipped += 1
            emit_progress("parsing")
            continue
        if max_tree_nodes is not None and size > max_tree_nodes:
            skipped += 1
            emit_progress("parsing")
            continue

        sig = get_ast_signature(data)
        buckets[sig].append((path, tree, size))
        emit_progress("parsing")
        
    logging.debug("Parsing complete. Skipped %s files.", skipped)
    logging.debug("Created %s distinct buckets based on structure.", len(buckets))
    
    active_buckets = {k: v for k, v in buckets.items() if len(v) > 1}
    logging.debug("Active buckets to process: %s", len(active_buckets))
    
    total_comparisons = sum((len(v) * (len(v) - 1)) // 2 for v in active_buckets.values())
    logging.debug("Estimated comparisons required: %s.", total_comparisons)
    emit_progress("comparison", total_comparisons=total_comparisons, force=True)
    
    def task_iter():
        for _, items in active_buckets.items():
            for (p1, t1, s1), (p2, t2, s2) in combinations(items, 2):
                if p1 == p2:
                    continue
                max_size = max(s1, s2, 1)
                if (abs(s1 - s2) / max_size) > size_diff_ratio_threshold:
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
                time.sleep(0.01)
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
                emit_progress("comparison", total_comparisons=total_comparisons)
                if timed_out():
                    hit_timeout = True
                continue

            for fut in done:
                comparisons_completed += 1
                err = fut.exception()
                if err is not None:
                    logging.warning("Comparison task failed: %s", err)
                    emit_progress("comparison", total_comparisons=total_comparisons)
                    continue
                res = fut.result()
                if res:
                    clone_pairs.append(res)
                emit_progress("comparison", total_comparisons=total_comparisons)

        if hit_timeout:
            raise TimeoutError(f"Project analysis timed out after {timeout_seconds}s during comparison.")

    finally:
        if hit_timeout:
            _terminate_pool_now(executor)
        else:
            executor.shutdown(wait=True)

    logging.debug("Detection complete. Found %s clone pairs.", len(clone_pairs))
    emit_progress("completed", total_comparisons=total_comparisons, force=True)
    return clone_pairs