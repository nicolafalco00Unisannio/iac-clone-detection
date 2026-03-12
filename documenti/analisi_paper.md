# Analisi Comparativa dei Paper Scientifici su Code Clone Detection e Infrastructure-as-Code

---

## 1. Riassunti Individuali

---

### Paper 1 - Roy & Cordy (2009) - "Comparison and Evaluation of Code Clone Detection Techniques and Tools: A Qualitative Approach"
**Fonte:** Science of Computer Programming, Vol. 74, pp. 470-495

Questo paper rappresenta il lavoro fondamentale che definisce la tassonomia classica dei cloni di codice. Gli autori forniscono una comparazione qualitativa e una valutazione completa di tutte le tecniche e gli strumenti di clone detection disponibili al momento della pubblicazione.

**Definizioni fondamentali:**
- **Type-1:** Frammenti identici eccetto variazioni in whitespace, layout e commenti.
- **Type-2:** Frammenti sintatticamente identici eccetto variazioni in identificatori, letterali, tipi, whitespace, layout e commenti.
- **Type-3:** Frammenti copiati con ulteriori modifiche come statement aggiunti, rimossi o modificati.
- **Type-4:** Frammenti che eseguono la stessa computazione ma sono implementati con varianti sintattiche diverse.

**Tassonomia delle tecniche:**
Il paper classifica le tecniche di clone detection in 5 categorie principali:

| Categoria | Tecnica | Strumenti rappresentativi |
|-----------|---------|--------------------------|
| Text-based | Hashing, dotplot, LSI | Johnson, Duploc, NICAD, Simian |
| Token-based | Suffix-tree, suffix-array, data mining | Dup, CCFinder, CP-Miner, RTF |
| Tree-based | AST matching, metrics per AST | CloneDr, Deckard, cpdetector |
| Metrics-based | Confronto vettori metriche | Davey, Mayrand et al. |
| Graph-based | Isomorfismo PDG | Duplix, Komondoor |

**Valutazione basata su scenari di editing:** Gli autori definiscono una tassonomia di scenari di editing ipotetico (copia con modifiche) e stimano qualitativamente la capacità di ciascuna tecnica di rilevare i cloni risultanti da tali scenari.

**Rilevanza per il progetto IaC:** Questo paper fornisce le fondamenta teoriche per la classificazione dei cloni (Type 1-4) adottata anche nel tool di clone detection per Terraform analizzato.

---

### Paper 2 - Tsuru et al. (2021) - "Type-2 Code Clone Detection for Dockerfiles"
**Fonte:** IEEE 15th International Workshop on Software Clones (IWSC), 2021

Questo paper propone una tecnica di rilevamento di cloni di Tipo 2 specificamente progettata per i Dockerfile, riconoscendo che il codice infrastrutturale ha caratteristiche sintattiche diverse dai linguaggi di programmazione tradizionali.

**Metodologia:**
1. Costruzione di AST dai Dockerfile (usando la tecnica di Henkel et al.)
2. Normalizzazione dei token (variabili temporanee, path, URL, username, tag, alias di opzioni, ordine parametri)
3. Hashing per istruzione
4. Separazione della sintassi Docker dalla sintassi Shell
5. Applicazione dell'algoritmo suffix array per ciascuna sintassi
6. Output dei clone set

**Token normalizzati vs. non normalizzati:**

| Token normalizzati | Motivazione |
|-------------------|-------------|
| Variabili temporanee (ARG) | Non influenzano i processi esterni al container |
| Path di file | Variazioni non influenzano il comportamento |
| URL | Non influenzano risorse esterne al container |
| Username/group | Variazioni non influenzano il comportamento |
| Tag delle immagini (FROM) | Differenze funzionali insignificanti |
| Ordine parametri/opzioni | Comandi equivalenti con ordine diverso |
| Alias di opzioni | Comandi equivalenti (es. `rm -fr` vs `rm --force --recursive`) |

**Risultati sperimentali (4,817 Dockerfile, 725 repository GitHub):**

| Metrica | Senza normalizzazione | Con normalizzazione |
|---------|----------------------|---------------------|
| Clone segments (both syntaxes) | 930,134 | 987,597 |
| Clone sets (both syntaxes) | 204,840 | 203,103 |
| Segmenti per clone set | 4.54 | 4.86 |
| Lunghezza segmenti per clone set | 20.78 | 21.30 |
| Precisione (Docker syntax) | 100% | 95.31% |
| Precisione (Shell syntax) | 98.70% | 98.44% |
| Precisione (Both) | 99.48% | 96.09% |

