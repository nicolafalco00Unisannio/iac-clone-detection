import hcl2
import yaml
import json
import re
import logging
from pathlib import Path
from collections import defaultdict
from itertools import combinations
import concurrent.futures
from zss import Node, simple_distance

# Configurazione Logging
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
        # Logging ridotto per non intasare la console con errori di parsing comuni
        logging.debug(f"Skipping {path.name}: Parsing failed ({e})")
        return None

def get_ast_signature(data):
    """
    Crea una 'firma' veloce del contenuto del file.
    Esempio: un file con una aws_instance e un s3_bucket avrà firma:
    'resource:aws_instance|resource:aws_s3_bucket'
    
    Questo serve per il BUCKETING: non ha senso confrontare un VPC con un Database.
    """
    if not isinstance(data, dict):
        return "generic"
    
    sig_parts = []
    
    # HCL2 parsa spesso come una lista di dizionari per le root keys
    # Es: {'resource': [{'aws_s3_bucket': {...}}, ...]}
    keys = sorted(data.keys())
    
    for k in keys:
        val = data[k]
        if k == 'resource' and isinstance(val, list):
            # Scendiamo nel dettaglio delle risorse
            for item in val:
                if isinstance(item, dict):
                    for res_type in item.keys():
                        sig_parts.append(f"res:{res_type}")
        elif k == 'data' and isinstance(val, list):
             for item in val:
                if isinstance(item, dict):
                    for data_type in item.keys():
                        sig_parts.append(f"data:{data_type}")
        else:
            # Per variabili, output, provider, etc.
            sig_parts.append(k)
            
    # Se la firma è vuota, usiamo "empty"
    if not sig_parts:
        return "empty"
        
    return "|".join(sorted(sig_parts))

def to_zss_tree(node, label='root'):
    """
    Converte un dizionario/lista Python in un albero ZSS.
    FIX CRITICO: I nodi foglia ora includono il VALORE.
    """
    # Caso Dizionario (Nodo strutturale)
    if isinstance(node, dict):
        zss_node = Node(label)
        for k, v in sorted(node.items()):
            # Etichetta del nodo figlio è la chiave (es. "bucket", "tags")
            zss_node.addkid(to_zss_tree(v, label=k))
        return zss_node
    
    # Caso Lista (Blocchi ripetuti)
    elif isinstance(node, list):
        zss_node = Node(label) # Label potrebbe essere "ingress" o "resource"
        for i, item in enumerate(node):
            # Aggiungiamo un indice per mantenere l'ordine se necessario, o usiamo label generica
            zss_node.addkid(to_zss_tree(item, label=f"{label}_item"))
        return zss_node
    
    # Caso Foglia (Stringhe, Numeri, Booleani)
    else:
        # QUI STA LA MAGIA: 
        # Invece di Node("str"), usiamo Node("VALUE:ami-12345")
        # In questo modo ZSS calcolerà una distanza > 0 se i valori sono diversi.
        val_str = str(node).strip()
        return Node(f"VAL:{val_str}")

def compute_distance_task(args):
    """Helper function per il multiprocessing"""
    p1, tree1, p2, tree2, threshold = args
    
    try:
        dist = simple_distance(tree1, tree2)
        
        # Logica di validazione clone:
        # Distanza 0 = Identici
        # Distanza bassa = Clone con lievi modifiche (es. cambio nome variabile)
        if dist <= threshold:
            return (p1, p2, dist)
    except Exception as e:
        logging.error(f"Error comparing {p1.name} and {p2.name}: {e}")
        
    return None

def count_nodes(zss_node):
    """Conta ricorsivamente il numero totale di nodi nell'albero."""
    count = 1 # Conta se stesso
    for child in zss_node.children:
        count += count_nodes(child)
    return count

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

if __name__ == "__main__":
    target_dir = 'C:/Users/Falco/Documents/Università/EQS/terraform-examples/' 
    
    # 0 = Copia esatta
    # 1-10 = Copia con modifiche lievi (nomi variabili, valori parametri)
    clones = detect_clones_smart(target_dir, limit=50, threshold=5)
    
    print("\n--- CLONE REPORT ---")
    for p1, p2, dist in clones:
        print(f"[Dist: {dist}] {p1.name} <--> {p2.name}")