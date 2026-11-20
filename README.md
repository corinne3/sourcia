# SourcIA

**À partir d'une demande structurée, trouver et qualifier les sources de R&D agricole, puis en faire un support de formation rattaché au référentiel du diplôme.**
Hackathon SAED, défi 1 : passer de **milliers de documents** à **environ 50 sources pertinentes, récentes et justifiées**, prêtes à être chargées dans NotebookLM ou tout autre outil de génération.

> Projet de Corinne Bergès, issu de TransfIA (projet personnel open source) : même socle technique (modèles locaux ou cloud par configuration, recherche hybride, traces, évaluation), nouveau métier.

---

## Ce que fait l'outil

| Module | Rôle | Commande |
|---|---|---|
| **M0 Demande** | les 7 critères du métier (profil, type de formation, public, ressources, sorties, sources, contenu personnel) | `demande`, `--demande-fichier`, page web |
| **M1 Collecte** | sites prioritaires chaque jour (PDF et articles web), suivi des liens déplacés ou morts ; PDF d'un site, vidéos, photos, données (`--medias`), catalogue, documents privés | `collect-sites`, `check-links`, `add-site`, `import-catalog`, `add-folder`, `download` |
| **M2 Extraction** | lire le texte (d'abord les premières pages) | `extract` |
| **M3 Qualification** | remplir une **fiche** par document (organisme, année, lieu, contexte, type, dispositif, chiffrage), **chaque valeur avec sa preuve** | `qualify`, `fiche` |
| **M4 Recherche** | mots + sens + synonymes métier + reranker | `index`, `search` |
| **M5 Sélection** | entonnoir → ≈ 50 documents classés, filtrés, **justifiés**, diversifiés | `select` |
| **M6 Sorties** | page web du formateur, exports (md, csv, txt, json, zip), API, serveur MCP | `serve`, `mcp`, `select --export` |
| **M7 Formation** | créer **soi-même** le support : plan, points clés sourcés, QCM (et Moodle), fiche technique, synthèse, cas concret, glossaire, script de podcast, déroulé de séance, contenu personnel protégé | `formation` |
| **Corpus pédagogique** (étape 3) | à partir des **seuls documents cochés** et des acquis visés : séquences rattachées aux capacités, points clés et synthèse avec **références vérifiables** (document, page, extrait exact, lien `#page=N` pour un PDF), bibliographie, dans `corpus.json` (sans QCM) ; document Word avec liens cliquables vers la page citée (`corpus_pedagogique.docx`, python-docx : `pip install -e ".[word]"`) ; **illustrations d'origine** des pages citées (PyMuPDF : logos, bandeaux et décors écartés, légende prise dans le document) | `corpus`, `corpus-word` |
| **M8 Référentiels** | capacités des diplômes (chlorofil.fr), versions, rattachement des séquences, validation par l'enseignant, contrôle du niveau | `referentiel`, `valider-formation` |
| **Évaluation** | comparer à une référence fournie par le métier | `eval trouver`, `eval qualifier`, `eval gabarit` |

Formats d'échange entre modules (le « contrat » pour l'équipe) : `data/documents.jsonl` et `data/fiches.jsonl` (voir `src/sourcia/core/models.py`).
Dans `documents.jsonl`, le champ facultatif `link` donne l'état du lien (`ok`, `moved`, `dead`, `unreachable`) : pour afficher ou exporter une adresse, utiliser `doc.current_url` (la nouvelle adresse si le document a été déplacé) ; `url` et `id` ne changent jamais.

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
- **Collecte polie** : robots.txt respecté, une requête par seconde au plus par site ; une protection anti-robots n'est jamais contournée (le site est signalé en échec).
- **Articles : le texte de l'article seul**, sans les « articles liés » ni les encadrés de la page, pour qu'une preuve ne vienne jamais d'un autre article.
- **Un lien n'est déclaré mort qu'avec certitude** : 404/410 ou page HTML à la place du PDF ; une panne passagère ne compte qu'après 3 échecs de suite.

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

## Collecte quotidienne des sites prioritaires

La liste des sites est dans [`config/sites.yaml`](config/sites.yaml) :

| Champ | Rôle |
|---|---|
| `nom`, `url` | nom court (sert de `source` aux documents) et adresse de départ |
| `filtre` | expression régulière : pages visitées en premier ; PDF gardés si elle se retrouve dans leur adresse, le texte du lien ou la page d'origine |
| `articles` | chemin des pages d'articles (ex. `^/infos-techniques/`) : chaque article qui passe le filtre devient un document `page` (texte de l'article seul, date de publication) |
| `exclure` | adresses jamais visitées ni listées (ex. sommaires de brochures payantes) |
| `actif` | `false` : site mis de côté (ex. bloqué), collecté seulement si on le demande avec `--site` |

```powershell
sourcia collect-sites                       # tous les sites : exploration, nouveaux PDF et articles, rapport par site
sourcia collect-sites --site arvalis --max-pages 20 --no-download
sourcia check-links                         # liens du catalogue : déplacés, morts, injoignables (rien n'est téléchargé)
sourcia check-links --etat dead,unreachable # revérifier seulement les liens à problème
```

Chaque lancement écrit un rapport lisible à l'écran et en JSON : `data/collecte/` et `data/liens/` (historique + `dernier.json`).
`collect-sites` s'arrête avec le code 1 si un site est injoignable ou bloqué, pour qu'un lancement automatique le signale.

| Règle de `check-links` | État |
|---|---|
| réponse 200 à la même adresse | `ok` |
| redirection définitive (301, 308) | `moved`, nouvelle adresse dans `link.new_url` |
| redirection temporaire (302, 307 : souvent un lien signé qui expire) | `ok`, l'adresse d'origine reste la bonne |
| 404, 410, ou page HTML à la place d'un PDF | `dead` |
| délai dépassé, erreur 5xx… | `unreachable`, puis `dead` après 3 échecs de suite |

Si `collect-sites` télécharge un fichier identique (même empreinte) à celui d'un document mort, l'ancien passe en `moved` vers la nouvelle adresse.

### Lancement automatique chaque jour

[`scripts/collecte_quotidienne.ps1`](scripts/collecte_quotidienne.ps1) enchaîne `collect-sites` puis `check-links`, écrit un journal par jour (`data/journal/collecte-AAAA-MM-JJ.log`) et refuse de démarrer si une collecte est déjà en cours. Code de sortie : 0 tout va bien, 1 à vérifier.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collecte_quotidienne.ps1                         # à la main
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\collecte_quotidienne.ps1 -Site arvalis -MaxPages 20
```

Pour le lancer chaque jour à 7 h avec le Planificateur de tâches Windows (à faire une fois, dans PowerShell, depuis le dossier du projet) :

```powershell
$projet = (Get-Location).Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $projet `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$projet\scripts\collecte_quotidienne.ps1`""
$quand = New-ScheduledTaskTrigger -Daily -At 7am
$options = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "SourcIA collecte quotidienne" -Action $action -Trigger $quand -Settings $options
```

`-StartWhenAvailable` : si le PC était éteint à 7 h, la collecte part dès qu'il est rallumé. Pour l'arrêter : `Unregister-ScheduledTask -TaskName "SourcIA collecte quotidienne"`.

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