**Pattern individuati:** Distribution building pattern (13 clone segments da 5 repository) e software installation pattern con make (12 clone segments da 5 repository).

**Rilevanza per il progetto IaC:** Dimostra l'applicabilita del clone detection a file di configurazione infrastrutturale. La normalizzazione dei token e la separazione delle sintassi sono concetti applicabili anche a Terraform.

---

### Paper 3 - Bellon et al. (2007) - "Comparison and Evaluation of Clone Detection Tools"
**Fonte:** IEEE Transactions on Software Engineering, Vol. 33, No. 9, pp. 577-591

Questo paper presenta l'esperimento quantitativo piu completo del suo tempo per valutare strumenti di clone detection. Sei tool sono stati confrontati su 8 sistemi C e Java (circa 850 KLOC totali).

**Strumenti valutati:**

| Tool | Tecnica | Autore/Team |
|------|---------|-------------|
| Dup | Token-based, suffix-tree | Baker |
| CCFinder | Token-based, suffix-tree normalizzato | Kamiya et al. |
| CloneDr | Tree-based, AST hashing + matching | Baxter et al. |
| cpdetector | Tree-based, AST serializzato + suffix-tree | Koschke et al. |
| Merlo (CLAN) | Metrics-based | Merlo et al. |
| Duplix | Graph-based, PDG | Krinke |

**Metodologia di valutazione:**
- Corpus di riferimento costruito manualmente da un "oracolo" indipendente (Stefan Bellon)
- 2% dei 325,935 candidati totali esaminati manualmente (77 ore di lavoro umano)
- Due metriche: **good-match** (intersezione dei frammenti) e **ok-match** (contenimento dei frammenti)
- Soglia p = 0.7 per entrambe le metriche
- Iniezione di "cloni segreti" per validazione

**Definizioni operative:**
- Minimo 6 righe per clone
- Cloni sintatticamente completi (sostituibili con chiamate a funzione)
- Frammenti definiti come (filename, start_line, end_line)

**Risultati chiave:**
- Gli approcci token-based (CCFinder) mostrano il miglior compromesso recall/precision per cloni Type-1
- Gli approcci tree-based eccellono per cloni Type-2
- Gli approcci graph-based (Duplix) trovano cloni unici non rilevati da altri, ma con precision piu bassa
- Nessun singolo tool domina su tutti i tipi e tutti i programmi

**Rilevanza per il progetto IaC:** Questo paper dimostra che approcci tree-based (come quello usato nel tool IaC con Zhang-Shasha TED) sono particolarmente adatti per cloni Type-2 e Type-3, validando la scelta architetturale del progetto.

---

### Paper 4 - McIntosh et al. (2011) - "An Empirical Study of Build Maintenance Effort"
**Fonte:** ICSE 2011, ACM

Questo studio empirico analizza lo sforzo di manutenzione dei sistemi di build in 10 progetti open-source, dimostrando che i file di configurazione (build system) richiedono uno sforzo di manutenzione significativo, spesso trascurato.

**Progetti analizzati:** 10 sistemi open-source di diversa grandezza e dominio (Java e C/C++).

**Risultati principali:**

| Metrica | Valore |
|---------|--------|
| Build coupling (accoppiamento build-source) | 2-10% dei commit |
| Overhead di manutenzione build su sviluppo source | Fino al 27% |
| Percentuale di logica di build duplicata (Type 1) in sistemi Java | ~50% |
| Inconsistent changes in cloni di build | Presenti e problematiche |

**Risultati chiave:**
- In sistemi Java, meta delle righe di logica di build sono clonate almeno una volta
- Le "inconsistent changes" e le "prolonged fixes", gia note come problemi dei cloni nel codice general-purpose, affliggono anche i file di configurazione di build
- Il build coupling varia dal 2% al 10% dei commit, suggerendo che i cambiamenti al build system sono frequenti e legati ai cambiamenti del codice sorgente

**Rilevanza per il progetto IaC:** Evidenzia che i file di configurazione (inclusi build e IaC) soffrono degli stessi problemi di clonazione del codice tradizionale, giustificando l'applicazione del clone detection a Terraform.

---

### Paper 5 - Juergens et al. (2009) - "Do Code Clones Matter?"
**Fonte:** ICSE 2009 / arXiv:1701.05472

