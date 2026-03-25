# Rilevamento di Code Clone in Infrastructure-as-Code tramite Tree Edit Distance su Abstract Syntax Tree: Uno Studio Empirico su Terraform

---

## Abstract

L'Infrastructure-as-Code (IaC) è divenuta il paradigma standard per il provisioning e la gestione dell'infrastruttura cloud. Tuttavia, i flussi di lavoro basati su copy-paste introducono duplicazioni sistematiche che causano configuration drift, propagazione di vulnerabilità di sicurezza e bloat di risorse. I tradizionali strumenti di clone detection, progettati per linguaggi di programmazione general-purpose, risultano inadeguati per i linguaggi dichiarativi come HCL2 (HashiCorp Configuration Language), dove i confronti testuali falliscono nel catturare l'equivalenza strutturale. In questo lavoro proponiamo un tool di clone detection specifico per Terraform che combina il parsing di AST (Abstract Syntax Tree) con l'algoritmo di Tree Edit Distance di Zhang-Shasha per identificare e classificare automaticamente cloni di Tipo 1, 2 e 3. Il nostro approccio introduce un meccanismo di bucketing basato sulla signature delle risorse per ridurre lo spazio di confronto, una codifica value-aware dei nodi foglia per distinguere differenze parametriche da differenze strutturali, e un sistema di suggerimenti di refactoring che genera codice Terraform concreto (estrazione in moduli o parametrizzazione tramite tfvars). Valutiamo il tool sul dataset TerraDS, analizzando la distribuzione dei tipi di clone, il loro impatto sulla manutenibilità e la prevalenza relativa di ciascuna tipologia.

---

## 1. Introduzione

L'Infrastructure-as-Code rappresenta oggi uno dei pilastri fondamentali del cloud computing moderno. Strumenti come Terraform, Ansible, Puppet e Chef consentono agli ingegneri di descrivere l'infrastruttura desiderata attraverso file di configurazione dichiarativi, garantendo riproducibilità, versionamento e automazione del deployment. Terraform, in particolare, si è affermato come lo standard de facto per il provisioning multi-cloud, con il suo linguaggio HCL2 che permette di definire risorse, moduli e dipendenze in modo dichiarativo [HashiCorp, 2024].

Nonostante i vantaggi dell'approccio IaC, la pratica quotidiana degli ingegneri infrastrutturali è caratterizzata da un diffuso ricorso al copy-paste. Un ingegnere che deve configurare un ambiente di produzione partendo da quello di sviluppo tende a copiare l'intero file `dev/main.tf` per creare `prod/main.tf`, introducendo piccole modifiche puntuali. Nel tempo, queste copie divergono silenziosamente, generando un fenomeno noto come *configuration drift*: gli ambienti che dovrebbero essere identici presentano differenze non documentate che possono causare comportamenti inattesi, vulnerabilità di sicurezza e difficoltà di debugging [HashiCorp, 2024].

Il problema della duplicazione nel codice IaC presenta caratteristiche peculiari che lo distinguono dalla duplicazione nel codice tradizionale. In primo luogo, la natura dichiarativa di HCL2 rende i confronti testuali (diff) inadeguati: due file con blocchi identici ma in ordine diverso risultano completamente diversi per un diff testuale, pur essendo semanticamente equivalenti. In secondo luogo, il meccanismo dello *state file* di Terraform introduce una "paralisi da refactoring": spostare risorse duplicate in un modulo riutilizzabile può causare la distruzione e ricreazione delle risorse esistenti, con potenziale downtime in produzione. Infine, la duplicazione nell'IaC ha conseguenze finanziarie dirette: ogni risorsa cloud duplicata inutilmente genera costi operativi reali.

I tool di clone detection esistenti — NiCad, CCFinder, SourcererCC — sono progettati per linguaggi di programmazione imperativi e non supportano nativamente HCL2. Gli approcci testuali e token-based non catturano la struttura dichiarativa dei file Terraform, mentre gli approcci tree-based esistenti richiedono parser specifici per ciascun linguaggio target.

In questo lavoro proponiamo un approccio strutturale al clone detection per Terraform basato su:

1. **Parsing HCL2 in Abstract Syntax Tree** tramite la libreria `python-hcl2`, con conversione in alberi compatibili con l'algoritmo Zhang-Shasha.
2. **Tree Edit Distance (TED)** per la misurazione della distanza strutturale tra coppie di file, con codifica value-aware dei nodi foglia.
3. **Bucketing per signature** delle risorse, che riduce drasticamente lo spazio di confronto da O(n²) a O(k²) dove k << n.
4. **Classificazione automatica** dei cloni in Tipo 1 (esatti), Tipo 2 (parametrizzati) e Tipo 3 (near-miss) basata sul rapporto tra TED e differenze parametriche.
5. **Suggerimenti di refactoring** che generano codice Terraform concreto per l'estrazione in moduli o la parametrizzazione tramite variabili.

I contributi principali di questo lavoro sono:

- La definizione di una mappatura tra la tassonomia classica dei code clone [Roy & Cordy, 2009] e il contesto specifico dell'Infrastructure-as-Code.
- La progettazione e implementazione di un tool di clone detection AST-based specifico per Terraform, con ottimizzazioni per la scalabilità (bucketing, parallelizzazione, pruning) e meccanismi di robustezza (timeout per-progetto, checkpointing persistente, limite di profondità AST).
- Una valutazione empirica sul dataset TerraDS che analizza distribuzione, impatto e prevalenza dei cloni nel codice Terraform.
- Un sistema di suggerimenti di refactoring automatici che genera codice Terraform eseguibile.

### 1.1 Obiettivi e Research Questions

Il presente lavoro si propone di rispondere alle seguenti Research Questions:

**RQ1: How do we classify code clones in IaC?**
Proponiamo una mappatura della tassonomia classica dei clone (Type 1-4) al contesto IaC, definendo criteri di classificazione basati sulla Tree Edit Distance e sull'analisi delle differenze parametriche tra file Terraform.

**RQ2: What is the impact of code clones in IaC?**
Analizziamo le conseguenze specifiche della duplicazione nel codice Terraform, identificando quattro categorie di impatto: configuration drift, propagazione di vulnerabilità di sicurezza, paralisi da refactoring e bloat di risorse con spreco finanziario.

**RQ3: Which clone types are more common?**
Attraverso l'analisi empirica del dataset TerraDS, quantifichiamo la distribuzione relativa dei cloni di Tipo 1, 2 e 3 nel codice Terraform reale, identificando i pattern di duplicazione più frequenti.

---

## 2. Background e Lavori Rilevanti

### 2.1 Terraform

Terraform è uno strumento open-source di Infrastructure-as-Code sviluppato da HashiCorp che consente di definire, provisioning e gestire infrastruttura cloud attraverso file di configurazione dichiarativi scritti in HCL2 (HashiCorp Configuration Language). A differenza dei linguaggi imperativi, HCL2 descrive lo stato desiderato dell'infrastruttura piuttosto che la sequenza di operazioni per raggiungerlo.

I concetti fondamentali di Terraform includono:

- **Risorse** (`resource`): unità atomiche di infrastruttura (es. `aws_instance`, `aws_s3_bucket`), ciascuna con un tipo e un nome logico univoco.
- **Moduli** (`module`): meccanismo di composizione e riuso che permette di raggruppare risorse correlate in unità riutilizzabili con interfaccia parametrizzata.
- **Variabili** (`variable`): parametri di input che consentono di rendere le configurazioni generiche e riutilizzabili.
- **State file**: file JSON che traccia la corrispondenza tra le risorse definite nel codice e quelle effettivamente presenti nell'infrastruttura cloud. Ogni risorsa è identificata da un indirizzo univoco (es. `aws_instance.web`); modifiche a questo indirizzo possono causare la distruzione e ricreazione della risorsa.
- **Provider**: plugin che implementano l'interfaccia con specifici servizi cloud (AWS, Azure, GCP, etc.).

