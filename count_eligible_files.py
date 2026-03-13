"""
Counts how many files in TerraDS would pass the node-count filter
used by the clone detector (MIN_TREE_NODES <= nodes <= MAX_TREE_NODES).
No clone detection is performed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import argparse
import logging
import concurrent.futures
import time

from src.core.parser import parse_file
from src.core.ast_converter import to_zss_tree, count_nodes
from src.detectors.zss_detector import MIN_TREE_NODES, MAX_TREE_NODES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Files ignored by find_iac_files (mirrored here to keep counts consistent)
_IGNORE_FILES = {
    'variables.tf', 'outputs.tf', 'versions.tf', 'provider.tf',
    'backend.tf', 'context.tf', 'terraform.tfvars',
}
_VALID_BLOCK = __import__('re').compile(r'^\s*(resource|module)\s+"', __import__('re').MULTILINE)


def _discover_files(root_dir):
    """
    Fast path enumeration only — no content reads.
    Returns a list of .tf paths that pass name/path filters.
    Content filtering is deferred to the parallel workers.
    """
    candidates = []
    scanned = 0
    for p in Path(root_dir).rglob('*.tf'):
        scanned += 1
        if scanned % 10_000 == 0:
            logging.info("  Discovering... scanned %d paths, %d candidates so far", scanned, len(candidates))
        if '.terraform' in p.parts:
            continue
        if p.name in _IGNORE_FILES:
            continue
        candidates.append(p)
    logging.info("  Discovery complete: scanned %d paths, %d candidates.", scanned, len(candidates))
    return candidates


def _classify_file(args):
    """
    Worker: reads content, checks for resource/module blocks, parses, counts nodes.
    Returns 'no_block', 'parse_failed', 'too_small', 'too_large', or 'eligible'.
    """
    path, min_nodes, max_nodes = args
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return 'parse_failed'
    if not _VALID_BLOCK.search(content):
        return 'no_block'
    data = parse_file(path)
    if data is None:
        return 'parse_failed'
    size = count_nodes(to_zss_tree(data))
    if size < min_nodes:
        return 'too_small'
    if size > max_nodes:
        return 'too_large'
    return 'eligible'


def main():
    parser = argparse.ArgumentParser(description='Count files eligible for clone detection.')
    parser.add_argument(
        '--root_dir',
        default='C:/Users/Falco/Documents/Università/EQS/Materiale/TerraDS',
        help='Root directory to scan',
    )
    parser.add_argument(
        '--min_nodes', type=int, default=MIN_TREE_NODES,
        help=f'Lower node-count bound (default: {MIN_TREE_NODES})',
    )
    parser.add_argument(
        '--max_nodes', type=int, default=MAX_TREE_NODES,
        help=f'Upper node-count bound (default: {MAX_TREE_NODES})',
    )
    parser.add_argument(
        '--workers', type=int, default=None,
        help='Number of parallel workers (default: cpu_count)',
    )
    args = parser.parse_args()

    logging.info("Scanning %s (min_nodes=%d, max_nodes=%d)...", args.root_dir, args.min_nodes, args.max_nodes)

    # Collect candidates with streaming progress, then classify in parallel
    files = _discover_files(args.root_dir)
    total = len(files)
    logging.info("Starting classification of %d files...", total)

    counts = {'eligible': 0, 'too_small': 0, 'too_large': 0, 'parse_failed': 0, 'no_block': 0}
    tasks = [(p, args.min_nodes, args.max_nodes) for p in files]
    done = 0
    start_time = time.monotonic()

    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
        for result in executor.map(_classify_file, tasks, chunksize=64):
            counts[result] += 1
            done += 1
            if done % 500 == 0:
                elapsed = time.monotonic() - start_time
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                logging.info(
                    "  [%d/%d] %.1f%%  |  %.0f files/s  |  ETA: %.0fs",
                    done, total, 100.0 * done / total, rate, eta,
                )

    print("\n=== Results ===")
    print(f"Total .tf paths (post name/path filters):         {total}")
    print(f"  No resource/module block:                        {counts['no_block']}")
    print(f"  Parse failures:                                  {counts['parse_failed']}")
    print(f"  Too small (< {args.min_nodes} nodes):           {counts['too_small']}")
    print(f"  Too large (> {args.max_nodes} nodes):           {counts['too_large']}")
    print(f"  Eligible (analyzed by clone detector):           {counts['eligible']}")
    print(f"  Skipped total:                                   {total - counts['eligible']}")


if __name__ == '__main__':
    main()
