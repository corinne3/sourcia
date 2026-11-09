# SourcIA

**À partir d'une demande structurée, trouver et qualifier les sources de R&D agricole, puis en faire un support de formation rattaché au référentiel du diplôme.**
Hackathon SAED, défi 1 : passer de **milliers de documents** à **environ 50 sources pertinentes, récentes et justifiées**, prêtes à être chargées dans NotebookLM ou tout autre outil de génération.

> Projet de Corinne Bergès, issu de TransfIA (projet personnel open source) : même socle technique (modèles locaux ou cloud par configuration, recherche hybride, traces, évaluation), nouveau métier.

---

## Ce que fait l'outil

| Module | Rôle | Commande |
|---|---|---|
| **M0 Demande** | les 7 critères du métier (profil, type de formation, public, ressources, sorties, sources, contenu personnel) | `demande`, `--demande-fichier`, page web |
| **M1 Collecte** | PDF d'un site, vidéos, photos, données (`--medias`), catalogue, documents privés | `add-site`, `import-catalog`, `add-folder`, `download` |
| **M2 Extraction** | lire le texte (d'abord les premières pages) | `extract` |
| **M3 Qualification** | remplir une **fiche** par document (organisme, année, lieu, contexte, type, dispositif, chiffrage), **chaque valeur avec sa preuve** | `qualify`, `fiche` |
| **M4 Recherche** | mots + sens + synonymes métier + reranker | `index`, `search` |
| **M5 Sélection** | entonnoir → ≈ 50 documents classés, filtrés, **justifiés**, diversifiés | `select` |
| **M6 Sorties** | page web du formateur, exports (md, csv, txt, json, zip), API, serveur MCP | `serve`, `mcp`, `select --export` |
| **M7 Formation** | créer **soi-même** le support : plan, points clés sourcés, QCM (et Moodle), fiche technique, synthèse, cas concret, glossaire, script de podcast, déroulé de séance, contenu personnel protégé | `formation` |
| **M8 Référentiels** | capacités des diplômes (chlorofil.fr), versions, rattachement des séquences, validation par l'enseignant, contrôle du niveau | `referentiel`, `valider-formation` |
| **Évaluation** | comparer à une référence fournie par le métier | `eval trouver`, `eval qualifier`, `eval gabarit` |

Formats d'échange entre modules (le « contrat » pour l'équipe) : `data/documents.jsonl` et `data/fiches.jsonl` (voir `src/sourcia/core/models.py`).

## Deux usages de la sélection

| Voie | Entrée | Ce qui est produit | Contrôles |
|---|---|---|---|
| **NotebookLM ou autre outil** (proposition de l'équipe) | export `.txt` (adresses) ou `.zip` (PDF) | ce que produit l'outil | ceux de l'outil |
| **M7 Formation de SourcIA** (complément) | la même sélection | support formateur `.md`, QCM apprenants, QCM Moodle (GIFT), `.json` | dans le code : chaque point, définition et réponse doit se retrouver dans sa source ; sinon retiré et listé ; les **alertes des fiches** (résultats anciens, réglementation…) suivent dans l'annexe des sources |

## Les garde-fous

- **Pas de valeur sans preuve** : une valeur proposée par le modèle est rejetée si sa preuve ne se retrouve pas dans le document, ou si le nombre donné (année, modalités, répétitions) ne figure pas dans la preuve.
- **« Non trouvé » plutôt qu'une valeur inventée.**
- **Documents privés jamais envoyés à un modèle en ligne** (verrou dans le code, testé).
- **Justification construite à partir de la fiche et du passage trouvé** : elle ne peut pas inventer.
- **Formation** : un point clé, une définition ou une explication de QCM non retrouvé dans le passage cité est retiré (et listé en annexe) ; un chiffre doit figurer à l'identique dans la source ; la bonne réponse d'un QCM doit être celle que l'explication justifie.
- **Collecte polie** : robots.txt respecté, une requête par seconde au plus par site.

## Démarrage rapide (Windows, PowerShell)

```powershell
cd C:\dev\sourcia
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[recommended]"
sourcia -c config/rapide.yaml doctor
sourcia -c config/rapide.yaml demo
```

Exemples de demandes : `config/demandes/` (BTSA diplômant, agriculteurs en distanciel, CAPa).

`demo` déroule tout le pipeline sur 8 documents **fictifs** (`data/samples`), sans Internet ni modèle.
Le plan de tests pas à pas est dans [`docs/PLAN_TESTS.md`](docs/PLAN_TESTS.md).

## Configurations

| Fichier | Modèle | Embeddings | Usage |
|---|---|---|---|
| `config/rapide.yaml` | Ollama qwen2.5:1.5b | hashing (aucun modèle) | premier essai en 1 minute |
| `config/local.yaml` | Ollama qwen2.5:3b | multilingual-e5-small | usage normal, tout reste sur le PC |
| `config/gcp.yaml` | Gemini Flash-Lite (LiteLLM) | e5 en local | documents publics seulement ; clé dans `.env` |
| `config/test.yaml` | factice | hashing | tests automatiques |

## Documentation

- [`docs/DOSSIER_ARCHITECTURE.md`](docs/DOSSIER_ARCHITECTURE.md) : **le dossier pour l'équipe** (besoins → blocs, sous-défis, contrats, propositions pour les questions ouvertes)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) : détails techniques de M1 à M7
- [`docs/PLAN_TESTS.md`](docs/PLAN_TESTS.md) : installation et tests pas à pas, avec les commandes
- [`docs/JOURNAL_TESTS.md`](docs/JOURNAL_TESTS.md) : résultats obtenus, problèmes et corrections

## Licence

MIT pour le code. Les documents collectés gardent leur propre licence (ex. RD Agri : CC BY-NC-SA) : la colonne `licence` est conservée.