La struttura tipica di un progetto Terraform prevede file come `main.tf` (risorse principali), `variables.tf` (dichiarazioni di variabili), `outputs.tf` (valori di output) e `terraform.tfvars` (valori concreti delle variabili). L'unità di riuso in Terraform è il modulo, che corrisponde tipicamente a una directory contenente uno o più file `.tf`.

### 2.2 Code Smell in IaC

La letteratura recente ha dimostrato che il codice IaC è soggetto a problemi di qualità analoghi a quelli del codice tradizionale. Sharma, Fragkoulis e Spinellis [2016] hanno condotto uno studio pioneristico dimostrando che il codice IaC soffre di code smell, con il codice duplicato che rappresenta il 13% degli smell individuati. Rahman e Williams [2019] hanno esteso questa analisi mostrando che i cloni in IaC propagano vulnerabilità di sicurezza tra configurazioni, amplificando il rischio di compromissione dell'infrastruttura.

Bessghaier et al. [2024] hanno condotto uno studio empirico su 82 progetti Puppet, analizzando 12 tipi di IaC smell e la loro co-occorrenza. I risultati mostrano che il 74% dei file IaC presenta almeno uno smell, con *Insufficient Modularization* e *Tightly Coupled Modules* presenti nel 96-100% dei progetti. I file "smelly" risultano 3.8 volte più frequentemente modificati, presentano un code churn 3.1 volte superiore e sono 3.3 volte più inclini ai difetti rispetto ai file non-smelly. Questi risultati quantificano l'impatto reale dei problemi di qualità nel codice IaC, rafforzando la necessità di strumenti di analisi automatica.

### 2.3 Code Clone

Un code clone è un frammento di codice che è identico o simile ad un altro frammento all'interno dello stesso sistema software o tra sistemi diversi. La definizione formale, secondo Roy e Cordy [2009], identifica un clone come una coppia di frammenti di codice $(f_1, f_2)$ tale che $f_1$ e $f_2$ siano sufficientemente simili secondo una metrica di similarità definita.

I code clone nascono tipicamente da pratiche di copy-paste durante lo sviluppo, quando gli sviluppatori copiano frammenti esistenti e li adattano per nuovi requisiti. Sebbene questa pratica acceleri lo sviluppo iniziale, introduce debito tecnico che si manifesta nel tempo sotto forma di inconsistenze tra le copie, difficoltà di manutenzione e propagazione di difetti [Juergens et al., 2009].

### 2.4 Tassonomia dei Cloni

La tassonomia classica dei code clone, definita da Roy e Cordy [2009], distingue quattro tipologie:

- **Type 1 (Exact Clone):** Frammenti di codice identici eccetto variazioni in whitespace, layout e commenti. Non presentano alcuna differenza semantica o sintattica.
- **Type 2 (Parameterized Clone):** Frammenti sintatticamente identici nella struttura, ma con variazioni in identificatori, letterali, tipi, whitespace, layout e commenti.
- **Type 3 (Near-miss Clone):** Frammenti copiati con ulteriori modifiche come statement aggiunti, rimossi o modificati, oltre alle variazioni del Tipo 2.
- **Type 4 (Semantic Clone):** Frammenti che eseguono la stessa computazione ma sono implementati con varianti sintattiche diverse. Richiedono analisi semantica per la rilevazione.

Nel contesto dell'Infrastructure-as-Code proponiamo la seguente mappatura:

| Tipo | Definizione Classica | Mappatura IaC |
|------|---------------------|---------------|
| **Type 1** | Copie esatte | Due risorse che forniscono la stessa infrastruttura con identici parametri (es. due `aws_instance` identiche in file diversi) |
| **Type 2** | Copie con parametri rinominati | Risorse con struttura equivalente ma valori diversi; candidati ideali per templating tramite `variable` o estrazione in `module` |
| **Type 3** | Copie con variazioni strutturali | Configurazioni quasi identiche con piccole variazioni (es. una regola di sicurezza extra); forma tipica di configuration drift tra ambienti |
| **Type 4** | Cloni semantici | Configurazioni sintatticamente diverse che producono la stessa infrastruttura (es. provider diversi per lo stesso servizio) |

Il nostro tool si concentra sulla rilevazione dei Tipi 1-3, in quanto il Tipo 4 richiederebbe un'analisi semantica che va oltre la comparazione strutturale degli AST.

### 2.5 Conseguenze dei Cloni in IaC

L'analisi della letteratura e delle caratteristiche specifiche di Terraform ci ha permesso di identificare quattro categorie principali di impatto dei cloni nel codice IaC:

**Configuration Drift.** I cloni di Tipo 3 sono il vettore principale di questo problema. Quando un ingegnere copia la configurazione dell'ambiente di sviluppo per creare quello di produzione, le due copie tendono a divergere nel tempo. Modifiche applicate a un ambiente — come patch di sicurezza o aggiornamenti di configurazione — non vengono sistematicamente propagate a tutti i cloni, generando ambienti inconsistenti che contraddicono il principio fondamentale dell'IaC: la riproducibilità [HashiCorp, 2024].

**Propagazione di Vulnerabilità di Sicurezza.** Le impostazioni di sicurezza in IaC sono distribuite in molte risorse. Quando una vulnerabilità viene scoperta e corretta in una risorsa, i cloni di Tipo 1 e 2 della stessa risorsa presenti in altri file possono rimanere non corretti, lasciando backdoor nell'infrastruttura apparentemente messa in sicurezza. Rahman e Williams [2019] hanno dimostrato che questo pattern è frequente nei contesti IaC.

**Paralisi da Refactoring.** Nel codice tradizionale, il refactoring di una funzione duplicata è generalmente sicuro. In Terraform, le risorse sono tracciate nello state file con il loro indirizzo univoco. Spostare risorse duplicate in un modulo riutilizzabile modifica l'indirizzo della risorsa, causando potenzialmente la distruzione e ricreazione della risorsa in produzione. Questa caratteristica genera una "paralisi" nei confronti del refactoring, poiché la migrazione richiederebbe una manipolazione manuale dello stato per evitare downtime.

**Bloat di Risorse e Spreco Finanziario.** Quando uno sviluppatore copia un blocco di configurazione (clone di Tipo 1 o 2) che include risorse accessorie non necessarie (es. un load balancer o servizi di logging), viene provisionata più infrastruttura del necessario. Nel cloud computing, dove i costi sono proporzionali alle risorse utilizzate, la duplicazione di codice si traduce direttamente in duplicazione di costi.

### 2.6 Studi Precedenti sui Cloni in IaC

La ricerca sul clone detection nei file di configurazione infrastrutturale è un'area emergente ma in rapida crescita. Analizziamo di seguito i contributi più rilevanti.

Juergens et al. [2009] hanno condotto uno studio empirico fondamentale dimostrando che il 52% dei clone group nel codice tradizionale contiene almeno un'inconsistenza correlata a difetti reali, con una densità di 48.1 difetti per kLOC nel codice clonato. Sebbene lo studio non fosse specifico per IaC, i risultati giustificano fortemente la necessità di clone detection in qualsiasi contesto software.

Mondal et al. [2017] hanno studiato la propagazione dei bug attraverso il code cloning, dimostrando che fino al 33% dei bug-fix nei cloni riguarda bug propagati tramite copy-paste. I cloni near-miss (Tipo 2 e 3) risultano i principali vettori di propagazione, con il 16.22% dei bug-fix per cloni di Tipo 3 che coinvolge bug propagati.

Tsuru et al. [2021] hanno proposto una tecnica di clone detection di Tipo 2 specifica per Dockerfile, basata su AST e suffix array con normalizzazione dei token. Lo studio ha analizzato 4,817 Dockerfile da 725 repository GitHub, ottenendo una precisione del 95-100%. Questo lavoro dimostra l'applicabilità del clone detection a file di configurazione infrastrutturale e la necessità di approcci specifici per ciascun linguaggio IaC.

Cardoen [2024] ha delineato un piano di ricerca dottorale sul code cloning nei file CI/CD, con focus su GitHub Actions. L'analisi di 43K+ repository e 2.5M+ file workflow conferma che i file di configurazione CI/CD soffrono degli stessi problemi di clonazione del codice general-purpose, con meccanismi di riuso (Reusable Actions, Reusable Workflows) che tentano di mitigare il fenomeno.

