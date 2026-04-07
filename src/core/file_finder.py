"""
File discovery and filtering logic.
"""

import logging
from pathlib import Path
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def find_iac_files(root, limit=None):
    """
    Finds valid IaC files for clone detection, filtering out noise.

    Filters applied:
    1.  Ignores .terraform directory (external modules).
    2.  Ignores configuration-only files (variables.tf, outputs.tf, providers.tf, etc.).
    3.  Ignores files without 'resource' or 'module' blocks.
    """
    exts = ('.tf',)

    ignore_files = {
        'variables.tf',
        'outputs.tf',
        'versions.tf',
        'provider.tf',
        'backend.tf',
        'context.tf',
        'terraform.tfvars'
    }

    files = []

    valid_block_pattern = re.compile(r'^\s*(resource|module)\s+"', re.MULTILINE)

    for p in Path(root).rglob('*'):
        try:
            if not p.is_file() or p.suffix not in exts:
                continue

            if '.terraform' in p.parts:
                continue

            if p.name in ignore_files:
                continue

            try:
                content = p.read_text(encoding='utf-8', errors='ignore')

                if not valid_block_pattern.search(content):
                    continue

                files.append(p)
                if limit and len(files) >= limit:
                    break

            except Exception as e:
                logging.warning(f"Skipping file {p} due to read error: {e}")
                continue

        except (PermissionError, OSError) as e:
            logging.debug(f"Skipping {p}: {e}")
            continue

    return files
