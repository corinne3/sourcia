# SourcIA : architecture

> Détails techniques de M1 à M7 (écrits en s2, toujours valables). La vue d'ensemble à jour (s3 : demande structurée M0, référentiels M8, ressources non textuelles, nouvelles sorties) est dans [`DOSSIER_ARCHITECTURE.md`](DOSSIER_ARCHITECTURE.md).
> Version du code décrite ici : `s2`. Ce document décrit ce qui est **codé**. La note d'architecture pour le forum (proposition à l'équipe) en reste la source.

---

## 1. Principes

| Principe | Dans le code |
|---|---|
| **La valeur est en amont** | on livre une sélection de documents qualifiés ; l'outil de génération (NotebookLM ou autre) reste interchangeable |
| **Le métier définit la qualité** | `eval gabarit` produit le tableau à remplir ; `eval qualifier` et `eval trouver` mesurent l'outil contre cette référence |
| **Traçable** | chaque champ de la fiche = valeur + preuve + confiance + méthode (`source`, `regles`, `llm`, `humain`) |
| **Frugal** | règles gratuites pour tous ; modèle seulement pour les N premiers candidats (`--llm-top`) ; fiches en cache |
| **Pas d'ontologie lourde** | sens par embeddings ; petit lexique `config/synonymes.yaml` facultatif |
| **Modulaire** | 6 modules, deux fichiers d'échange (`documents.jsonl`, `fiches.jsonl`) |
| **Portable** | changer de modèle = changer de fichier de configuration (Ollama local ou Gemini via LiteLLM) |

## 2. Vue d'ensemble

```
 Sites (add-site)     Catalogue RD Agri / Lexicon (import-catalog)     Dossier privé (add-folder)
        │                          │                                          │
        ▼                          ▼                                          ▼
 M1 COLLECTE  collect/  web.py · catalog.py · local.py · store.py   →  data/documents.jsonl
        ▼
 M2 EXTRACTION  extract/pdf.py  (PyMuPDF, sinon pypdf ; 40 pages max)  →  data/text/<id>.json
        ▼
 M3 QUALIFICATION  qualify/  rules.py (passe 1) · llm.py (passe 2) · pipeline.py (fusion, alertes, cache)
                                                                     →  data/fiches.jsonl
        ▼
 M4 RECHERCHE  search/index.py  BM25 + embeddings (RRF) + synonymes + reranker  →  data/index/<embeddings>/
        ▼
 M5 SÉLECTION  select/funnel.py  filtres · score · diversité · justification
        ▼
 M6 SORTIES  export/exporters.py · api/app.py (+ static/index.html) · mcp_server/server.py · cli.py
        ▼                                      ▼
   NotebookLM ou autre outil            M7 FORMATION  formation/  corpus · builder · checks · render
                                         →  data/formations/<date>/ (support .md, QCM, Moodle GIFT, .json)
 Transverse : evaluation/bench.py · observability/ (traces) · llm/ (Ollama, LiteLLM, factice, cache)
```

## 3. Modules

### M1 Collecte (`collect/`)