Studio empirico fondamentale che risponde alla domanda cruciale: i cloni causano davvero difetti? Lo studio analizza 5 grandi sistemi software e dimostra che le inconsistenze nei cloni sono fortemente correlate a difetti reali.

**Sistemi analizzati:** 5 sistemi industriali e open-source.

**Risultati quantitativi:**

| Metrica | Valore |
|---------|--------|
| Clone group analizzati | 1,427 |
| Gruppi con inconsistenze | 52% |
| Difetti confermati | 107 |
| Densita di difetti nei cloni | 48.1 difetti/kLOC |
| Densita di difetti nel codice non clonato | Significativamente inferiore |

**Conclusioni principali:**
- Il 52% dei clone group contiene almeno un'inconsistenza
- Le inconsistenze nei cloni sono fortemente correlate a difetti reali del software
- La densita di difetti nel codice clonato (48.1 difetti/kLOC) e nettamente superiore rispetto al codice non clonato
- I cloni di Tipo 3 sono i piu problematici in termini di inconsistenze

**Rilevanza per il progetto IaC:** Giustifica fortemente la necessita di un tool di clone detection: se il 52% dei clone group contiene inconsistenze che portano a difetti, rilevare i cloni e fondamentale per la qualita del software (e del codice IaC).

---

### Paper 6 - Yu et al. (2025) - "An Empirical Study on the Characteristics of Reusable Code Clones"
**Fonte:** ACM Transactions on Software Engineering and Methodology (TOSEM)

Questo studio adotta una prospettiva diversa: invece di concentrarsi solo sugli aspetti negativi dei cloni, analizza le caratteristiche dei cloni "riusabili" - quelli che vengono correttamente gestiti e riutilizzati in piu progetti.

**Dataset:** 60 progetti open-source, 538K commit.

**Metodologia:** Machine learning (Random Forest, Logistic Regression, SVM) per predire quali cloni sono riusabili basandosi su feature del codice.

**Risultati:**

| Modello | AUC | F1-Score |
|---------|-----|----------|
| Random Forest | 0.73 | 0.89 |
| Logistic Regression | ~0.68 | ~0.84 |
| SVM | ~0.65 | ~0.82 |

**Feature piu importanti per predire la riusabilita:**
1. **CountFollowers** (numero di "seguaci" del clone) - la piu importante
2. Complessita ciclomatica
3. Dimensione del frammento (LOC)
4. Numero di parametri

**Rilevanza per il progetto IaC:** Suggerisce che non tutti i cloni sono negativi. Il tool IaC potrebbe classificare i cloni non solo per tipo ma anche per "riusabilita", aiutando gli utenti a concentrare gli sforzi di refactoring sui cloni davvero problematici.

---

### Paper 7 - Selim et al. (2010) - "Studying the Impact of Clones on Software Defects"
**Fonte:** IEEE Working Conference on Reverse Engineering (WCRE), 2010

Questo paper studia l'impatto dei cloni sui difetti software utilizzando la **survival analysis** (modelli di Cox), un approccio statistico sofisticato che modella il "rischio" di un metodo di sperimentare un difetto nel tempo.

**Sistemi analizzati:**

| Sistema | Linguaggio | LOC (ultima revisione) | Revisioni |
|---------|-----------|----------------------|-----------|
| Apache Ant | Java | - | ~4000 |
| ArgoUML | Java | - | ~2000+ |

**Tool di clone detection utilizzati:** CCFinder (token-based) e Simian (string-based).

**Predittori nei modelli Cox:**

| Categoria | Predittore | Descrizione |
|-----------|-----------|-------------|
| Controllo | LOC | Righe di codice |
| Controllo | tokens | Numero di token |
| Controllo | nesting | Livelli di annidamento massimo |
| Controllo | cyclo | Complessita ciclomatica |
| Clonazione | clone | Se il metodo contiene cloni |
| Clonazione | NumCloneSib | Numero di clone sibling |
| Clonazione | NumDefectSib | Numero di sibling difettosi |
| Clonazione | numdefectnumprev | Densita di difetti storici |

**Risultati principali:**
- LOC e la storia dei difetti (numdefectnumprev) sono i predittori di controllo piu significativi
- Il numero di sibling difettosi (NumDefectSib) e significativo nel determinare i difetti
- La defect-proneness dei metodi clonati e specifica del sistema analizzato
- I predittori tradizionali (controllo) possono gia predire bene i difetti: aggiungere predittori di clonazione non migliora sempre la correlazione
- I metodi con una "commit history" piu lunga dovrebbero ricevere piu risorse di ispezione

