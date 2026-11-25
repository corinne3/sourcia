# SourcIA

[![Tests](https://github.com/moussa197/saed-defi1/actions/workflows/tests.yml/badge.svg)](https://github.com/moussa197/saed-defi1/actions/workflows/tests.yml)

**À partir d'une demande structurée, trouver et qualifier les sources de R&D agricole, puis en faire un support de formation rattaché au référentiel du diplôme.**
Hackathon SAED, défi 1 : passer de **milliers de documents** à **environ 50 sources pertinentes, récentes et justifiées**, prêtes à être chargées dans NotebookLM ou tout autre outil de génération.

> Projet de Corinne Bergès, issu de TransfIA (projet personnel open source) : même socle technique (modèles locaux ou cloud par configuration, recherche hybride, traces, évaluation), nouveau métier.

**Le parcours de l'enseignant, dans le navigateur :**

| 1. Catalogue | 2. Mon dossier | 3. Mon corpus | 4. Mes supports |
|---|---|---|---|
| chercher dans les sources collectées (Arvalis, Terres Inovia, chambres d'agriculture…) | garder les documents utiles, ajouter les siens (PDF privés) | séquences rattachées aux capacités du diplôme, chaque point clé avec sa source (document, page, extrait, lien) | QCM, cartes, présentation, infographie, fiche technique, glossaire, podcast |

---

## Sommaire

1. [Essayer en 2 minutes](#essayer-en-2-minutes)
2. [Utiliser l'application web sur son PC](#utiliser-lapplication-web-sur-son-pc)
3. [Mettre en ligne](#mettre-en-ligne)
4. [Configurations](#configurations)
5. [Les garde-fous](#les-garde-fous)
6. [Ce que fait l'outil, module par module](#ce-que-fait-loutil-module-par-module)
7. [Comptes enseignants et dossiers](#comptes-enseignants-et-dossiers)
8. [Collecte quotidienne des sites prioritaires](#collecte-quotidienne-des-sites-prioritaires)
9. [Travailler à plusieurs](#travailler-à-plusieurs)
10. [Documentation](#documentation) et [licence](#licence)

---

## Essayer en 2 minutes

Windows, PowerShell, Python 3.10 ou plus récent :

```powershell
git clone https://github.com/moussa197/saed-defi1.git
cd saed-defi1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[recommended]"
sourcia -c config/rapide.yaml doctor
sourcia -c config/rapide.yaml demo
```

- `doctor` vérifie l'installation ; `demo` déroule tout le pipeline sur 8 documents **fictifs** (`data/samples`), sans Internet ni modèle.
- Si `Activate.ps1` est refusé : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis relancer l'activation.
- Chaque nouvelle fenêtre PowerShell : se placer dans le dossier, puis `.\.venv\Scripts\Activate.ps1` (la ligne commence alors par `(.venv)`).
- Exemples de demandes : `config/demandes/` (BTSA diplômant, agriculteurs en distanciel, CAPa).
- Le plan de tests pas à pas est dans [`docs/PLAN_TESTS.md`](docs/PLAN_TESTS.md).

## Utiliser l'application web sur son PC

**1. Le modèle.** Deux choix :

| Choix | Ce qu'il faut | Configuration |
|---|---|---|
| **Gemini** (en ligne, rapide) | `pip install -e ".[cloud]"`, puis une clé Gemini (Google AI Studio) : copier `.env.example` en `.env` et remplir `GEMINI_API_KEY` | `config/gcp.yaml` |
| **Ollama** (tout reste sur le PC) | [Ollama](https://ollama.com) installé, puis `ollama pull qwen2.5:3b` | `config/local.yaml` |

`.env` n'est jamais envoyé sur GitHub (il est dans `.gitignore`). Ne collez jamais la clé ailleurs.
Si Windows bloque `litellm` (message « Contrôle d'application » ou DLL refusée) : `pip install "litellm==1.80.0"`.

**2. Le catalogue.** Après un `git clone`, le catalogue est vide : les documents de tiers ne sont jamais dans git. Trois façons de le remplir :

```powershell
# a) collecter les vrais sites (config/sites.yaml), puis préparer les documents (de 30 min à quelques heures)
sourcia -c config/gcp.yaml collect-sites
sourcia -c config/gcp.yaml extract
sourcia -c config/gcp.yaml qualify
sourcia -c config/gcp.yaml index

# b) importer le paquet d'un collègue (demandé en privé : il contient des textes de tiers), puis indexer
python scripts/catalogue_paquet.py importer catalogue-AAAAMMJJ.tar.gz
sourcia -c config/gcp.yaml index

# c) seulement pour voir, sur un catalogue vide : les 8 documents fictifs (sinon ils se mêlent aux vrais)
sourcia -c config/gcp.yaml demo
```

Remplacez `config/gcp.yaml` par `config/local.yaml` si vous utilisez Ollama.

**3. Lancer l'application et créer son compte** (deux fenêtres PowerShell) :

```powershell
sourcia -c config/gcp.yaml serve
```

```powershell
sourcia -c config/gcp.yaml comptes ajouter prenom.nom@lycee.fr --url http://127.0.0.1:8000
```

La deuxième commande affiche un **lien de connexion** (`…/dossiers#jeton=…`) : ouvrez-le dans le navigateur, vous êtes connecté.
Puis suivez la barre d'étapes : **Catalogue → Mon dossier → Mon corpus → Mes supports**. `Ctrl+C` arrête le serveur.

## Mettre en ligne

L'image Docker contient l'application seule : **aucun secret, aucune donnée**. Les secrets sont donnés au démarrage ;
le catalogue, les comptes et les dossiers vivent dans un volume persistant (`/data`).

Sur son PC, exactement comme en ligne (Docker Desktop) :

```powershell
# dans .env : GEMINI_API_KEY=…  et  SOURCIA_SESSION_SECRET=…  (au moins 32 caractères aléatoires, obtenus par :)
python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build              # puis http://localhost:8000
```

Puis, une seule fois, le catalogue et les comptes (dans une autre fenêtre) :

```powershell
python scripts/catalogue_paquet.py creer                                 # sur le PC qui a le catalogue (≈ 6 Mo, sans PDF)
docker compose cp catalogue-AAAAMMJJ.tar.gz sourcia:/tmp/catalogue.tar.gz
docker compose exec sourcia python scripts/catalogue_paquet.py importer /tmp/catalogue.tar.gz
docker compose restart
docker compose exec sourcia sourcia comptes ajouter prenom.nom@lycee.fr --url http://localhost:8000
docker compose exec sourcia sourcia comptes demo --url http://localhost:8000     # compte démo (jury) avec un dossier prêt
```

Chaque commande `comptes` affiche un lien de connexion : c'est un secret, à transmettre en privé. Relancer
`comptes demo` donne un nouveau lien et rend l'ancien inutilisable ; `--url` doit être l'adresse que les gens ouvriront
(l'adresse publique une fois en ligne).

**Mode serveur** (`config/serveur.yaml`, utilisé par l'image) : n'importe qui peut chercher dans le catalogue, mais
lancer une formation ou des supports demande d'être connecté (sinon n'importe qui pourrait vider le quota Gemini).
Le serveur refuse de démarrer sans `SOURCIA_SESSION_SECRET`. La recherche y est « légère » (pas de PyTorch).

**Accès libre** (`acces_libre: true`, activé dans `config/serveur.yaml` pour le prototype) : personne n'a de jeton à
saisir. Chaque visiteur reçoit automatiquement un compte anonyme, gardé un mois dans son navigateur, et ne voit que
ses propres dossiers. Pour protéger la clé Gemini partagée, un visiteur lance au plus 3 corpus et 3 productions de
supports par jour (`limite_visiteur_corpus`, `limite_visiteur_supports`). Les comptes avec jeton marchent toujours
et ne sont pas limités. Pour revenir aux jetons obligatoires : `acces_libre: false`.

Chez un hébergeur (Render, Railway, Fly.io, serveur de l'établissement…), il faut **Docker, un disque persistant monté
sur `/data` et le HTTPS** : le pas à pas complet (secrets, premier lancement, sauvegarde, mises à jour) est dans
[`docs/DEPLOIEMENT.md`](docs/DEPLOIEMENT.md).

⚠️ Le niveau gratuit de Gemini est réservé aux essais : un service ouvert à de vrais utilisateurs (Espace économique
européen) doit passer au niveau payant.

## Configurations

| Fichier | Modèle | Recherche (embeddings) | Usage |
|---|---|---|---|
| `config/rapide.yaml` | Ollama qwen2.5:1.5b | hashing (aucun modèle) | premier essai en 1 minute |
| `config/local.yaml` | Ollama qwen2.5:3b | multilingual-e5-small | usage normal, tout reste sur le PC |
| `config/gcp.yaml` | Gemini Flash-Lite (LiteLLM) | e5 en local | clé dans `.env` ; documents privés envoyés seulement avec l'accord de l'enseignant |
| `config/serveur.yaml` | Gemini Flash-Lite (LiteLLM) | hashing (sans PyTorch) | serveur en ligne et image Docker : connexion obligatoire, données dans `/data` |
| `config/test.yaml` | factice | hashing | tests automatiques |

Changer de modèle = changer de fichier, pas le code. `-c <fichier>` choisit la configuration (sinon la variable
`SOURCIA_CONFIG`, sinon `config/local.yaml`) ; la variable `SOURCIA_DATA_DIR` remplace le dossier des données.
Un index de recherche est propre à sa configuration : après un changement de configuration, relancer `index`.

## Les garde-fous

- **Pas de valeur sans preuve** : une valeur proposée par le modèle est rejetée si sa preuve ne se retrouve pas dans le document, ou si le nombre donné (année, modalités, répétitions) ne figure pas dans la preuve.
- **« Non trouvé » plutôt qu'une valeur inventée.**
- **Documents privés jamais envoyés à un modèle en ligne** sans l'accord explicite de l'enseignant (verrou dans le code, testé).
- **Justification construite à partir de la fiche et du passage trouvé** : elle ne peut pas inventer.
- **Formation** : un point clé, une définition ou une explication de QCM non retrouvé dans le passage cité est retiré (et listé en annexe) ; un chiffre doit figurer à l'identique dans la source ; la bonne réponse d'un QCM doit être celle que l'explication justifie.
- **Collecte polie** : robots.txt respecté, une requête par seconde au plus par site ; une protection anti-robots n'est jamais contournée (le site est signalé en échec).
- **Articles : le texte de l'article seul**, sans les « articles liés » ni les encadrés de la page, pour qu'une preuve ne vienne jamais d'un autre article.
- **Un lien n'est déclaré mort qu'avec certitude** : 404/410 ou page HTML à la place du PDF ; une panne passagère ne compte qu'après 3 échecs de suite.
- **En ligne** : connexion obligatoire pour ce qui appelle le modèle ; aucun secret ni aucune donnée dans l'image Docker ; le paquet du catalogue ne contient ni PDF ni chemin de l'ordinateur d'origine.

## Ce que fait l'outil, module par module

| Module | Rôle | Commande |
|---|---|---|
| **M0 Demande** | les 7 critères du métier (profil, type de formation, public, ressources, sorties, sources, contenu personnel) | `demande`, `--demande-fichier`, page web |
| **M1 Collecte** | sites prioritaires chaque jour (PDF et articles web), liens déplacés ou morts ; vidéos, photos, données (`--medias`), catalogue, documents privés | `collect-sites`, `check-links`, `add-site`, `import-catalog`, `add-folder`, `download` |
| **M2 Extraction** | lire le texte (d'abord les premières pages) | `extract` |
| **M3 Qualification** | une **fiche** par document (organisme, année, lieu, contexte, type, dispositif, chiffrage), **chaque valeur avec sa preuve** | `qualify`, `fiche` |
| **M4 Recherche** | mots + sens + synonymes métier + reranker | `index`, `search` |
| **M5 Sélection** | entonnoir → ≈ 50 documents classés, filtrés, **justifiés**, diversifiés | `select` |
| **M6 Sorties** | page web, exports (md, csv, txt, json, zip), API, serveur MCP | `serve`, `mcp`, `select --export` |
| **M7 Formation** | support complet à partir d'une sélection du catalogue (voir plus bas) | `formation` |
| **Corpus pédagogique** (étape 3) | à partir des **seuls documents cochés** : séquences, points clés et synthèse avec **références vérifiables** (voir plus bas) | `corpus`, `corpus --dossier`, `corpus-word` |
| **Supports** (étape 4) | à partir du **seul `corpus.json`** : QCM, cartes, présentation, infographie, fiche, glossaire, podcast (voir plus bas) | `supports` |
| **Parcours web** | **Catalogue → Mon dossier → Mon corpus → Mes supports**, sans ligne de commande | `serve` |
| **M8 Référentiels** | capacités des diplômes (chlorofil.fr), versions, rattachement des séquences, validation par l'enseignant, contrôle du niveau | `referentiel`, `valider-formation` |
| **Évaluation** | comparer à une référence fournie par le métier | `eval trouver`, `eval qualifier`, `eval gabarit` |

**M7 Formation** : créer **soi-même** le support : plan, points clés sourcés, QCM (et Moodle), fiche technique,
synthèse, cas concret, glossaire, script de podcast, déroulé de séance, contenu personnel protégé.

**Corpus pédagogique** (`corpus.json`, sans QCM) :
- à partir des **seuls documents cochés** et des acquis visés : séquences rattachées aux capacités, points clés et synthèse ;
- chaque point avec sa **référence vérifiable** : document, page, extrait exact, lien `#page=N` pour un PDF ; bibliographie ;
- document Word avec liens cliquables vers la page citée (`corpus_pedagogique.docx`, `pip install -e ".[word]"`) ;
- **illustrations d'origine** des pages citées (PyMuPDF : logos, bandeaux et décors écartés, légende prise dans le document) ;
- **depuis un dossier enseignant** : documents cochés et prêts du dossier ; PDF téléversés cités « Document fourni par
  le formateur » (API `POST /api/dossiers/{id}/corpus-pedagogique`, tâche de fond, même connexion).

**Supports** (tout ou partie des séquences, chaque information avec sa référence [S1, p. N]) :
- **QCM** sans modèle, justes par construction : Markdown élève et corrigé, Moodle GIFT ; le modèle peut compléter (questions contrôlées) ;
- **cartes** de révision : CSV Anki, HTML à découper ;
- **présentation** `.pptx` (`pip install -e ".[pptx]"`, références dans les notes) et **infographie** A4 (HTML) ;
- avec modèle : **fiche technique**, **glossaire**, **podcast**, contrôlés contre les extraits ;
- API `POST /api/supports` (corpus du catalogue) ou `…/corpus-pedagogique/{cid}/supports` (corpus d'un dossier).

**Deux usages de la sélection :**

| Voie | Entrée | Ce qui est produit | Contrôles |
|---|---|---|---|
| **NotebookLM ou autre outil** (proposition de l'équipe) | export `.txt` (adresses) ou `.zip` (PDF) | ce que produit l'outil | ceux de l'outil |
| **M7 Formation de SourcIA** (complément) | la même sélection | support formateur `.md`, QCM apprenants, QCM Moodle (GIFT), `.json` | dans le code : chaque point, définition et réponse doit se retrouver dans sa source ; sinon retiré et listé ; les **alertes des fiches** (résultats anciens, réglementation…) suivent dans l'annexe des sources |

**Formats d'échange entre modules** (le « contrat » pour l'équipe) : `data/documents.jsonl` et `data/fiches.jsonl`
(voir `src/sourcia/core/models.py`). Dans `documents.jsonl`, le champ facultatif `link` donne l'état du lien (`ok`,
`moved`, `dead`, `unreachable`) : pour afficher ou exporter une adresse, utiliser `doc.current_url` (la nouvelle
adresse si le document a été déplacé) ; `url` et `id` ne changent jamais.

## Comptes enseignants et dossiers

Chaque enseignant a un compte : son adresse e-mail et un **jeton** secret, qui lui sert de mot de passe personnel.
L'option API est incluse dans `.[recommended]` (sinon : `pip install -e ".[api]"`).

**Gérer les comptes** (l'administrateur, sur la machine du serveur) :

```powershell
sourcia comptes ajouter prenom.nom@lycee.fr --url https://adresse-du-serveur
sourcia comptes lister
sourcia comptes retirer prenom.nom@lycee.fr
```

- `ajouter` affiche le jeton **une seule fois**, avec un **lien de connexion directe** (`…/dossiers#jeton=…`) :
  transmettez l'un ou l'autre à l'enseignant par un canal privé.
- Seule l'empreinte du jeton est rangée dans `<data_dir>/comptes.json` ; le fichier est relu dès qu'il change, sans relancer le serveur.
- `--remplacer` donne un nouveau jeton à un compte existant (les sessions ouvertes avec l'ancien s'arrêtent).
- La variable d'environnement `SOURCIA_DOSSIER_ACCOUNTS` (objet JSON adresse → jeton) reste acceptée.

**Session** : l'enseignant saisit son jeton une fois (ou ouvre son lien) ; un cookie protégé (HttpOnly,
SameSite=Strict, Secure en HTTPS) le garde connecté 12 heures, sur toutes les pages, catalogue compris.
« Se déconnecter » ferme la session. En accès libre, un visiteur sans jeton a un compte anonyme (voir « Mettre en
ligne »). `SOURCIA_SESSION_SECRET` (au moins 32 caractères aléatoires) garde les sessions
après un redémarrage : sur son PC, sans elle, il suffit de se reconnecter ; **en mode serveur, elle est obligatoire**.

**Démonstration** : `sourcia comptes demo` crée le compte `demo@sourcia.local` avec un dossier déjà rempli de
documents publics du catalogue (`--sujet`, `--documents`) et affiche son lien. Rien n'existe sans cette commande ;
`sourcia comptes retirer demo@sourcia.local` le supprime.

**Dossiers** (`/dossiers` dans l'interface web) :
- le partage donne accès au compte correspondant à l'adresse e-mail ;
- la fin du traitement s'affiche dans le dossier ; après une interruption du serveur, le bouton « Relancer » reprend le traitement ;
- en ligne : gardez `<data_dir>` (comptes et dossiers) sur un volume persistant et servez l'interface en HTTPS.

**Intégrer la consolidation** : `GET /api/dossiers/{id}/corpus` avec le jeton de l'enseignant. La réponse fournit les
sources cochées et prêtes, leurs fiches de qualification et leur texte par page. Le ZIP inclut la fiche JSON de chaque
source et la transcription d'une vidéo lorsque l'extraction a pu la produire à partir d'un fichier local.

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

## Travailler à plusieurs

**Tests** : `pytest` (environ 2 minutes ; aucun réseau ni modèle : modèle simulé, `config/test.yaml`).
La même suite tourne sur GitHub à chaque push et à chaque PR ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)),
puis l'image Docker est construite et démarrée pour vérifier qu'elle répond. Le badge en haut de cette page dit si tout est vert.

**Règles** :
- une branche par sujet, une PR vers `main` ; la CI doit être verte avant de fusionner ;
- jamais dans git : `data/` (documents de tiers, comptes, dossiers), `.env` (clés), les paquets `catalogue-*.tar.gz` ;
  attention aux `git add -A` ;
- les liens de connexion, les jetons et le paquet du catalogue s'échangent par un canal privé.

**Arborescence** :

| Dossier | Contenu |
|---|---|
| `src/sourcia/` | le code (un sous-dossier par module : `collect`, `extract`, `qualify`, `search`, `select`, `formation`, `api`…) |
| `src/sourcia/api/static/` | les pages web (HTML, CSS, JS, polices) |
| `config/` | configurations, sites, synonymes, référentiels des diplômes, exemples de demandes |
| `tests/` | tests automatiques (`pytest`) et corpus d'exemple figé |
| `scripts/` | collecte quotidienne, paquet du catalogue |
| `docs/` | architecture, plan de tests, journal, mise en ligne |
| `data/` | données locales, hors de git (seul `data/samples/`, fictif, est versionné) |

## Documentation

- [`docs/DOSSIER_ARCHITECTURE.md`](docs/DOSSIER_ARCHITECTURE.md) : **le dossier pour l'équipe** (besoins → blocs, sous-défis, contrats, propositions pour les questions ouvertes)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) : détails techniques de M1 à M7
- [`docs/PLAN_TESTS.md`](docs/PLAN_TESTS.md) : installation et tests pas à pas, avec les commandes
- [`docs/JOURNAL_TESTS.md`](docs/JOURNAL_TESTS.md) : résultats obtenus, problèmes et corrections
- [`docs/DEPLOIEMENT.md`](docs/DEPLOIEMENT.md) : mise en ligne pas à pas (Docker, secrets, catalogue, comptes, sauvegarde)

## Licence

MIT pour le code. Les documents collectés gardent leur propre licence (ex. RD Agri : CC BY-NC-SA) : la colonne `licence` est conservée.
