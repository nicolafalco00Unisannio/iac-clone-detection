\## Giustificazione dell’approccio a granularità di file



Sì, puoi assolutamente adottare questo approccio, e qui trovi la giustificazione che puoi utilizzare nel report del progetto o nella discussione finale.



Il tuo approccio è una \*\*rilevazione dei cloni a granularità di file\*\*, che differisce dalla tradizionale clone detection del software ma è altamente rilevante per l’Infrastructure as Code (IaC).



\### Strategia di giustificazione



Puoi sostenere che la rilevazione a livello di sottoalbero sia eccessiva e produca rumore nell’IaC dichiarativo per i seguenti motivi:



\#### L’unità di riuso in Terraform è il modulo (file/cartella)



\* In Java/C++, gli sviluppatori copiano e incollano funzioni (sottoalberi).

\* In Terraform, gli sviluppatori copiano tipicamente interi ambienti o interi file di moduli (ad esempio copiando `dev/main.tf` per creare `prod/main.tf`).

\* Di conseguenza, la rilevazione dell’intero albero si allinea meglio al flusso di lavoro reale degli ingegneri Terraform.



\#### La sintassi dichiarativa è intrinsecamente “clonata”



\* Il codice Terraform contiene naturalmente molti piccoli frammenti identici (ad esempio configurazioni standard di bucket S3).

\* La rilevazione a livello di sottoalbero segnalerebbe migliaia di falsi positivi (boilerplate).

\* Due definizioni simili di bucket non rappresentano necessariamente debito tecnico: è semplicemente il modo in cui funziona il linguaggio.

\* L’approccio Full-Tree filtra questo rumore e si concentra su duplicazioni strutturali significative che indicano reali opportunità di refactoring.



\#### Compromesso tra prestazioni e valore



\* Confrontare ogni sottoalbero con ogni altro sottoalbero ha complessità O(N²) rispetto al numero di nodi.

\* Confrontare file ha complessità O(N²) rispetto al numero di file.

\* Poiché i progetti Terraform possono diventare molto grandi, la rilevazione a livello di file fornisce risultati immediatamente utilizzabili senza il costo computazionale della rilevazione a livello di sottoalbero.



\### Conclusione



Non stai sbagliando approccio: stai eseguendo una \*\*clone detection a grana grossa\*\*.



Per essere scientificamente accurato, definisci chiaramente l’ambito:



> “Questo strumento si concentra sulla clone detection a grana grossa (livello di file) per identificare configurazioni di ambienti e definizioni di moduli duplicate, evitando l’elevato rapporto rumore/segnale tipico del pattern matching a grana fine nei linguaggi dichiarativi.”



---



\## Giustificazione fondamentale del progetto



Argomento centrale:



\*\*“L’IaC è codice, ma viene trattata come configurazione. Questo genera tipi specifici di debito tecnico che i tradizionali clone detector non intercettano.”\*\*



\### 1. Il problema dell’infrastruttura “Split-Brain”



Nel software tradizionale, un bug da copia-incolla rompe una funzionalità.

Nell’IaC può causare deriva di sicurezza e downtime.



Scenario:



\* Un ingegnere copia `dev/main.tf` per creare `prod/main.tf`.



Problema:



\* Dopo mesi viene applicata una patch di sicurezza in dev ma non in prod perché i file sono leggermente divergenti (clone Tipo 3).



Valore dello strumento:



\* Individua cloni quasi identici e segnala differenze critiche.



---



\### 2. Violare il principio DRY costa denaro



Nel cloud computing, duplicazione di codice = duplicazione di costi.



Scenario:



\* Team copiano blocchi EC2 invece di usare moduli condivisi.



Problema:



\* Cambiare istanza globalmente richiede modifiche manuali a molti file.



Valore dello strumento:



\* Identifica cloni parametrizzati e supporta refactoring in moduli riutilizzabili.



---



\### 3. Il codice dichiarativo è difficile da confrontare



I diff testuali falliscono perché l’ordine non conta.



Scenario:



\* File A: X poi Y

\* File B: Y poi X



Problema:



\* Il diff testuale li considera completamente diversi.



Valore:



\* AST + Tree Edit Distance rileva equivalenza semantica.



---



\### 4. Scalabilità della manutenzione



Le codebase Terraform crescono linearmente con l’infrastruttura.



Problema:



\* Aggiornamenti richiedono modifiche manuali a centinaia di file.



Valore:



\* Assistente al refactoring che suggerisce consolidamenti in moduli.



---



\### Frase riassuntiva per abstract