- **`web.py`** : à partir d'une adresse :
  - lit `robots.txt` (pages interdites jamais visitées) ;
  - lit les plans de site (`sitemap.xml`, y compris les index de plans) ;
  - explore les pages du même site (largeur d'abord, `max_pages_per_site`) ;
  - garde les liens PDF, avec le **texte du lien comme titre** ;
  - `--include` : expression régulière pour ne garder que certains PDF ;
  - téléchargement : vérifie que c'est un vrai PDF (`%PDF`) et sa taille.
- **`catalog.py`** : CSV, JSON, JSONL ou liste d'adresses ; reconnaît les noms de colonnes courants (`titre`, `lien`, `année`…), sinon `--map`.
- **`local.py`** : un dossier de PDF ou de textes, **privés par défaut**.
- **`store.py`** : `documents.jsonl` ; fusion si un document est ajouté deux fois ; **doublons de contenu** (même empreinte sha1 sur deux sites) écartés par `canonical()`.

### M2 Extraction (`extract/pdf.py`)

- Texte page par page, nettoyé (mots coupés, espaces).
- PDF scanné détecté (moins de 200 caractères sur les 3 premières pages) → alerte « OCR nécessaire ».
- La date de création du fichier est notée comme **indice faible** seulement (`meta.annee_fichier`).

### M3 Qualification (`qualify/`)

| Passe | Sur quoi | Coût | Comment |
|---|---|---|---|
| **Source** | métadonnées | nul | date du catalogue, nom du site |
| **1. Règles** (`rules.py`) | tous les documents | nul | expressions régulières et petits lexiques ; la preuve = la phrase trouvée |
| **2. Modèle** (`llm.py`) | candidats demandés | mesuré (`cout_s`) | sortie JSON validée (Pydantic) ; preuve obligatoire |
| **Fusion** (`pipeline.py`) | — | — | la valeur la plus sûre l'emporte ; accord règles + modèle → confiance + 0,15 |

Garde-fous de la passe modèle :
1. la preuve doit se retrouver dans le texte (au moins 60 % de ses mots) ;
2. un nombre (année, modalités, répétitions) doit figurer **dans** sa preuve ;
3. document privé + modèle en ligne → la passe modèle n'est pas lancée ;
4. si le modèle échoue (JSON invalide, délai), on garde les règles et on le note (`llm_echec`).

Alertes : année antérieure à 2022 (sécheresses récentes), année non trouvée, réglementation ancienne (ex. glyphosate), pas de chiffrage économique, lieu non trouvé, retour d'expérience sans dispositif, PDF scanné, contexte éloigné de la région du formateur.

### La fiche (`core/models.py`)

```json
{
  "document_id": "9e3cb5a759575bae",
  "organisme": {"value": "Chambre d'agriculture", "evidence": "Chambre d'agriculture des Pays de la Loire", "confidence": 0.5, "method": "regles"},
  "annee": {"value": 2023, "evidence": "…résultats de l'essai 2023", "confidence": 0.5, "method": "regles"},
  "lieu": {"value": "ferme expérimentale des Grands Prés", "evidence": "Essai conduit à la ferme expérimentale…", "confidence": 0.6, "method": "regles"},
  "type": {"value": "experimentation", "…": "…"},
  "modalites": {"value": 4, "…": "…"},
  "repetitions": {"value": 3, "…": "…"},
  "chiffrage_economique": {"value": true, "…": "…"},
  "themes": ["sorgho", "sécheresse", "valeur alimentaire"],
  "alertes": [],
  "passes": ["regles"],
  "cout_s": 0.0
}
```

Les colonnes définitives viendront de « l'Excel » du métier : ajouter un champ = l'ajouter à `Fiche`, à `FicheLLM` (consigne du modèle) et, si possible, une règle.

### M4 Recherche (`search/`)

- Indexé par document : **titre + mots-clés**, puis les `index_pages` premières pages en passages de 200 mots.
- **BM25** (mots, avec synonymes métier) + **embeddings** (sens) fusionnés par **RRF** (rang réciproque).
- `min_dense_sim` : seuil de similarité sous lequel un passage n'est pas candidat par le sens (sinon tout le corpus remonte) ; **à calibrer par modèle d'embeddings**.
- Reranker : `lexical` (rapide) ou `cross-encoder` (plus précis, plus lent).
- Un index par modèle d'embeddings (`data/index/<modèle>/`) : on peut changer de configuration sans tout casser.

### M5 Sélection (`select/funnel.py`)

1. recherche : jusqu'à 300 candidats ;
2. qualification : règles pour tous, modèle pour les `llm_top` premiers ;
3. filtres : années, types, sources (`strict` : exclure aussi les valeurs inconnues) ;
4. score = 0,6 × pertinence + 0,2 × récence + 0,2 × qualité du dispositif ;
5. diversité : au plus `max_per_source` documents d'un même organisme ;
6. justification : passage trouvé (avec la page), faits de la fiche, alertes.

### M6 Sorties

- **Exports** : `.md` (liste lisible), `.csv` (toutes les colonnes, pour le tableur et la relecture du métier), `.txt` (une adresse par ligne, pour NotebookLM ; **jamais les documents privés**), `.json`, `.zip` (les PDF téléchargés).
- **Page web** (`sourcia serve`) : demande, filtres, liste justifiée, fiche et preuves dépliables, exports.
- **API** : `POST /api/selection`, `GET /api/recherche`, `GET /api/fiche/{id}`, `GET /api/export/{fichier}`, `GET /api/etat`.
- **MCP** (`sourcia mcp`) : `chercher_sources`, `selectionner_sources`, `fiche_document` (pour l'agent de l'équipe ou un autre client).

### M7 Formation (`formation/`)

Le complément pour créer **soi-même** la formation, à partir de la même sélection que celle donnée à NotebookLM.

| Étape | Fichier | Ce qui se passe |
|---|---|---|
| Mini-corpus | `corpus.py` | seulement les documents sélectionnés, découpés en passages ; recherche mots + sens, au plus 2 passages par document (diversité) ; documents privés exclus si le modèle est en ligne |
| Plan | `builder.py` | le modèle propose les séquences (titre, objectif, durée, mots-clés) à partir des titres et thèmes ; **repli sans modèle** : une séquence par thème le plus fréquent des fiches |
| Par séquence | `builder.py` | passages utiles → **points clés** cités [n] → **QCM** (on en demande 2 de plus et on garde ceux qui passent les contrôles) |
| Glossaire, cas pratique | `builder.py` | facultatifs (`--sans-glossaire`, `--sans-cas`) ; le cas pratique décrit une exploitation **fictive** |
| Contrôles | `checks.py` | voir ci-dessous |
| Sorties | `render.py` | support formateur, QCM apprenants (sans réponses), QCM Moodle (GIFT), JSON |

Contrôles dans le code (une sortie bien formée n'est pas une sortie juste) :
1. point clé, définition, élément de réponse : ses mots porteurs de sens doivent se retrouver dans le passage cité (≥ 50 %), et **un chiffre doit y figurer à l'identique** ;
2. QCM : l'explication doit être soutenue par son passage ; la bonne réponse doit être celle que l'explication justifie (sinon l'index est **corrigé** et c'est signalé) ; question ambiguë ou en double → retirée ;
3. doublons de points clés entre séquences, et de termes du glossaire → retirés ;
4. tout ce qui est retiré est listé dans l'**annexe B** du support : rien n'est caché au formateur ;
5. chaque contenu renvoie au document et à la page (« S3, p. 2 ») ; l'**annexe A** liste les sources avec leurs **alertes**.

Limites : contrôles lexicaux (ni paraphrase ni négation comprises) ; avec un petit modèle, beaucoup de contenus sont retirés (c'est voulu) ; **le formateur relit avant diffusion**.

Coût : environ 2 appels au modèle par séquence, plus 2 (plan, glossaire) et 1 (cas pratique). En local avec qwen2.5:3b, compter 1 à 3 minutes par appel.

## 4. Évaluation (`evaluation/bench.py`)

| Mesure | Référence | Indicateurs |
|---|---|---|
| **Trouver** | `demandes.jsonl` : demandes de formateurs + documents attendus | rappel@N, MRR, comparés à 5 méthodes : titres seuls (≈ moteur par mots-clés), BM25, sens seul, hybride, sélection complète |
| **Qualifier** | tableau rempli par le métier (`eval gabarit` le prépare) | exactitude par champ et **taux de valeurs fausses** (pire qu'une valeur absente) |
| **Coût** | — | `cout_s` par fiche, `sourcia stats` |

⚠️ Le jeu d'exemple (`data/samples/eval`) est **fictif** et écrit avec les mêmes formulations que les règles : il vérifie que le code marche, **il ne mesure pas** la qualité réelle.

## 5. Sécurité et conformité

- Aucune clé dans le code : `.env` (ignoré par Git).
- Documents privés : jamais vers un modèle en ligne, jamais d'adresse dans les exports `.txt` et le MCP.
- Collecte : robots.txt, délai d'une seconde, `User-Agent` explicite sans adresse personnelle.
- Licences : conservées par document ; RD Agri en CC BY-NC-SA (usage non commercial, attribution).
- Niveau gratuit de Gemini : pour des essais seulement ; un service ouvert à des utilisateurs de l'EEE doit passer au niveau payant.

## 6. Limites connues et suites

- Règles écrites sur des exemples fictifs : **à recalibrer sur de vrais documents**.
- Pas d'OCR des PDF scannés.
- Connecteur MCP RD Agri à brancher quand sa documentation sera publiée.
- Tableaux des PDF non exploités (dispositif souvent dans un tableau).
- M7 : mesurer la part de contenus retirés par modèle (1.5B, 3B, Gemini) et faire juger les supports par des formateurs ; comparer avec ce que produit NotebookLM sur la même sélection.
- À comparer : NotebookLM seul, recherche Google `filetype:pdf`, moteur de RD Agri.