Bessghaier et al. [2024] hanno analizzato 82 progetti Puppet dimostrando che i problemi di modularità (*Insufficient Modularization*, *Tightly Coupled Modules*) sono i più diffusi tra gli IaC smell, presenti nel 96-100% dei progetti. I file con smell sono 3.3 volte più inclini ai difetti, quantificando l'impatto reale della scarsa qualità nel codice IaC.

Oliveira et al. [2025] hanno replicato e validato la tassonomia dei difetti IaC "Gang of Eight" su 541 repository (Ansible, Chef, Puppet), confermando che *Configuration Data* è la categoria di difetto più prevalente. Questa categoria include valori hard-coded ripetuti e configurazioni duplicate, direttamente rilevabili tramite clone detection.

### 2.7 Altri Tool per Clone Detection

La letteratura sui tool di clone detection per codice general-purpose è vasta. Roy e Cordy [2009] classificano le tecniche in cinque categorie principali:

| Approccio | Tecnica | Tool Rappresentativi | Punti di Forza | Limiti |
|-----------|---------|---------------------|----------------|--------|
| **Text-based** | Hashing, dotplot | NiCad, Simian | Semplice, language-independent | Bassa recall per Type 2+ |
| **Token-based** | Suffix-tree, data mining | CCFinder, CP-Miner, SourcererCC | Buon compromesso recall/precision | Non rispetta la struttura sintattica |
| **Tree-based** | AST matching, metriche AST | CloneDr, Deckard | Eccelle per Type 2 e 3 | Richiede parser specifico |
| **Metrics-based** | Confronto vettori metriche | Mayrand et al. | Scalabile, veloce | Bassa precision |
| **Graph-based** | Isomorfismo PDG | Duplix | Trova cloni semantici unici | Computazionalmente costoso |

Bellon et al. [2007] hanno condotto la valutazione quantitativa più completa del periodo, confrontando sei tool su 850 KLOC di codice C e Java. I risultati dimostrano che gli approcci token-based (CCFinder) offrono il miglior compromesso recall/precision per cloni di Tipo 1, mentre gli approcci tree-based eccellono per cloni di Tipo 2 e 3. Nessun singolo tool domina su tutti i tipi e tutti i programmi.

Yu et al. [2025] hanno introdotto una prospettiva complementare, studiando le caratteristiche dei cloni "riusabili" tramite modelli di machine learning (Random Forest, AUC = 0.73), dimostrando che non tutti i cloni sono negativi e che alcuni rappresentano pratiche di riuso legittime.

Il nostro approccio si posiziona nella categoria tree-based, utilizzando la Tree Edit Distance come metrica di similarità. Rispetto ai tool esistenti, il nostro contributo colma un gap specifico: **non esiste ad oggi uno strumento di clone detection specifico per IaC (Terraform).**

---

## 3. Metodologia

### 3.1 Architettura del Tool

Il nostro tool implementa una pipeline di clone detection composta da sette fasi sequenziali, dalla scoperta dei file alla generazione del report. La Figura 1 illustra l'architettura complessiva.

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  File        │    │  Parsing     │    │  AST         │    │  Bucketing   │
│  Discovery   │───▶│  HCL2        │───▶│  Conversion  │───▶│  per         │
│  (.tf)       │    │  → dict      │    │  dict → ZSS  │    │  Signature   │
└──────────────┘    └──────────────┘    │  (depth≤30)  │    └──────┬───────┘
                                        └──────────────┘           │
┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  HTML Report │    │  Classifica- │    │  TED         │◀─────────┘
│  Generation  │◀───│  zione Cloni │◀───│  Computation │
│  + Refactor  │    │  Type 1/2/3  │    │  (parallela  │
└──────────────┘    └──────────────┘    │  + timeout)  │
        ▲                               └──────────────┘
        │
┌──────────────┐
│  Checkpoint  │
│  (JSON)      │
│  + Resume    │
└──────────────┘
```
*Figura 1: Pipeline di clone detection con checkpointing e timeout.*

**Fase 1 — File Discovery.** Il modulo `file_finder.py` esegue una scansione ricorsiva della directory di input, selezionando esclusivamente file con estensione `.tf`. Vengono esclusi: (a) i file nella directory `.terraform/` (moduli vendor scaricati automaticamente); (b) i file di sola configurazione che non contengono logica refactorabile (`variables.tf`, `outputs.tf`, `versions.tf`, `provider.tf`, `backend.tf`, `context.tf`, `terraform.tfvars`); (c) i file che non contengono almeno un blocco `resource` o `module`, verificato tramite espressione regolare `^\s*(resource|module)\s+"`.

**Fase 2 — Parsing.** Il modulo `parser.py` utilizza la libreria `python-hcl2` per parsare ciascun file `.tf` in un dizionario Python che rappresenta l'AST del file. Il parser gestisce gracefully gli errori, restituendo `None` per file malformati senza interrompere l'analisi.

**Fase 3 — Conversione AST.** Il modulo `ast_converter.py` converte il dizionario Python in un albero compatibile con la libreria ZSS (Zhang-Shasha). La conversione implementa un limite di profondità massima (`MAX_ZSS_DEPTH = 30`): i nodi oltre questa soglia vengono troncati con un'etichetta `DEPTH_LIMIT`, prevenendo esplosioni combinatorie su alberi patologicamente profondi e garantendo tempi di calcolo TED predicibili.

**Fase 4 — Bucketing.** Il modulo `detector_utils.py` calcola una signature per ciascun file basata sui tipi di risorsa contenuti. I file con signature identica vengono raggruppati nello stesso bucket; solo le coppie all'interno dello stesso bucket vengono confrontate.

**Fase 5 — TED Computation.** Il modulo `zss_detector.py` orchestra il calcolo parallelo della Tree Edit Distance per tutte le coppie di file all'interno di ciascun bucket, utilizzando `ProcessPoolExecutor` con gestione manuale dei future. Il modulo implementa: (a) un timeout per-progetto configurabile che interrompe l'analisi dopo un tempo limite, con terminazione forzata (`kill`) dei worker per garantire il rilascio delle risorse anche su Windows; (b) un filtro superiore sulla dimensione degli alberi (`MAX_TREE_NODES = 500`) che esclude file troppo grandi il cui costo TED sarebbe proibitivo; (c) un pruning basato sul rapporto di differenza di dimensione (`SIZE_DIFF_RATIO_THRESHOLD = 0.20`) anziché sulla differenza assoluta, per adattare il filtraggio alla scala degli alberi; (d) un sistema di progress callback che emette lo stato dell'analisi a intervalli configurabili.

**Fase 6 — Classificazione.** Il modulo `diff_analyzer.py` classifica ciascuna coppia di cloni in Type 1, 2 o 3 basandosi sul rapporto tra la TED e il numero di differenze parametriche.

**Fase 7 — Report.** Il modulo `report_generator.py` genera un report HTML interattivo con statistiche aggregate, diff side-by-side racchiuse in sezioni collassabili (`<details>`) per migliorare la navigabilità, e suggerimenti di refactoring.

**Checkpointing e ripresa.** Il modulo `main.py` implementa un sistema di checkpointing persistente che salva periodicamente lo stato dell'analisi (progetti completati, coppie di cloni trovate, contatori di errori e timeout) su file JSON. Il salvataggio avviene tramite scrittura atomica (write su file temporaneo + `os.replace`) con retry e fallback su file di recovery in caso di lock. In caso di interruzione (`KeyboardInterrupt` o timeout), il tool genera un report parziale e un checkpoint che consente di riprendere l'analisi con il flag `--resume_checkpoint`, evitando di riprocessare i progetti già completati.

### 3.2 Conversione in AST

La conversione da file Terraform ad albero ZSS avviene in due fasi: il parsing HCL2 produce un dizionario Python annidato, che viene poi convertito ricorsivamente in un albero ZSS.

La libreria `python-hcl2` parsa il file `.tf` producendo un dizionario con la seguente struttura:

```python
{
  "resource": [
    {
      "aws_instance": {
        "web_server": {
          "ami": "ami-12345",
          "instance_type": "t2.micro",
          "tags": {"Name": "WebServer"}
        }
      }
    }
  ]
}
```

La funzione `to_zss_tree(node, label, max_depth, _depth)` converte ricorsivamente questo dizionario in un albero ZSS secondo le seguenti regole:

1. **Dizionari:** Ogni chiave diventa un nodo figlio; il valore viene convertito ricorsivamente come sottoalbero del nodo chiave.
2. **Liste:** Ciascun elemento della lista diventa un nodo figlio con etichetta `"{label}_item"`.
3. **Valori foglia** (stringhe, numeri, booleani): Vengono codificati come nodi con etichetta `VAL:{valore}`.
4. **Limite di profondità:** Se la ricorsione raggiunge `MAX_ZSS_DEPTH` (default: 30), il nodo viene troncato con etichetta `{label}:DEPTH_LIMIT`. Questo previene alberi patologicamente profondi — ad esempio configurazioni con policy JSON annidate — dal generare costi TED esponenziali.

La codifica dei valori foglia con il prefisso `VAL:` è una scelta progettuale cruciale. Senza questo prefisso, due alberi con struttura identica ma valori diversi avrebbero TED = 0, rendendo impossibile distinguere cloni di Tipo 1 (identici) da cloni di Tipo 2 (parametrizzati). Con il prefisso, un'operazione di sostituzione di un valore foglia ha costo 1 nel calcolo della TED.

La funzione `count_nodes(zss_node)` conta ricorsivamente il numero di nodi nell'albero, includendo la radice. Questo conteggio è utilizzato per il filtraggio dei file troppo piccoli e per il pruning basato sulla differenza di dimensione.

**Esempio di conversione:**

```
Input:  resource "aws_instance" "web" { ami = "ami-123", type = "t2.micro" }

Albero ZSS:
            root
             └── resource
                  └── resource_item
                       └── aws_instance
                            └── web
                                 ├── ami
                                 │    └── VAL:ami-123
                                 └── type
                                      └── VAL:t2.micro

Numero di nodi: 9
```

### 3.3 Tree Distance con ZSS

L'algoritmo di Zhang-Shasha [1989] calcola la *Tree Edit Distance* (TED) tra due alberi ordinati, definita come il costo minimo della sequenza di operazioni di editing necessarie per trasformare un albero nell'altro. Le operazioni ammesse sono:

- **Inserimento** di un nodo: costo = 1
- **Cancellazione** di un nodo: costo = 1
- **Sostituzione** dell'etichetta di un nodo: costo = 1 (se le etichette differiscono)

La complessità computazionale dell'algoritmo è O(n₁ · n₂ · min(d₁, l₁) · min(d₂, l₂)), dove nᵢ è il numero di nodi, dᵢ la profondità e lᵢ il numero di foglie dell'albero i-esimo. In pratica, per alberi bilanciati, la complessità è approssimativamente O(n² · m²).

Per mitigare il costo computazionale, il nostro tool implementa tre strategie di ottimizzazione:

**Bucketing per signature.** La funzione `get_ast_signature(data)` genera una stringa di signature per ciascun file, concatenando i tipi di risorsa presenti (es. `res:aws_instance|res:aws_s3_bucket`) ordinati alfabeticamente. Solo i file con signature identica vengono confrontati, riducendo il numero di confronti da $\binom{n}{2}$ (tutte le coppie) a $\sum_b \binom{k_b}{2}$ dove $k_b$ è il numero di file nel bucket $b$ e $k_b \ll n$.

**Pruning per rapporto di dimensione.** Prima di calcolare la TED, il tool verifica che il rapporto di differenza di dimensione tra i due alberi non superi una soglia relativa: se $\frac{|n_1 - n_2|}{\max(n_1, n_2)} > 0.20$, la coppia viene scartata senza calcolare la TED. L'uso di una soglia relativa (anziché assoluta come nella versione iniziale) consente un filtraggio più accurato: per alberi piccoli, una differenza di pochi nodi è significativa, mentre per alberi grandi la stessa differenza assoluta potrebbe non esserlo.

**Parallelizzazione con gestione dei future.** Il calcolo della TED per le coppie all'interno di ciascun bucket viene distribuito su più processi tramite `ProcessPoolExecutor`. Anziché utilizzare `executor.map` con chunksize fisso, il tool gestisce manualmente i future con un pool di dimensione `max_in_flight = workers × 4`, raccogliendo i risultati incrementalmente tramite `concurrent.futures.wait` con `return_when=FIRST_COMPLETED`. Questo approccio consente: (a) il rispetto del timeout tramite controllo periodico della deadline; (b) l'emissione di progress callback durante l'attesa; (c) la terminazione immediata dei worker in caso di timeout tramite `proc.kill()` sui processi del pool.

**Filtraggio file boilerplate e file troppo grandi.** I file con meno di `MIN_TREE_NODES = 100` nodi nell'albero ZSS vengono esclusi dall'analisi, in quanto file molto piccoli genererebbero un elevato numero di falsi positivi senza valore informativo per il refactoring. Simmetricamente, i file con più di `MAX_TREE_NODES = 500` nodi vengono esclusi per evitare costi TED proibitivi: l'algoritmo Zhang-Shasha ha complessità superquadratica, e alberi molto grandi (es. file con centinaia di risorse) renderebbero l'analisi intrattabile.

**Timeout per-progetto.** Il detector accetta un parametro `timeout_seconds` che impone un limite temporale all'analisi di ciascun progetto. Il timeout viene verificato durante la fase di parsing (prima di ogni file) e durante la fase di confronto (prima di sottomettere nuovi task e dopo ogni attesa). In caso di timeout, viene sollevata un'eccezione `TimeoutError` e i worker del pool vengono terminati forzatamente tramite `proc.kill()`, necessario per garantire il rilascio delle risorse anche su Windows dove `terminate()` potrebbe non essere sufficiente per worker bloccati in calcoli CPU-bound.

La soglia di TED è configurabile dall'utente (valore di default: 5). Una coppia di file viene classificata come clone solo se la sua TED è inferiore o uguale alla soglia. Valori più bassi producono risultati più conservativi (solo cloni molto simili), mentre valori più alti includono anche cloni near-miss con maggiori differenze strutturali.

**Parametri CLI per robustezza.** L'analisi per-progetto (`--per_project`) supporta i seguenti parametri aggiuntivi:

| Flag CLI | Default | Funzione |
|----------|---------|----------|
| `--project_timeout` | 600s | Timeout per l'analisi di ciascun progetto |
| `--checkpoint_file` | `clone_checkpoint.json` | File di salvataggio dello stato |
| `--resume_checkpoint` | off | Riprende l'analisi da un checkpoint esistente |
| `--checkpoint_interval` | 300s | Intervallo di salvataggio intra-progetto |

In caso di interruzione (timeout o `Ctrl+C`), il tool: (1) salva un checkpoint con lo stato corrente; (2) genera un report parziale (suffisso `_partial`) con i risultati disponibili; (3) stampa il comando per riprendere l'analisi. I progetti vengono processati in ordine alfabetico deterministico per garantire la riproducibilità del checkpoint.

### 3.4 Logica di Classificazione dei Cloni

La classificazione di una coppia di cloni avviene confrontando la Tree Edit Distance con il numero di differenze puramente parametriche. La funzione `classify_clone_type(distance, ast1, ast2)` implementa la seguente logica:

**Definizione formale.** Siano $T_1$ e $T_2$ gli alberi ZSS di due file, $d = \text{TED}(T_1, T_2)$ la Tree Edit Distance, e $p = |\text{param\_diffs}(A_1, A_2)|$ il numero di differenze parametriche (valori foglia diversi in posizioni corrispondenti degli AST originali):

$$
\text{tipo}(T_1, T_2) = \begin{cases}
\text{Type 1} & \text{se } d = 0 \\
\text{Type 2} & \text{se } d = p \text{ e } p > 0 \\
\text{Type 3} & \text{se } d > p
\end{cases}
$$