> “Sebbene l’Infrastructure as Code sia lo standard per il provisioning cloud, i workflow basati su copia-incolla introducono rischi di sicurezza e manutenzione. Questo progetto implementa un sistema di clone detection basato su AST che utilizza Tree Edit Distance per identificare cloni semantici (Tipo 1-3), affrontando deriva di configurazione e violazioni di modularità.”



---



\## Riferimenti accademici standard



\### Validazione del problema



\*\*Does Your Configuration Code Smell?\*\*

Sharma, Fragkoulis, Spinellis (2016)



\* Dimostra che l’IaC soffre di code smell.

\* Il codice duplicato rappresenta il 13% degli smell.



\*\*Security Smells in Infrastructure as Code Scripts\*\*

Rahman \& Williams (2019)



\* Mostra che i cloni propagano vulnerabilità.



---



\### Validazione della tassonomia



\*\*A Survey on Software Clone Detection Research\*\*

Roy \& Cordy (2007)



\* Definisce Type 1, Type 2 e Type 3 clone.



---



\### Validazione della metodologia



\*\*Clone Detection Using Abstract Syntax Trees\*\*

Baxter et al. (1998)



\* AST > diff testuali.



\*\*Tree Edit Distance Algorithms\*\*

Zhang \& Shasha (1989)



\* Algoritmo implementato dalla libreria ZSS.



---



\### Terminologia accademica



Usa il termine \*\*Configuration Drift\*\* invece di “Split-Brain”.



---



\## Threats to Validity



\### Construct Validity



\* Modello di costo euristico.

\* Mancanza di risoluzione semantica delle variabili.

\* Ordinamento delle liste.



\### Internal Validity



\* Bias di granularità (file vs sottoalbero).

\* Complessità algoritmica O(N³) o O(N⁴).



\### External Validity



\* Rappresentatività del dataset.

\* Specificità del linguaggio Terraform.



Frase riassuntiva:



> “L’approccio AST offre maggiore precisione rispetto ai diff testuali, ma i risultati sono influenzati da bias di granularità e dalla mancata risoluzione semantica.”



---



\## Sviluppi futuri



\### 1. Consapevolezza semantica



\* Risoluzione variabili e valutazione parziale.

\* Rilevazione Type 4 clone.



\### 2. Prefiltro basato su fingerprint



\* LSH o hashing vettoriale.

\* Riduzione complessità.



\### 3. Subtree detection integrata



\* Identificazione blocchi duplicati interni.

\* Generazione automatica moduli.



\### 4. Machine Learning per raccomandazioni



\* Classificare cloni dannosi vs benigni.



\### 5. Supporto multi-linguaggio IaC



\* Adapter per YAML, JSON e altri strumenti.



Tabella riassuntiva:



| Feature             | Categoria         | Difficoltà | Problema affrontato |

| ------------------- | ----------------- | ---------- | ------------------- |

| Variable Resolution | Analisi semantica | Alta       | False negative      |

| Vector Hashing      | Prestazioni       | Media      | Scalabilità         |

| Subtree Mining      | Granularità       | Alta       | Bias file-level     |

| Auto-Refactoring    | Automazione       | Molto alta | Azionabilità        |



---



\## Struttura del paper (IMRaD adattato)



\### Titolo (idee)



\* Analisi empirica dei code clone in registri IaC su larga scala

\* Rilevamento della Configuration Drift tramite AST



---



\### 1. Introduzione



\* IaC come base del cloud moderno.

\* Problemi di copia-incolla e deriva.

\* Limiti dei diff testuali.

\* Soluzione AST + TED.

\* Contributi principali.



---



\### 2. Background e Related Work



\* Terraform e moduli.

\* Tassonomia dei cloni.

\* Letteratura esistente.



---



\### 3. Metodologia



\* Architettura del tool.

\* Rappresentazione AST.

\* Algoritmo Zhang-Shasha.

\* Logica di classificazione.



---



\### 4. Study Design



\* Dataset TerraDS.

\* Parametri e soglie.

\* Specifiche hardware.



---



\### 5. Risultati (con Research Questions)



RQ1: Tipologie di cloni

RQ2: Impatto dei cloni

RQ3: Prevalenza dei cloni



---



\### 6. Discussione



\* Interpretazione risultati.

\* Implicazioni industriali.

\* Threats to Validity.



---



\### 7. Conclusione e Future Work



\* Sintesi risultati.

\* Estensioni future.



---



\### Suggerimenti di scrittura



\* Usa “We propose”, non “I did”.

\* Definisci TerraDS chiaramente.

\* Ammetti limiti esplicitamente.

