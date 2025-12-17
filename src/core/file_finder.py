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
    
    # Filenames to ignore as they don't contain refactorable logic
    ignore_files = {
        'variables.tf', 
        'outputs.tf', 
        'versions.tf', 
        'provider.tf', 
        'backend.tf', 
        'terraform.tfvars'
    }
    
    files = []
    
    # Regex to check for relevant blocks. 
    # Looks for 'resource' or 'module' followed by a quoted name (standard HCL).
    valid_block_pattern = re.compile(r'^\s*(resource|module)\s+"', re.MULTILINE)

    for p in Path(root).rglob('*'):
        try:
            # 1. Path & Extension Check
            if not p.is_file() or p.suffix not in exts:
                continue
                
            # 2. Path Exclusion (vendor modules)
            # We look for .terraform in the path components to handle nested folders correctly
            if '.terraform' in p.parts:
                continue
                
            # 3. Naming Convention Check
            if p.name in ignore_files:
                continue
            
            # 4. Content Check (does it contain logic?)
            try:
                # Read text (ignore errors to handle potential binary/encoding issues safely)
                content = p.read_text(encoding='utf-8', errors='ignore')
                
                # Filter: Must contain at least one resource or module definition
                if not valid_block_pattern.search(content):
                    # This implicitly filters out files that are empty or only contain 'locals' / 'data'
                    continue
                    
                files.append(p)
                if limit and len(files) >= limit:
                    break
                    
            except Exception as e:
                logging.warning(f"Skipping file {p} due to read error: {e}")
                continue

        except (PermissionError, OSError) as e:
            # Skip files/directories we don't have permission to access
            logging.debug(f"Skipping {p}: {e}")
            continue
            
    return files