Se la TED è esattamente uguale al numero di parametri diversi, allora tutte le operazioni di editing sono sostituzioni di valori foglia, e la struttura degli alberi è isomorfa (Type 2). Se la TED supera il numero di differenze parametriche, allora sono presenti anche operazioni di inserimento o cancellazione di nodi, indicando differenze strutturali (Type 3).

**Identificazione delle differenze parametriche.** La funzione `_identify_param_differences(ast1, ast2)` attraversa ricorsivamente i due AST in parallelo, confrontando i valori foglia nelle stesse posizioni strutturali. Per ciascuna differenza rilevata, registra:
- Il percorso nell'AST (es. `resource[0].aws_instance.web.ami`)
- I due valori ($v_1$, $v_2$)
- Il tipo Terraform inferito (`string`, `number`, `bool`, `list(any)`)

L'inferenza del tipo è necessaria per generare dichiarazioni `variable` corrette nei suggerimenti di refactoring.

**Suggerimenti di refactoring.** In base alla classificazione e al numero di differenze, il tool genera suggerimenti concreti:

| Condizione | Strategia | Output |
|-----------|-----------|--------|
| $d = 0$ (Type 1) | Deduplicazione semplice | Suggerimento di usare un singolo file |
| $d = p$ e $p \leq 1$ (Type 2, poche diff) | Parametrizzazione con tfvars | File `variables.tf` + file `.tfvars` per ambiente |
| $d = p$ e $p \geq 2$ (Type 2, molte diff) | Estrazione in modulo | Directory `modules/` con `main.tf` e `variables.tf` + chiamate `module` |
| $d > p$ (Type 3) | Revisione manuale | Evidenziazione differenze strutturali |

Per la strategia **tfvars**, il tool genera: un file `variables.tf` con le dichiarazioni delle variabili, una versione del file originale con riferimenti `var.nome_variabile` al posto dei valori concreti, e file `.tfvars` separati per ciascun ambiente con i valori specifici.

Per la strategia **module extraction**, il tool genera: una directory modulo con `variables.tf` (parametri) e `main.tf` (logica comune con riferimenti a variabili), e blocchi `module` per ciascun chiamante con i valori specifici. Il sistema rileva automaticamente le variabili *pass-through* — riferimenti a `var.X` nel codice originale che devono essere propagati come input del modulo.

### 3.5 Testing

La correttezza dei singoli componenti della pipeline è verificata tramite una test suite automatizzata basata su **pytest**. La suite comprende 69 test organizzati in 8 moduli, ciascuno dedicato a un componente specifico del tool.

| Modulo di test | Componente verificato | Test |
|----------------|----------------------|------|
| `test_ast_converter.py` | Conversione dict → albero ZSS | 8 |
| `test_parser.py` | Parsing HCL2, YAML, JSON | 5 |
| `test_file_finder.py` | Scoperta e filtraggio file | 5 |
| `test_detector_utils.py` | Signature bucketing, calcolo distanza | 6 |
| `test_diff_analyzer.py` | Classificazione Type 1/2/3, differenze parametriche | 13 |
| `test_hcl_utils.py` | Formattazione valori HCL, sanitizzazione nomi variabile | 9 |
| `test_refactoring.py` | Generazione moduli, rendering HCL, parametrizzazione tfvars | 23 |
| **Totale** | | **69** |

I test coprono l'intero percorso logico della pipeline: dal parsing di file Terraform validi e invalidi, alla conversione in alberi ZSS con verifica della struttura dei nodi e della codifica `VAL:` dei valori foglia, al bucketing per signature con verifica della correttezza delle firme generate, al calcolo della Tree Edit Distance con verifica delle soglie, alla classificazione dei cloni con verifica della regola $d = p$ per Type 2, fino alla generazione dei suggerimenti di refactoring con verifica della correttezza del codice HCL prodotto (dichiarazioni di variabili, iniezione di riferimenti `var.*`, gestione delle collisioni di nomi, rilevamento delle variabili pass-through).

Le fixture condivise (`conftest.py`) forniscono AST di esempio rappresentativi dei casi d'uso principali: risorse AWS con parametri identici (per Type 1), con valori diversi (per Type 2), con differenze strutturali (per Type 3), e directory temporanee con file `.tf` validi e invalidi per i test del file finder. Tutti i test sono eseguibili con il comando `pytest tests/ -v` e completano in meno di 1 secondo.

### 3.6 Validazione Empirica dei Suggerimenti di Refactoring

Oltre ai test unitari sui generatori di codice HCL, abbiamo aggiunto una validazione empirica end-to-end dei suggerimenti di refactoring su quattro progetti reali. Per ciascun caso, confrontiamo il piano Terraform **pre-refactoring** con quello **post-refactoring** tramite il tool di equivalenza semantica (`plan_equivalence.py`), verificando che la trasformazione preservi il comportamento infrastrutturale.

Le fixture dei piani sono salvate con naming `pre_<id>` e `post_<id>` (formato JSON o TXT da `terraform show`).

La Tabella seguente riassume i quattro casi validati:

| Project ID | Tipo clone | Strategia di refactoring | Piano | Normalizzazione | Esito |
|------------|------------|--------------------------|-------|-----------------|-------|
| 104546844 | Type 2 | Estrazione in modulo | TXT | `normalize_modules=True` | PASS |
| 104919803 | Type 2 | Parametrizzazione con tfvars | TXT | `normalize_modules=True` | PASS |
| 578269253 | Type 2 | Estrazione in modulo | JSON | `normalize_modules=True`, `normalize_label_separators=True` | PASS |
| 800611402 | Type 1 | Deduplicazione semplice | JSON | `normalize_modules=True` | PASS |

Il caso `578269253` richiede anche la normalizzazione dei separatori delle label (`-` vs `_`), poiche il refactoring preserva la semantica ma introduce una variazione lessicale nei nomi interni. Questo comportamento è coerente con i limiti noti del confronto puramente sintattico e con la necessita di normalizzazioni controllate per evitare falsi negativi.

Questa validazione aumenta la confidenza pratica nei suggerimenti prodotti: non solo il codice generato è sintatticamente valido, ma mantiene anche l'equivalenza semantica dei piani in casi reali di refactoring.

---

## 4. Esperimenti

### 4.1 TerraDS

Per la valutazione empirica utilizziamo **TerraDS**, dataset pubblico di repository Terraform open-source distribuito su Zenodo [TerraDS, 2024]. L'analisi è stata eseguita sull'intero corpus, non su un campione ridotto.

La pipeline di selezione dei file avviene in due stadi:

1. **Filtri di nome/path:** esclusione di file non refactorabili (`variables.tf`, `outputs.tf`, `versions.tf`, `provider.tf`, `backend.tf`, `context.tf`, `terraform.tfvars`) e directory vendor (`.terraform/`).
2. **Filtri strutturali:** presenza di almeno un blocco `resource`/`module`, parsing HCL2 riuscito, dimensione AST nel range operativo (`100 ≤ nodi ≤ 500`).

La tabella seguente riporta i conteggi reali sul dataset completo:

| Metrica | Conteggio | Percentuale su `.tf` filtrati |
|---------|-----------|-------------------------------|
| Total `.tf` paths (post name/path filters) | 683,962 | 100.0% |
| No `resource`/`module` block | 207,368 | 30.3% |
| Parse failures | 6,678 | 1.0% |
| Too small (`< 100` nodi) | 408,082 | 59.7% |
| Too large (`> 500` nodi) | 1,673 | 0.2% |
| **Eligible (analyzed by clone detector)** | **60,161** | **8.8%** |
| **Skipped total** | **623,801** | **91.2%** |

Questi numeri evidenziano che il collo di bottiglia principale non è il parsing, ma la distribuzione dimensionale degli AST: la maggior parte dei file Terraform nel corpus è troppo piccola per fornire segnali clonali robusti secondo la soglia `MIN_TREE_NODES = 100`.

### 4.2 Parametri e Metriche

La configurazione sperimentale utilizza i seguenti parametri:

| Parametro | Valore | Motivazione |
|-----------|--------|-------------|
| **Soglia TED** | 5 | Compromesso tra recall e precision; cattura cloni con fino a 5 operazioni di editing |
| **Nodi minimi** (`MIN_TREE_NODES`) | 100 | Esclude file boilerplate che genererebbero falsi positivi |
| **Nodi massimi** (`MAX_TREE_NODES`) | 500 | Esclude file troppo grandi con costo TED proibitivo |
| **Profondità massima AST** (`MAX_ZSS_DEPTH`) | 30 | Previene esplosioni combinatorie su alberi patologicamente profondi |
| **Soglia rapporto dimensione** (`SIZE_DIFF_RATIO_THRESHOLD`) | 0.20 | Pruning relativo: scarta coppie con differenza di dimensione > 20% |
| **Bucketing** | Per tipo di risorsa | Evita confronti tra file con risorse diverse |
| **Parallelizzazione** | ProcessPoolExecutor con gestione manuale dei future | Sfrutta tutti i core disponibili con supporto timeout |
| **Timeout per-progetto** (`--project_timeout`) | 600s | Impedisce che progetti patologici blocchino l'intera analisi |
| **Intervallo checkpoint** (`--checkpoint_interval`) | 300s | Frequenza di salvataggio dello stato durante l'analisi di un progetto |

Le regole di filtraggio dei file escludono i seguenti nomi: `variables.tf`, `outputs.tf`, `versions.tf`, `provider.tf`, `backend.tf`, `context.tf`, `terraform.tfvars`. Inoltre, viene verificata la presenza di almeno un blocco `resource` o `module` tramite l'espressione regolare `^\s*(resource|module)\s+"`.

Le metriche calcolate includono:

- **Numero di clone pair:** coppie di file con TED ≤ soglia.
- **Numero di clone group:** componenti connesse nel grafo dei cloni (calcolate con NetworkX).
- **Distribuzione per tipo:** conteggio dei cloni Type 1, 2 e 3.
- **File coinvolti:** numero di file unici che partecipano ad almeno una coppia di cloni.
- **Differenze parametriche:** per ciascuna coppia di cloni, il dettaglio dei parametri che differiscono.

### 4.3 Hardware Utilizzato

Gli esperimenti sono stati eseguiti sulla seguente configurazione:

| Componente | Specifica |
|-----------|-----------|
| Sistema operativo | Windows 11 |
| CPU | Processore: AMD Ryzen 7 PRO 7840U |
| RAM | 32 GB LPDDR5X |
| Python | 3.13 |

---

## 5. Risultati

In questa sezione presentiamo i risultati dell'analisi empirica, organizzati per Research Question.

### RQ1: How do we classify code clones in IaC?

La mappatura proposta tra tassonomia classica dei clone e contesto IaC (Sezione 2.4) si è dimostrata operazionalmente valida. La classificazione basata sul rapporto tra TED e differenze parametriche consente di distinguere efficacemente le tre tipologie.

Sull'intero subset analizzabile di TerraDS (**60,161 file**, soglia TED = 5), il tool ha rilevato **8,048 clone pair**, organizzati in **2,287 clone group**, con **5,874 file coinvolti** in almeno una relazione di clonazione.

La regola di classificazione $d = p$ (TED uguale al numero di differenze parametriche) si è dimostrata un criterio operativo affidabile per distinguere cloni di Tipo 2 da cloni di Tipo 3. Consideriamo un esempio concreto dal dataset: due file di configurazione di un cluster Kubernetes (`k8s_cluster.tf`) in due ambienti diversi presentano struttura identica ma differiscono per il parametro `network_plugin` (`"calico"` vs `"kubenet"`) e per il nome del cluster. Il tool calcola TED = 2 e rileva esattamente 2 differenze parametriche, classificando correttamente la coppia come **Type 2 (Parameterized Clone)** e suggerendo l'estrazione in un modulo con due variabili.

In sintesi:

- I **cloni di Tipo 1** (TED = 0) corrispondono a configurazioni duplicate esattamente, tipicamente risultanti dalla copia diretta di file tra ambienti o progetti senza alcuna modifica.
- I **cloni di Tipo 2** (TED = numero di differenze parametriche) identificano configurazioni con struttura isomorfa e parametri diversi, candidati ideali per l'estrazione in moduli o la parametrizzazione tramite variabili.
- I **cloni di Tipo 3** (TED > differenze parametriche) catturano configurazioni con differenze strutturali, indicative di configuration drift o evoluzione divergente delle copie.

### RQ2: What is the impact of code clones in IaC?

L'analisi delle **8,048** coppie di cloni rilevate, combinata con la letteratura esistente, conferma i quattro impatti identificati in Sezione 2.5. Di seguito riportiamo evidenze qualitative dal dataset.

**Configuration drift.** I cloni di Tipo 3 rilevati mostrano pattern consistenti di divergenza tra ambienti. Ad esempio, nel dataset sono presenti coppie di file VPC (`vpc.tf`) che condividono la stessa struttura di rete ma differiscono per la presenza/assenza di blocchi di configurazione come `enable_dns_hostnames` o regole di routing aggiuntive. Queste differenze strutturali sono indicative di modifiche applicate a un ambiente ma non propagate all'altro — il classico pattern di configuration drift.

**Bloat di risorse.** Il dataset contiene 21 copie identiche (Type 1) del file `context.tf`, un pattern comune nei progetti che utilizzano il framework CloudPosse/null-label. Questi file duplicati non apportano logica specifica ma vengono copiati meccanicamente in ogni modulo, generando bloat nel repository. Il tool segnala correttamente queste duplicazioni come candidati per la deduplicazione.

**Opportunità di refactoring.** I cloni di Tipo 2 rappresentano la categoria con il maggiore potenziale di refactoring. L'analisi mostra numerose coppie di file con struttura identica e differenze limitate a 1-3 parametri (nomi di risorsa, AMI ID, instance type), per le quali il tool genera automaticamente suggerimenti concreti: estrazione in modulo per coppie con molte differenze, parametrizzazione tramite `tfvars` per coppie con poche differenze.

**Rischio di sicurezza.** La presenza di cloni di Tipo 1 e 2 con impostazioni di sicurezza (security group, IAM policy) implica che una correzione di vulnerabilità applicata a un file potrebbe non essere propagata ai suoi cloni, confermando le osservazioni di Rahman e Williams [2019].

**Validazione su refactoring reali.** Per rafforzare le evidenze qualitative, abbiamo ispezionato quattro casi reali di refactoring (stesse fixture usate nella validazione pre/post dei piani). In tutti i casi il pattern osservato è coerente: le risorse duplicate vengono rimosse dal file target e sostituite da una chiamata `module`, riducendo duplicazione strutturale senza introdurre nuove risorse nel target.

| Project ID | Pattern di refactoring | Trasformazione osservata nel target | Delta principale |
|------------|------------------------|-------------------------------------|------------------|
| 104546844 | Module extraction (modulo condiviso) | `firewalls.tf` passa da implementazione diretta a modulo `common_module_9` (`source = ../../shared/modules/common_module_9`) | 18 risorse `aws_security_group`/`aws_security_group_rule` rimosse e delegate al modulo |
| 104919803 | Wrapper delegation (canonical clone reuse) | `main.tf` passa da risorse dirette a wrapper `module "impl"` verso il clone canonico | 12 risorse AWS (ASG, ELB, launch config, SG/rule, alarm) rimosse dal target |
| 578269253 | Module extraction (modulo locale) | `prepare-backend/main.tf` passa a `module "common_module_1069"` con modulo locale estratto | 8 risorse IBM/local rimosse dal target; aggiunta directory `modules/common_module_1069/` |
| 800611402 | Wrapper delegation (cross-project reuse) | `main.tf` passa a wrapper `module "impl"` verso la controparte CI; aggiunto `variables.tf` | 9 risorse Harness rimosse dal target; input esplicitati tramite variabili |

Questa analisi è allineata alla verifica di equivalenza dei piani: i quattro casi risultano semanticamente equivalenti tra pre e post refactoring con normalizzazione dei moduli; il caso `578269253` richiede anche normalizzazione dei separatori di label (`-`/`_`) per evitare falsi negativi lessicali.