**Rilevanza per il progetto IaC:** Suggerisce che la sola presenza di cloni non e sufficiente a predire difetti; bisogna considerare la storia evolutiva e il contesto. Il tool IaC potrebbe beneficiare di un'analisi della storia dei commit per prioritizzare i cloni piu rischiosi.

---

### Paper 8 - Cardoen (2024) - "Towards an Empirical Analysis of Code Cloning and Code Reuse in CI/CD Ecosystems"
**Fonte:** BENEVOL 2024 (23rd Belgium-Netherlands Software Evolution Workshop)

Questo e un paper di piano di ricerca dottorale che delinea uno studio empirico sul code cloning nei file di configurazione CI/CD, con focus iniziale su GitHub Actions.

**Ipotesi centrali:**
- I file di configurazione CI/CD soffrono degli stessi problemi di clonazione del codice general-purpose
- I maintainer creano nuove configurazioni CI/CD tramite copy-paste da configurazioni esistenti o starter template
- La duplicazione del codice nei workflow porta a problemi di manutenibilita

**Dataset:** 43K+ repository, 2.5M+ file workflow, 219K+ storie di workflow (estratti con il tool "gigawork").

**Research Questions:**
- RQ1: Come definire e identificare i cloni nei workflow?
- RQ2: Quanto sono prevalenti i cloni nei file workflow?
- RQ3: Quali sono le caratteristiche dei cloni?
- RQ4: Da dove provengono i cloni?
- RQ5: Come co-evolvono i cloni?
- RQ6: Qual e l'impatto dei cloni?
- RQ7: Vengono introdotti componenti riusabili nei workflow?
- RQ8: Come aiutare i maintainer a evitare i cloni?
- RQ9: Quali sono le somiglianze tra cloni di ecosistemi CI/CD diversi?

**Meccanismi di riuso in GitHub Actions:**
1. **Reusable Actions** (componenti riusabili dal Marketplace)
2. **Reusable Workflows** (workflow richiamabili da altri workflow)
3. **Composite Actions** (bundle di Actions come singolo step)
4. **Starter Workflows** (template forniti da GitHub)

**Rilevanza per il progetto IaC:** Conferma che l'analisi dei cloni nei file di configurazione (inclusi IaC e CI/CD) e un'area di ricerca emergente e rilevante. La distinzione tra meccanismi di riuso (Actions, moduli Terraform) e copy-paste e cruciale.

---

### Paper 9 - Mondal et al. (2017) - "Bug Propagation through Code Cloning: An Empirical Study"
**Fonte:** IEEE ICSME 2017

Primo studio empirico dedicato alla propagazione di bug attraverso il code cloning. Definisce due pattern formali di propagazione e li applica a 4 sistemi open-source Java.

**Sistemi analizzati:**

| Sistema | Linguaggio | LOC (ultima rev.) | Revisioni |
|---------|-----------|-------------------|-----------|
| jEdit | Java | 191,804 | 4,000 |
| Freecol | Java | 91,626 | 1,950 |
| Carol | Java | 25,091 | 1,700 |
| Jabref | Java | 45,515 | 1,545 |

**Due pattern di bug propagation:**
- **Pattern 1:** Due frammenti creati nella stessa revisione (probabile copy-paste), entrambi contengono lo stesso bug, entrambi corretti con similarity preserving co-change.
- **Pattern 2:** Un frammento creato da un preesistente (probabile copia); il bug del frammento originale viene propagato alla copia.

**Risultati quantitativi:**

| Metrica | Type 1 | Type 2 | Type 3 |
|---------|--------|--------|--------|
| % cloni coinvolti in bug propagation (overall) | ~0.07% | ~1.9% | ~0.7% |
| % bug-fix cloni con bug propagati (overall) | 4.76% | 12.82% | 16.22% |
| % commit bug-fix indicanti bug propagati (max) | 28.57% | 25% | 19.56% |
| Bug propagation clone pairs (Carol, Type 3) | - | - | 130 |

**Risultati dall'analisi manuale (133 coppie di Carol):**
- 132 su 133 coppie: nessun frammento modificato prima del bug-fix
- 131 su 133 coppie: i frammenti sono metodi completi
- La propagazione avviene principalmente nei cloni creati nella stessa revisione

