"""
Convert parsed ASTs to ZSS tree format.
"""

from zss import Node

MAX_ZSS_DEPTH = 30


def to_zss_tree(node, label='root', max_depth=MAX_ZSS_DEPTH, _depth=0):
    """
    Converte un dizionario/lista Python in un albero ZSS.
    I nodi foglia ora includono il VALORE.
    """
    if _depth >= max_depth:
        return Node(f"{label}:DEPTH_LIMIT")

    # Caso Dizionario (Nodo strutturale)
    if isinstance(node, dict):
        zss_node = Node(label)
        for k, v in sorted(node.items()):
            # Etichetta del nodo figlio è la chiave (es. "bucket", "tags")
            zss_node.addkid(to_zss_tree(v, label=k, max_depth=max_depth, _depth=_depth + 1))
        return zss_node
    
    # Caso Lista (Blocchi ripetuti)
    elif isinstance(node, list):
        zss_node = Node(label) # Label potrebbe essere "ingress" o "resource"
        for item in node:
            # Aggiungiamo un indice per mantenere l'ordine se necessario, o usiamo label generica
            zss_node.addkid(to_zss_tree(item, label=f"{label}_item", max_depth=max_depth, _depth=_depth + 1))
        return zss_node
    
    # Caso Foglia (Stringhe, Numeri, Booleani)
    else:
        # Invece di Node("str"), usiamo Node("VALUE:ami-12345")
        # In questo modo ZSS calcolerà una distanza > 0 se i valori sono diversi.
        val_str = str(node).strip()
        return Node(f"VAL:{val_str}")

def count_nodes(zss_node):
    """Conta ricorsivamente il numero totale di nodi nell'albero."""
    count = 1 # Conta se stesso
    for child in zss_node.children:
        count += count_nodes(child)
    return count