### RQ3: Which clone types are more common?

La distribuzione dei tipi di clone rilevati sul dataset TerraDS è la seguente:

| Tipo di Clone | Coppie | Percentuale |
|--------------|--------|-------------|
| Type 1 (Exact Clone) | 5,143 | 63.9% |
| Type 2 (Parameterized Clone) | 1,329 | 16.5% |
| Type 3 (Near-miss Clone) | 1,576 | 19.6% |
| **Totale** | **8,048** | **100%** |

**I cloni di Tipo 1 sono dominanti**, rappresentando il 63.9% delle coppie rilevate. Questo risultato indica che la pratica prevalente nel codice Terraform resta la copia esatta di file o blocchi infrastrutturali tra ambienti/progetti. I **2,287 clone group** confermano che i cloni non sono distribuiti uniformemente ma si concentrano in cluster di riuso ripetuto.
**I cloni di Tipo 1 sono dominanti**, rappresentando il 63.9% delle coppie rilevate. Questo risultato indica che la pratica prevalente nel codice Terraform è la copia esatta di file tra ambienti o progetti, senza alcuna modifica. I 2,287 clone group rilevati confermano che i cloni non sono distribuiti uniformemente ma si concentrano in cluster di file identici o quasi identici — spesso corrispondenti a copie dello stesso modulo in diversi ambienti (dev, staging, prod).

I cloni di Tipo 2 (16.5%) rappresentano il segmento più promettente per il refactoring automatizzato: file con struttura isomorfa e poche differenze parametriche possono essere consolidati tramite moduli Terraform o parametrizzazione con variabili, riducendo significativamente la duplicazione.

I cloni di Tipo 3 (19.6%) indicano divergenza strutturale tra file originariamente identici — il segnale più forte di configuration drift attivo.

### Riepilogo dei Risultati

| Metrica | Valore |
|---------|--------|
| `.tf` paths (post name/path filters) | 683,962 |
| File analizzabili dal detector | 60,161 |
| File esclusi complessivi | 623,801 |
| Clone pair rilevate | 8,048 |
| Clone group | 2,287 |
| File coinvolti in almeno un clone | 5,874 |
| Cloni Type 1 | 5,143 (63.9%) |
| Cloni Type 2 | 1,329 (16.5%) |
| Cloni Type 3 | 1,576 (19.6%) |

---

## 6. Discussione

### 6.1 Interpretazione dei Risultati

I risultati ottenuti si allineano con la letteratura esistente sul clone detection. La presenza di cloni nel codice Terraform conferma le osservazioni di McIntosh et al. [2011] sui file di build (circa 50% di logica duplicata) e di Bessghaier et al. [2024] sui file Puppet (74% di file con smell). La predominanza di cloni esatti (Tipo 1, 63.9%) differisce dai risultati di Mondal et al. [2017] nel contesto general-purpose, dove i cloni near-miss sono più comuni. Questa differenza è spiegabile con la natura dichiarativa dell'IaC: gli ingegneri Terraform copiano interi file tra ambienti (dev → prod) senza modifiche, generando copie esatte, mentre nel codice imperativo le copie tendono a subire adattamenti immediati. I cloni di Tipo 2 (16.5%) e Tipo 3 (19.6%) confermano tuttavia che anche nel contesto IaC si osserva la progressiva divergenza delle copie nel tempo.

La scelta dell'approccio tree-based si è rivelata appropriata. Coerentemente con i risultati di Bellon et al. [2007], l'analisi strutturale tramite AST eccelle nel rilevamento di cloni di Tipo 2 e 3, dove gli approcci testuali e token-based mostrano limiti. In particolare, la capacità di rilevare file con blocchi identici ma in ordine diverso — un pattern frequente in Terraform dove l'ordine delle risorse è irrilevante — rappresenta un vantaggio concreto rispetto ai diff testuali.

Il nostro tool adotta una **clone detection a granularità di file** (coarse-grained), in contrasto con la detection a granularità di funzione o sottoalbero (fine-grained) tipica degli strumenti per codice general-purpose. Questa scelta è motivata da tre considerazioni specifiche del contesto IaC:

1. **L'unità di riuso in Terraform è il modulo (file/directory):** gli ingegneri Terraform copiano tipicamente interi file o intere directory di moduli, non singoli blocchi. La detection full-tree si allinea meglio al flusso di lavoro reale.
2. **La sintassi dichiarativa è intrinsecamente "clonata":** piccoli frammenti identici (es. configurazioni standard di bucket S3) sono la norma, non l'eccezione. La detection a livello di sottoalbero genererebbe un elevato numero di falsi positivi.
3. **Compromesso prestazioni-valore:** confrontare ogni sottoalbero con ogni altro avrebbe complessità O(N²) sul numero di nodi, mentre il confronto a livello di file ha complessità O(N²) sul numero di file (ordini di grandezza inferiore).

Yu et al. [2025] hanno dimostrato che non tutti i cloni sono negativi; alcuni rappresentano pratiche di riuso legittime. Il nostro sistema di classificazione e suggerimenti di refactoring tiene conto di questa osservazione: i cloni di Tipo 1 con strutture complesse sono segnalati per la deduplicazione, mentre i cloni di Tipo 2 con poche differenze parametriche ricevono suggerimenti di parametrizzazione che preservano il pattern originale.

### 6.2 Threats to Validity

#### Construct Validity

- **Modello di costo euristico.** L'algoritmo Zhang-Shasha utilizza un modello di costo unitario per tutte le operazioni di editing (inserimento, cancellazione, sostituzione). In realtà, non tutte le modifiche hanno lo stesso impatto nella configurazione Terraform: la modifica di un nome AMI potrebbe avere conseguenze molto diverse dalla modifica di un tag di naming. Un modello di costo pesato potrebbe migliorare la significatività della TED.
- **Mancanza di risoluzione semantica delle variabili.** Il tool confronta i valori letterali presenti nei file, senza risolvere i riferimenti a variabili (`var.X`), local values (`local.Y`) o data sources (`data.Z`). Due file che utilizzano la stessa variabile con valori diversi definiti altrove risulterebbero identici (falso negativo), mentre due file con valori identici espressi come letterale in uno e variabile nell'altro risulterebbero diversi (falso positivo).
- **Ordinamento delle liste.** L'algoritmo confronta gli elementi delle liste in ordine sequenziale. In Terraform, alcune liste (es. `ingress` rules in security group) sono semanticamente equivalenti indipendentemente dall'ordine. Ordini diversi della stessa lista generano una TED > 0, potenzialmente classificando come Type 3 un clone che è effettivamente Type 1 o Type 2.

#### Internal Validity

- **Bias di granularità file-level.** La scelta di operare a livello di file intero (anziché di sottoblocco) introduce un bias: file grandi con una porzione clonata e una porzione diversa risulteranno con TED elevata e non verranno rilevati come cloni parziali. Questo bias è mitigato dal fatto che in Terraform i file tendono ad essere focalizzati su singole risorse o gruppi di risorse correlate.
- **Complessità algoritmica e limiti di filtraggio.** La complessità dell'algoritmo Zhang-Shasha, pur ottimizzata dal bucketing e dal pruning, rimane elevata per file molto grandi. Il filtraggio dei file con meno di 100 nodi esclude potenzialmente cloni significativi in file di piccole dimensioni. Simmetricamente, il limite superiore di 500 nodi (`MAX_TREE_NODES`) esclude file di grandi dimensioni che potrebbero contenere cloni rilevanti; tuttavia, questa scelta è necessaria per garantire tempi di analisi ragionevoli. Il limite di profondità AST (`MAX_ZSS_DEPTH = 30`) tronca alberi molto profondi, potenzialmente perdendo informazione strutturale in configurazioni con annidamento estremo.
- **Timeout e completezza.** Il meccanismo di timeout per-progetto può interrompere l'analisi di progetti complessi prima del completamento, escludendo potenziali clone pair. Il sistema di checkpointing mitiga questo rischio consentendo di riprendere l'analisi con timeout più generosi.

