"""
Shared utilities for clone detection.
"""

from zss import simple_distance
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


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