**Conclusioni principali:**
- Fino al **33%** dei clone fragment che sperimentano bug-fix possono contenere bug propagati
- Il **28.57%** dei bug-fix commit per i cloni puo riguardare bug propagati
- I cloni near-miss (Type 2 e Type 3) sono i principali vettori di propagazione
- I cloni Type 1 hanno la minore probabilita di propagare bug
- I cloni metodo sono i piu coinvolti nella propagazione

**Rilevanza per il progetto IaC:** Conferma che i cloni non sono solo un problema estetico ma un vettore di propagazione di bug. Nel contesto Terraform, un bug in un modulo copiato puo propagarsi a tutte le copie, rendendo il clone detection essenziale.

---

### Paper 10 - Bessghaier et al. (2024) - "On the Prevalence, Co-occurrence, and Impact of Infrastructure-as-Code Smells"
**Fonte:** IEEE SANER 2024

Studio empirico su 82 progetti Puppet open-source che analizza la prevalenza, co-occorrenza e impatto degli IaC smell sulla manutenibilita e la defect-proneness.

**Dataset:**

| Statistica | Valore |
|-----------|--------|
| Progetti analizzati | 82 |
| Commit totali | 19,641 |
| File IaC smelly | 1,462 |
| File IaC non-smelly | 501 |
| Istanze di smell totali | 5,213 |
| Periodo studiato | 2011-2023 |

**12 tipi di IaC smell analizzati:**

| Smell | Livello | Prevalenza nei progetti | % negli smell totali |
|-------|---------|------------------------|---------------------|
| Insufficient Modularization (DIM) | Design/File | 100% | 30.57% |
| Tightly Coupled Modules (DTC) | Design/File | 96.42% | 21.35% |
| Multifaceted Abstraction (DMF) | Design/File | 95.23% | 21.59% |
| Unstructured Module (DUM) | Design/Module | 100% | 9.44% |
| Weakened Modularity (DWM) | Design/File | 59.52% | 5% |
| Missing Dependency (DMP) | Design/Module | 75.29% | 5.73% |
| Incomplete Conditional (IIC) | Implementation/File | 34.52% | 2.09% |
| Complex Expression (ICE) | Implementation/File | 25% | 1.42% |
| Incomplete Tasks (IIT) | Implementation/File | 23.8% | 1.23% |
| Deprecated Statement (IDS) | Implementation/File | 10.71% | 0.32% |
| Dense Structure (DDS) | Design/Module | 32.94% | 0.63% |
| Deficient Encapsulation (DDE) | Design/Module | 9.41% | 0.59% |

**Risultati chiave:**

| Metrica | Valore |
|---------|--------|
| % file IaC smelly | 74% |
| % file smelly con 2+ smell co-occorrenti | 52.29% |
| Frequenza di modifica file smelly vs non-smelly | **3.8x** piu frequente |
| Code churn file smelly vs non-smelly | **3.1x** maggiore |
| Defect-proneness file smelly vs non-smelly | **3.3x** maggiore |
| Persistenza difetti in file smelly | 1.65 commit in piu |

**Co-occorrenza piu forte:** {Deficient Encapsulation -> Dense Structure} con Lift = 40.17

**Rilevanza per il progetto IaC:** Dimostra quantitativamente che i problemi di qualita nel codice IaC (inclusa la duplicazione) hanno impatti reali e misurabili sulla manutenibilita e sui difetti. I file IaC "smelly" sono 3.3x piu inclini ai difetti.

---

### Paper 11 - Oliveira et al. (2025) - "A Defect Taxonomy for Infrastructure as Code: A Replication Study"
**Fonte:** arXiv:2505.01568

Studio di replicazione che verifica la tassonomia dei difetti IaC proposta originariamente da Rahman et al. (la "Gang of Eight"), estendendola a un dataset molto piu ampio.

**Dataset:**

| Statistica | Valore |
|-----------|--------|
| Repository analizzati | 541 |
| Commit analizzati | ~570,000 |
| Tool IaC | Ansible, Chef, Puppet |
| Difetti classificati | Migliaia |

**Tassonomia "Gang of Eight" confermata:**

| Categoria di difetto | Prevalenza |
|---------------------|------------|
| Configuration Data | Piu prevalente |
| Conditional | Seconda categoria |
| Dependency | Terza categoria |
| Documentation | - |
| Idempotency | - |
| Security | - |
| Service | - |
| Syntax | - |