#### External Validity

- **Rappresentatività del dataset.** I risultati sono limitati al dataset TerraDS e potrebbero non generalizzare a tutti i contesti di utilizzo di Terraform (es. codebase aziendali private, settori specifici, pratiche di team diversi).
- **Specificità del linguaggio.** Il tool è progettato esclusivamente per Terraform/HCL2. Sebbene l'approccio AST + TED sia concettualmente applicabile ad altri linguaggi IaC (Ansible/YAML, Puppet, CloudFormation/JSON), l'implementazione richiede parser e logiche di conversione specifici per ciascun linguaggio.

---

## 7. Conclusione e Sviluppi Futuri

In questo lavoro abbiamo proposto un tool di clone detection specifico per Infrastructure-as-Code basato su Abstract Syntax Tree e Tree Edit Distance. Il nostro contributo colma un gap nella letteratura, dove strumenti di clone detection per Terraform che combinano analisi strutturale, classificazione automatica e suggerimenti di refactoring non erano precedentemente disponibili.

I principali contributi del lavoro sono:

1. Una **mappatura della tassonomia classica dei code clone** (Type 1-4) al contesto specifico dell'Infrastructure-as-Code, con definizioni operative per ciascun tipo.
2. Un **tool di clone detection AST-based** per Terraform che utilizza l'algoritmo Zhang-Shasha per la Tree Edit Distance, con ottimizzazioni per la scalabilità (bucketing per signature, pruning per rapporto di dimensione, parallelizzazione con gestione dei future) e meccanismi di robustezza (timeout per-progetto con terminazione forzata dei worker, limite di profondità AST, limite superiore sulla dimensione degli alberi).
3. Un **sistema di classificazione automatica** basato sul rapporto tra TED e differenze parametriche, che distingue cloni esatti (Type 1), parametrizzati (Type 2) e near-miss (Type 3).
4. Un **generatore di suggerimenti di refactoring** che produce codice Terraform eseguibile, con strategie differenziate per parametrizzazione tramite tfvars e estrazione in moduli.
5. Un **sistema di checkpointing persistente** che salva lo stato dell'analisi su file JSON con scrittura atomica, consentendo di interrompere e riprendere l'analisi senza perdere i risultati parziali, e di generare report anche in caso di interruzione.
6. Una **test suite automatizzata** di 69 test che verifica la correttezza di ogni fase della pipeline, dalla conversione AST alla generazione dei suggerimenti di refactoring.

Come sviluppi futuri, identifichiamo cinque direzioni di ricerca:

**1. Consapevolezza semantica.** L'integrazione della risoluzione delle variabili e della valutazione parziale delle espressioni consentirebbe di ridurre i falsi negativi causati dalla mancata risoluzione dei riferimenti `var.X` e `local.Y`. Questa estensione aprirebbe anche alla rilevazione dei cloni di Tipo 4 (semantici), attualmente fuori dall'ambito del tool.

**2. Prefiltro basato su fingerprint.** L'adozione di tecniche di Locality-Sensitive Hashing (LSH) o hashing vettoriale per la pre-selezione delle coppie candidate ridurrebbe ulteriormente lo spazio di confronto, migliorando la scalabilità su dataset di grandi dimensioni senza sacrificare la recall.

**3. Subtree detection integrata.** L'estensione dalla detection a livello di file alla detection a livello di sotto-albero consentirebbe di identificare blocchi duplicati all'interno di file altrimenti diversi, superando il bias di granularità attualmente presente. L'output potrebbe includere la generazione automatica di moduli Terraform a partire dai sottoblocchi duplicati.

**4. Machine Learning per raccomandazioni.** Seguendo l'approccio di Yu et al. [2025], l'addestramento di modelli di classificazione per distinguere cloni "dannosi" da cloni "benigni" consentirebbe di prioritizzare i suggerimenti di refactoring, concentrando l'attenzione degli ingegneri sui cloni con il maggiore impatto sulla manutenibilità e la sicurezza.

**5. Supporto multi-linguaggio IaC.** Lo sviluppo di adapter per altri linguaggi IaC (Ansible/YAML, CloudFormation/JSON, Pulumi, Bicep) estenderebbe l'applicabilità del tool all'intero ecosistema Infrastructure-as-Code, consentendo analisi cross-tool e comparative.

| Sviluppo Futuro | Categoria | Difficoltà | Problema Affrontato |
|-----------------|-----------|------------|---------------------|
| Variable Resolution | Analisi semantica | Alta | Falsi negativi da riferimenti non risolti |
| Vector Hashing / LSH | Prestazioni | Media | Scalabilità su dataset grandi |
| Subtree Mining | Granularità | Alta | Bias file-level |
| ML Recommendations | Automazione | Alta | Prioritizzazione dei cloni |
| Multi-Language Support | Estensibilità | Media | Limitazione a Terraform |

---

## Riferimenti

- Baxter, I. D., Yahin, A., Moura, L., Sant'Anna, M., & Bier, L. (1998). Clone Detection Using Abstract Syntax Trees. *Proceedings of the International Conference on Software Maintenance (ICSM)*.
- Bellon, S., Koschke, R., Antoniol, G., Krinke, J., & Merlo, E. (2007). Comparison and Evaluation of Clone Detection Tools. *IEEE Transactions on Software Engineering*, 33(9), 577–591.
- Bessghaier, N., Ouni, A., & Mkaouer, M. W. (2024). On the Prevalence, Co-occurrence, and Impact of Infrastructure-as-Code Smells. *IEEE SANER 2024*.
- Cardoen, A. (2024). Towards an Empirical Analysis of Code Cloning and Code Reuse in CI/CD Ecosystems. *BENEVOL 2024*.
- HashiCorp. (2024). Detecting and Managing Drift with Terraform. https://www.hashicorp.com/blog/detecting-and-managing-drift-with-terraform
- Juergens, E., Deissenboeck, F., Hummel, B., & Wagner, S. (2009). Do Code Clones Matter? *Proceedings of the 31st International Conference on Software Engineering (ICSE)*.
- McIntosh, S., Adams, B., & Hassan, A. E. (2011). An Empirical Study of Build Maintenance Effort. *Proceedings of the 33rd International Conference on Software Engineering (ICSE)*.
- Mondal, M., Roy, C. K., & Schneider, K. A. (2017). Bug Propagation through Code Cloning: An Empirical Study. *IEEE International Conference on Software Maintenance and Evolution (ICSME)*.
- Oliveira, D., et al. (2025). A Defect Taxonomy for Infrastructure as Code: A Replication Study. *arXiv:2505.01568*.
- Rahman, A., & Williams, L. (2019). Security Smells in Infrastructure as Code Scripts. *IEEE/ACM International Conference on Mining Software Repositories (MSR)*.
- Roy, C. K., & Cordy, J. R. (2009). Comparison and Evaluation of Code Clone Detection Techniques and Tools: A Qualitative Approach. *Science of Computer Programming*, 74, 470–495.
- Selim, G. M., Foo, K. C., & Zou, Y. (2010). Studying the Impact of Clones on Software Defects. *IEEE Working Conference on Reverse Engineering (WCRE)*.
- Sharma, T., Fragkoulis, M., & Spinellis, D. (2016). Does Your Configuration Code Smell? *Proceedings of the 13th International Conference on Mining Software Repositories (MSR)*.
- TerraDS. (2024). TerraDS: Terraform Dataset for Infrastructure-as-Code Analysis. Zenodo. https://zenodo.org/records/14217386
- Tsuru, E., Washizaki, H., & Fukazawa, Y. (2021). Type-2 Code Clone Detection for Dockerfiles. *IEEE 15th International Workshop on Software Clones (IWSC)*.
- Yu, D., et al. (2025). An Empirical Study on the Characteristics of Reusable Code Clones. *ACM Transactions on Software Engineering and Methodology (TOSEM)*.
- Zhang, K., & Shasha, D. (1989). Simple Fast Algorithms for the Editing Distance between Trees and Related Problems. *SIAM Journal on Computing*, 18(6), 1245–1262.
