"""
Parsing logic with global caching.
"""

import hcl2
import yaml
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

parsed_asts = {}

def parse_file(path):
    """
    Parser robusto. Se hcl2 fallisce (comune su dataset grandi),
    ritorna None invece di crashare.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            if path.suffix == '.tf':
                return hcl2.load(f)
            elif path.suffix in ('.yaml', '.yml'):
                return yaml.safe_load(f)
            elif path.suffix == '.json':
                return json.load(f)
    except Exception as e:
        logging.debug(f"Skipping {path.name}: Parsing failed ({e})")
        return None