**Risultati principali:**
- La tassonomia originale "Gang of Eight" e confermata come valida su un dataset molto piu grande
- **Configuration Data** e la categoria di difetto piu prevalente nell'IaC
- I difetti sono distribuiti diversamente tra Ansible, Chef e Puppet
- La replicazione conferma la robustezza della classificazione originale

**Rilevanza per il progetto IaC:** I difetti di tipo "Configuration Data" (che includono valori hard-coded, duplicazioni di configurazione) sono i piu comuni nell'IaC. Il clone detection puo intercettare molti di questi difetti prima che causino problemi in produzione.

---

## 2. Confronto Comparativo

### 2.1 Tabella Sinottica dei Paper

| # | Paper | Anno | Focus | Ambito | Metodo | Dataset |
|---|-------|------|-------|--------|--------|---------|
| 1 | Roy & Cordy | 2009 | Tassonomia e confronto tecniche | Code clone general | Qualitativo | 30+ tool |
| 2 | Tsuru et al. | 2021 | Clone detection Dockerfile | IaC (Docker) | AST + suffix array | 4,817 file, 725 repo |
| 3 | Bellon et al. | 2007 | Valutazione quantitativa tool | Code clone general | Oracolo umano | 850 KLOC, 6 tool |
| 4 | McIntosh et al. | 2011 | Manutenzione build system | Build/Config files | Mining repository | 10 progetti |
| 5 | Juergens et al. | 2009 | Impatto cloni su difetti | Code clone general | Analisi inconsistenze | 5 sistemi, 1,427 gruppi |
| 6 | Yu et al. | 2025 | Cloni riusabili | Code clone general | Machine Learning | 60 progetti, 538K commit |
| 7 | Selim et al. | 2010 | Cloni e difetti (survival) | Code clone general | Cox Models | 2 sistemi Java |
| 8 | Cardoen | 2024 | Piano PhD - cloni CI/CD | CI/CD (GitHub Actions) | Mixed-method | 43K+ repo, 2.5M+ file |
| 9 | Mondal et al. | 2017 | Propagazione bug via cloni | Code clone general | Genealogia cloni | 4 sistemi Java |
| 10 | Bessghaier et al. | 2024 | IaC smell prevalenza/impatto | IaC (Puppet) | Mining + statistico | 82 progetti, 19,641 commit |
| 11 | Oliveira et al. | 2025 | Tassonomia difetti IaC | IaC (Ansible/Chef/Puppet) | Replicazione | 541 repo, 570K commit |

### 2.2 Confronto per Tipo di Contributo

| Contributo | Paper |
|-----------|-------|
| **Definizioni e tassonomie** | Paper 1 (clone types), Paper 11 (defect taxonomy) |
| **Valutazione tool/tecniche** | Paper 1 (qualitativo), Paper 3 (quantitativo) |
| **Impatto cloni su difetti** | Paper 5, Paper 7, Paper 9 |
| **Clone detection per IaC/config** | Paper 2 (Docker), Paper 4 (build), Paper 8 (CI/CD) |
| **Qualita e smell IaC** | Paper 10, Paper 11 |
| **Aspetti positivi dei cloni** | Paper 6 |

### 2.3 Confronto Quantitativo dell'Impatto dei Cloni

| Paper | Metrica | Valore | Interpretazione |
|-------|---------|--------|-----------------|
| Paper 5 | % clone group con inconsistenze | **52%** | Oltre meta dei gruppi di cloni e inconsistente |
| Paper 5 | Densita difetti nei cloni | **48.1 diff/kLOC** | Altissima densita di difetti nel codice clonato |
| Paper 9 | % bug-fix cloni con bug propagati | Fino a **33%** | Un terzo dei bug-fix nei cloni riguarda bug propagati |
| Paper 9 | % commit indicanti bug propagati | Fino a **28.57%** | Quasi un terzo dei commit e per bug propagati |
| Paper 10 | Modifica file smelly vs non-smelly | **3.8x** | File IaC "smelly" modificati quasi 4 volte piu spesso |
| Paper 10 | Defect-proneness smelly vs non-smelly | **3.3x** | File IaC "smelly" 3.3 volte piu inclini ai difetti |
| Paper 4 | % logica di build duplicata (Java) | **~50%** | Meta della logica di build e clonata |
| Paper 2 | Precisione Type-2 detection (Docker) | **95%** | Alta precisione per clone detection in IaC |

### 2.4 Confronto delle Tecniche di Clone Detection

| Approccio | Vantaggi | Svantaggi | Usato in |
|-----------|----------|-----------|----------|
| **Text-based** | Semplice, language-independent | Bassa recall per Type-2+ | Paper 1 (NICAD), Paper 3 (Simian) |
| **Token-based** | Buon compromesso recall/precision | Non rispetta struttura sintattica | Paper 1 (CCFinder), Paper 3, Paper 7 |
| **Tree-based (AST)** | Eccelle per Type-2 e Type-3 | Richiede parser completo | Paper 1 (CloneDr), Paper 2 (Dockerfile AST), **Progetto IaC** |
| **Metrics-based** | Scalabile, veloce | Bassa precision | Paper 1, Paper 3 |
| **Graph-based (PDG)** | Trova cloni semantici unici | Computazionalmente costoso | Paper 1, Paper 3 |
| **ML-based** | Predice riusabilita | Richiede training data | Paper 6 |
| **TED (Tree Edit Distance)** | Misura distanza strutturale precisa | Computazionalmente O(n^4) | **Progetto IaC** (Zhang-Shasha) |

### 2.5 Evoluzione Temporale della Ricerca

| Periodo | Focus | Paper rappresentativi |
|---------|-------|----------------------|
| 2007-2009 | Definizioni, tassonomie, valutazione tool | Paper 1, Paper 3 |
| 2009-2011 | Impatto dei cloni su difetti e manutenzione | Paper 4, Paper 5, Paper 7 |
| 2017 | Propagazione bug attraverso cloni | Paper 9 |
| 2021 | Clone detection per codice infrastrutturale | Paper 2 |
| 2024-2025 | IaC quality, CI/CD cloning, difetti IaC | Paper 8, Paper 10, Paper 11 |

---

## 3. Deduzioni e Riflessioni

### 3.1 I cloni nel codice infrastrutturale sono un problema reale e misurabile

I dati raccolti dai paper analizzati convergono su una conclusione chiara: **la duplicazione del codice, sia nel codice tradizionale che in quello infrastrutturale, e un fattore di rischio significativo**.

- Paper 5 dimostra che il **52% dei clone group** contiene inconsistenze correlate a difetti reali (Juergens et al., 2009).
- Paper 10 quantifica che i file IaC "smelly" sono **3.3 volte piu inclini ai difetti** rispetto ai file non-smelly (Bessghaier et al., 2024).
- Paper 4 rivela che **circa il 50% della logica di build** nei sistemi Java e clonata (McIntosh et al., 2011).
- Paper 11 conferma che i difetti di tipo "Configuration Data" (che includono duplicazioni) sono i piu prevalenti nell'IaC (Oliveira et al., 2025).

### 3.2 I cloni near-miss sono piu pericolosi dei cloni identici

Un risultato ricorrente in piu paper e che i cloni Type-2 e Type-3 (near-miss) sono piu problematici dei cloni Type-1 (identici):

- Paper 9: i cloni Type-3 mostrano la piu alta intensita di propagazione bug (**16.22%** dei bug-fix cloni), rispetto a Type-2 (12.82%) e Type-1 (4.76%) (Mondal et al., 2017).
- Paper 5: le inconsistenze piu frequenti si trovano nei cloni con modifiche (Type-3) (Juergens et al., 2009).
- Paper 7: la defect-proneness varia per tipo di clone e per sistema, ma i cloni near-miss tendono ad essere piu problematici (Selim et al., 2010).

Questa evidenza supporta la scelta del progetto IaC di utilizzare Tree Edit Distance per rilevare anche cloni near-miss con modifiche strutturali.

### 3.3 Il clone detection per IaC richiede approcci specializzati

I paper che trattano specificamente codice infrastrutturale evidenziano sfide uniche:

- Paper 2 dimostra che i Dockerfile sono linguaggi annidati (Docker + Shell syntax) che richiedono normalizzazione specifica dei token e separazione delle sintassi (Tsuru et al., 2021).
- Paper 4 mostra che i file di build hanno pattern di duplicazione diversi dal codice tradizionale (McIntosh et al., 2011).
- Paper 8 ipotizza che i file di configurazione CI/CD richiedano algoritmi di clone detection adattati alla loro sintassi YAML specifica (Cardoen, 2024).

Il progetto di clone detection per Terraform affronta queste sfide con un approccio **AST-based + Tree Edit Distance** che:
1. Parsa HCL2 in strutture dati Python
2. Converte in alberi ZSS per il confronto strutturale
3. Applica bucketing per tipo di risorsa (ottimizzazione)
4. Classifica i cloni in Type-1, Type-2, Type-3 in base alla distanza TED

### 3.4 Non tutti i cloni sono negativi

Paper 6 (Yu et al., 2025) introduce una prospettiva importante: alcuni cloni sono "riusabili" e rappresentano pratiche di sviluppo legittime. Con un modello Random Forest (AUC = 0.73), gli autori riescono a predire quali cloni saranno riusati positivamente.

Anche Paper 7 (Selim et al., 2010) e Paper 8 (Cardoen, 2024) riconoscono che la clonazione puo essere una pratica ragionevole in certi contesti. Nel mondo IaC, copiare un modulo Terraform ben testato puo essere piu sicuro che riscriverlo da zero.

**Implicazione per il progetto IaC:** Il tool potrebbe beneficiare di una classificazione dei cloni non solo per tipo (1-3) ma anche per "rischio", considerando:
- Eta del clone (commit history)
- Numero di copie (clone siblings)
- Presenza di inconsistenze tra le copie
- Possibilita di estrazione in modulo riusabile

### 3.5 La tassonomia dei difetti IaC converge sulla duplicazione

Paper 11 conferma la tassonomia "Gang of Eight" per i difetti IaC, con **Configuration Data** come categoria piu prevalente. Questa categoria include:
- Valori hard-coded ripetuti
- Configurazioni duplicate
- Parametri inconsistenti

Paper 10 aggiunge che gli IaC smell legati alla modularita (Insufficient Modularization, Tightly Coupled Modules) sono i piu diffusi, presenti nel 96-100% dei progetti. Entrambi i tipi di problemi sono direttamente rilevabili tramite clone detection.

### 3.6 Sintesi: il progetto IaC si colloca in un gap della ricerca

Dalla rassegna emerge un **gap significativo** nella letteratura: mentre esistono studi su:
- Clone detection per codice general-purpose (Paper 1, 3, 5, 6, 7, 9)
- Clone detection per Dockerfile (Paper 2)
- Clone detection per build system (Paper 4)
- Cloni in CI/CD (Paper 8 - ancora in fase di ricerca)
- Qualita e difetti IaC per Puppet/Ansible/Chef (Paper 10, 11)

**Non esiste ancora uno studio dedicato al clone detection per Terraform** che combini:
1. Parsing HCL2 in AST
2. Tree Edit Distance per confronto strutturale
3. Classificazione automatica dei tipi di clone
4. Suggerimenti di refactoring (estrazione moduli, variabilizzazione)

Il progetto IaC analizzato colma esattamente questo gap, applicando tecniche consolidate (tree-based detection come in Paper 1, 2, 3) al contesto specifico di Terraform, con un approccio che tiene conto delle peculiarita del linguaggio HCL2.

---

## 4. Tabella Riassuntiva Finale

| Aspetto | Evidenza dalla letteratura | Implicazione per il clone detection IaC |
|---------|---------------------------|----------------------------------------|
| Prevalenza cloni | 7-23% del codice tradizionale (Paper 1), ~50% build logic (Paper 4), 74% file IaC smelly (Paper 10) | Alta probabilita di trovare cloni in codice Terraform |
| Impatto su difetti | 52% clone group con inconsistenze (Paper 5), 3.3x defect-proneness (Paper 10) | Clone detection puo prevenire difetti significativi |
| Bug propagation | Fino al 33% dei bug-fix cloni (Paper 9) | Rilevare cloni previene la propagazione di bug |
| Tipo piu pericoloso | Near-miss (Type 2-3) piu problematici (Paper 5, 9) | TED-based detection e ideale per catturare Type 2-3 |
| Tecnica ottimale | Tree-based eccelle per Type 2-3 (Paper 1, 3) | Approccio AST + TED del progetto e ben fondato |
| Non tutti i cloni sono negativi | Cloni riusabili esistono (Paper 6) | Classificare cloni per rischio, non solo per tipo |
| IaC ha sfide uniche | Linguaggi annidati, sintassi specifica (Paper 2, 8) | Parser specifico HCL2 e fondamentale |
| Difetto IaC piu comune | Configuration Data (Paper 11) | Clone detection intercetta duplicazioni di configurazione |
