# SourcIA : dossier d'architecture (Défi 1, hackathon SAED)

> **Auteure** : Corinne Bergès · **Version du code** : `s3` (novembre 2026) · **Statut** : proposition à valider par l'équipe
> **En une phrase** : à partir d'une **demande structurée** du formateur, SourcIA trouve et qualifie les sources de R&D (des milliers de documents → environ 30 à 50 sources justifiées), puis les donne à NotebookLM **ou** produit lui-même le support de formation, rattaché au **référentiel officiel** du diplôme quand la formation est diplômante.

---

## Sommaire

1. Les besoins et leur couverture
2. Vue d'ensemble
3. Proposition de découpage du Défi 1 en sous-défis
4. Les blocs, un par un
5. Les contrats d'échange (formats)
6. Trois parcours d'utilisateurs
7. Garde-fous, confidentialité, conformité
8. Propositions pour les questions ouvertes
9. Évaluation
10. Ce qui est testé, ce qui ne l'est pas encore
11. Limites et suites
12. Annexe : commandes

---

## 1. Les besoins et leur couverture

Sources des besoins : compte rendu du kick-off (03/11), mail du point métier avec Lionel (09/11), fils du forum.

| # | Besoin exprimé | Source | Bloc(s) | État |
|---|---|---|---|---|
| B1 | Trouver ≈ 50 sources pertinentes parmi des milliers | kick-off, fil « retrouver vite des références » | M1, M4, M5 | ✅ codé, testé sur exemples |
| B2 | Qualifier les documents (organisme, année, lieu, contexte, type, dispositif, chiffrage) | kick-off, fil « aider à qualifier » | M3 | ✅ codé, testé ; colonnes définitives = « l'Excel » du métier |
| B3 | Distinguer expérimentation et retour d'expérience | kick-off | M3 (type), M5 (filtre) | ✅ |
| B4 | Points de vigilance : résultats anciens (avant 2022), contexte éloigné, réglementation ancienne, pas de chiffrage | kick-off | M3 (alertes), M5 (région) | ✅ |
| B5 | Sortie utilisable par NotebookLM ou un autre outil | kick-off | M6 (exports .txt, .zip, .csv) | ✅ |
| B6 | **Profil du demandeur** (enseignant, formateur, conseiller, intervenant extérieur) | mail 09/11 | M0 → M5 (préférences), M7 (ton) | ✅ |
| B7 | **Type de formation** : diplômante ou non ; présentiel, distanciel, oral, écrit | mail 09/11 | M0 → M7 (sorties), M8 (référentiel) | ✅ |
| B8 | **Public cible** : type d'apprenant, niveau d'étude, expérience | mail 09/11 | M0 → M5, M7, M8 (contrôle du niveau) | ✅ |
| B9 | **Types de ressources** : données, résultats R&D, expérimentation, témoignage, photo, vidéo | mail 09/11 | M0 → M1 (collecte des médias), M2, M5 (filtres) | ✅ codé ; photo et vidéo qualifiées sur leurs **métadonnées** |
| B10 | **Forme du résultat** : fiche technique, quiz, synthèse, cas concret, podcast… | mail 09/11 | M7 | ✅ (podcast : **script** ; l'audio reste à NotebookLM ou une voix de synthèse) |
| B11 | **Précisions sur les sources** : publique ou non, année de sortie, dispositif, structure | mail 09/11 | M3 (fiche), M5 (filtres), M7 (annexe des sources) | ✅ année de **publication** séparée de l'année des **résultats** |
| B12 | **Compléter le résultat par du contenu personnel** | mail 09/11 | M0, M7 (notes et fichiers personnels, blocs protégés) | ✅ |
| B13 | **Valider le niveau** de la formation (CAP, bac pro, BTS…) avec les **référentiels** | échange du 09/11 | M8 | ✅ référentiels extraits de chlorofil.fr (3 diplômes), rattachement, validation par un enseignant |
| B14 | Mesurer que l'outil fait mieux que l'existant | kick-off | Évaluation | ✅ outil prêt ; **le jeu de référence doit venir du métier** |
| B15 | Documents privés du formateur | kick-off | M1, verrou M3/M7 | ✅ jamais envoyés à un modèle en ligne (testé) |
| B16 | Frugalité, coût maîtrisé | kick-off | M3 (règles puis modèle), cache, M7 | ✅ coût mesuré par document et par formation |

---

## 2. Vue d'ensemble

```
                 ┌──────────────────────────────────────────────────────────────┐
                 │ M0 DEMANDE STRUCTURÉE (les 7 critères du métier)             │
                 │ profil · type de formation · public · ressources · sorties   │
                 │ · précisions sur les sources · contenu personnel → demande.yaml
                 └──────────────┬───────────────────────────────┬───────────────┘
                                │ filtres, préférences           │ diplôme, capacités, public, sorties
 Sites, catalogues (RD Agri),   ▼                                ▼
 dossiers privés      ┌───────────────────┐            ┌──────────────────────────────┐
        │             │ M5 SÉLECTION      │            │ M8 RÉFÉRENTIELS (chlorofil.fr)│
        ▼             │ entonnoir, score, │            │ capacités, versions,          │
 ┌──────────────┐     │ diversité,        │            │ validation enseignant,        │
 │ M1 COLLECTE  │     │ justification     │            │ contrôle du niveau            │
 │ PDF, pages,  │     └───────▲───────┬───┘            └──────────────┬───────────────┘
 │ données,     │             │       │ ≈ 30–50 sources justifiées    │
 │ photos,      │     ┌───────┴─────┐ │                               │
 │ vidéos       │     │ M4 RECHERCHE│ ├──────────────► M6 SORTIES ───► NotebookLM / autre outil
 └──────┬───────┘     │ mots + sens │ │               (exports, page web, API, MCP)
        ▼             └───────▲─────┘ │                               │
 ┌──────────────┐             │       ▼                               ▼
 │ M2 EXTRACTION│      ┌──────┴──────────────┐         ┌──────────────────────────────────────┐
 │ texte, pages,│─────►│ M3 QUALIFICATION    │         │ M7 FORMATION                          │
 │ métadonnées  │      │ fiche + preuves +   │────────►│ plan rattaché aux capacités, points   │
 └──────────────┘      │ alertes             │         │ clés sourcés, QCM, fiche technique,   │
                       └─────────────────────┘         │ synthèse, cas concret, glossaire,     │
                                                       │ podcast (script), déroulé, contenu    │
                                                       │ personnel → support .md, Moodle (GIFT)│
                                                       └──────────────────────────────────────┘
 Transverse : ÉVALUATION (référence métier) · traces et coûts · modèles locaux ou en ligne par configuration
```

**Deux voies de production, une seule sélection**

| Voie | Pour qui | Ce qui est contrôlé |
|---|---|---|
| **NotebookLM ou autre outil** (proposition du kick-off) | qui a déjà l'outil, veut l'audio | ce que fait l'outil |
| **M7 Formation de SourcIA** | qui veut un support rattaché au référentiel, sourcé page par page, avec ses alertes, en local | dans le code : chaque contenu doit se retrouver dans sa source, sinon il est retiré et listé |

---

## 3. Proposition de découpage du Défi 1 en sous-défis

Le mail du 09/11 propose de « déposer des défis dans le Défi 1 ». Proposition, alignée sur les blocs :

| Sous-défi | Objet | Blocs | Livrable vérifiable |
|---|---|---|---|
| **1a. Structurer la demande** | le formulaire des 7 critères, commun à tous | M0 | `demande.yaml` validé par le métier |
| **1b. Trouver** | des milliers de documents → 30 à 50 sources | M1, M4, M5 | rappel@50 sur les demandes de référence |
| **1c. Qualifier** | la fiche de chaque document, avec preuves | M2, M3 | exactitude par champ, taux de valeurs fausses |
| **1d. Rattacher au référentiel** | diplômes, capacités, niveau | M8 | référentiels validés ; rattachements validés |
| **1e. Produire** | le support (NotebookLM ou M7) | M6, M7 | part de contenus retirés ; avis des formateurs |
| **1f. Évaluer** | le jeu de référence et les comparaisons | Évaluation | tableau de résultats partagé |

Chaque sous-défi peut être pris par une personne ou un groupe : les **formats d'échange** (section 5) permettent de remplacer un bloc sans toucher aux autres.

---

## 4. Les blocs, un par un

### M0 Demande structurée (`core/demande.py`, `config/demandes/`)

| Critère du métier | Champs | Valeurs proposées |
|---|---|---|
| 1. Profil du demandeur | `profil` | enseignant, formateur, conseiller, intervenant_exterieur, autre |
| 2. Type de formation | `diplomante`, `diplome`, `capacites`, `modalite`, `supports`, `duree_min` | modalité : présentiel, distanciel, hybride ; supports : écrit, oral, pratique |
| 3. Public cible | `apprenants`, `niveau`, `experience`, `effectif` | élèves, apprentis, étudiants, salariés, chefs d'entreprise, conseillers ; CAP à master ; débutant à confirmé |
| 4. Types de ressources | `ressources` | résultats R&D, expérimentation, témoignage, synthèse, guide technique, données, photo, vidéo, audio |
| 5. Formes de résultat | `sorties` | plan, points clés, quiz, fiche technique, synthèse, cas concret, glossaire, podcast, déroulé oral |
| 6. Précisions sur les sources | `annee_min`, `annee_max`, `sources_publiques_seulement`, `region`, `organismes`, `nombre_sources` | `organismes` = bonus de score, pas un filtre |
| 7. Contenu personnel | `notes_personnelles`, `fichiers_personnels`, `autoriser_cloud_personnel` | privé par défaut, jamais vers un modèle en ligne sauf accord |

- Saisie : formulaire de la page web, ou fichier YAML (`sourcia demande ma_demande.yaml` écrit un modèle commenté).
- Trois exemples fournis : BTSA diplômant (C4.2, C4.3), agriculteurs en distanciel (fiche technique, podcast), CAPa (CP5).

### M1 Collecte (`collect/`)

- **Sites** : à partir d'une adresse ; `robots.txt` respecté ; plans de site ; exploration du même site ; une requête par seconde au plus ; liens PDF avec le texte du lien comme titre ; filtre `--include`.
- **Médias** (`--medias`) : vidéos (YouTube, Vimeo, Dailymotion, Canal-U, PeerTube, .mp4), photos (balise `<img>` avec un texte alternatif parlant ; logos et pictogrammes ignorés), jeux de données (.csv, .xlsx, .json), audio.
- **Catalogues** : CSV, JSON, liste d'adresses (export RD Agri via le Lexicon) ; colonnes reconnues automatiquement, dont la nature de la ressource et la description.
- **Dossiers privés** : PDF, textes, données, photos, vidéos, audio ; **privés par défaut**.
- **Doublons** : même empreinte (sha1) sur deux sites → un seul document.

### M2 Extraction (`extract/pdf.py`, `collect/media.py`)

| Nature | Ce qui est lu |
|---|---|
| PDF | texte page par page (PyMuPDF, sinon pypdf) ; PDF scanné détecté → alerte « OCR nécessaire » |
| Texte, page web | texte nettoyé |
| Données | description : colonnes, nombre de lignes, exemple de ligne |
| Audio, vidéo locale | transcription si `faster-whisper` est installé (facultatif) |
| Photo, vidéo en ligne | **métadonnées seules** : titre, texte alternatif, page d'origine, description ; signalé |

### M3 Qualification (`qualify/`)

- **Passe 1, règles** (tous les documents, coût nul) ; **passe 2, modèle** (seulement les mieux classés, coût mesuré) ; **fusion** : accord des deux → confiance augmentée.
- La fiche : organisme, **année des résultats**, **année de publication**, lieu, contexte pédoclimatique, type, modalités, répétitions, chiffrage économique, thèmes, résumé, alertes.
- **Chaque valeur a sa preuve** (phrase du document) et une confiance ; « non trouvé » plutôt qu'une valeur devinée.
- Garde-fous de la passe modèle : preuve retrouvée dans le texte ; un nombre doit figurer **dans** sa preuve ; document privé jamais envoyé à un modèle en ligne ; échec du modèle → on garde les règles.
- **Alertes** : résultats antérieurs à 2022 ; résultats anciens dans un document récent (« résultats de 2016 publiés en 2022 ») ; réglementation ancienne (glyphosate…) ; pas de chiffrage ; lieu non trouvé ; retour d'expérience sans dispositif ; PDF scanné ; ressource qualifiée sur ses seules métadonnées ; droits d'utilisation d'une photo ou d'une vidéo ; licence d'un jeu de données.

### M4 Recherche (`search/`)

- BM25 (mots, avec un petit lexique métier : fissurateur = décompacteur…) + embeddings (sens) fusionnés par rang réciproque ; reranker lexical ou cross-encoder.
- Seuil de similarité à **calibrer** par modèle d'embeddings (sinon tout le corpus remonte).

### M5 Sélection (`select/funnel.py`)

1. recherche (jusqu'à 300 candidats) ;
2. qualification (règles pour tous, modèle pour les N premiers) ;
3. filtres de la demande : années (résultats, sinon publication), types de documents (déduits des **ressources** demandées), natures (données, photo, vidéo…), sources publiques seulement ;
4. score = 0,6 pertinence + 0,2 récence + 0,2 qualité du dispositif + **bonus de la demande** (préférences du profil et du public, organismes à privilégier) ;
5. diversité : au plus N documents d'un même organisme ;
6. justification construite à partir de la fiche et du passage : **elle ne peut pas inventer** ; alerte « contexte éloigné de <région> (essai en <région>) » grâce à la table régions-départements.

### M6 Sorties (`export/`, `api/`, `mcp_server/`)

- Exports : `.txt` (adresses web publiques, pour NotebookLM), `.zip` (PDF), `.csv` (relecture dans un tableur), `.md`, `.json` (avec la demande structurée).
- Page web : formulaire des 7 critères, sources justifiées avec fiche et preuves, création de la formation, validation des rattachements.
- API REST et serveur **MCP** (`chercher_sources`, `selectionner_sources`, `fiche_document`, `lister_referentiels`, `creer_formation`) : un agent de l'équipe peut appeler SourcIA sans connaître son code.

### M7 Formation (`formation/`)

| Étape | Ce qui se passe |
|---|---|
| Contenu personnel | notes et fichiers ajoutés au corpus, **privés** |
| Mini-corpus | seulement les sources sélectionnées, en passages ; au plus 2 passages par document par question (diversité) |
| Plan | séquences avec objectif commençant par un verbe d'action ; **diplômante** : une capacité visée par séquence, capacités non couvertes **ajoutées** ; repli sans modèle (une séquence par capacité, ou par thème) |
| Par séquence | points clés cités [n], QCM (on en demande 2 de plus, on garde ceux qui passent les contrôles) |
| Sorties demandées | fiche technique, synthèse, glossaire, cas concret (exploitation fictive), script de podcast à deux voix, déroulé de séance adapté à la modalité |
| Contrôles | soutien par la source (mots porteurs de sens, **chiffres à l'identique**) ; QCM : explication soutenue, bonne réponse cohérente avec l'explication (corrigée sinon), ni ambiguë ni en double ; doublons retirés |
| Niveau | voir M8 |
| Fichiers | `support_formateur.md`, `quiz_apprenants.md`, `quiz_moodle.gift.txt`, `podcast_script.md`, `rattachements.csv`, `formation.json`, `demande.yaml` |

- **Blocs personnels** dans le support : ce que le formateur y écrit est **conservé** quand il régénère (`--reprendre`).
- Annexe A : sources (S1, S2…) avec leurs alertes ; annexe B : tout ce que les contrôles ont retiré ; annexe C : remarques (rattachements corrigés, capacités ajoutées).

### M8 Référentiels et niveau (`referentiel/`)

| Fonction | Comment |
|---|---|
| **Source** | chlorofil.fr, portail pédagogique de l'enseignement agricole |
| **Catalogue** | `config/referentiels/catalogue.yaml` : diplôme, niveau (cadre national des certifications : CAPa 3, bac pro 4, BTSA 5), version, adresses des PDF |
| **Extraction** | sans modèle : codes (`C4.2`, `C 6.1.`, `CP5 –`, `CG1.1 -`), capacités mères (« Capacité 5 correspondant au bloc de compétences B5 »), libellés sur deux lignes ; **une capacité commence par un verbe à l'infinitif** (filtre du bruit) ; libellés différents selon le support (CAPa) gardés en **variantes** |
| **Déjà extraits** | CAPa Métiers de l'agriculture 2024 (28 capacités), bac pro CGEA 2024 (35), BTSA ACS'Agri 2025 (21, blocs C4 à C8) |
| **Versions** | empreinte des PDF ; essai de l'année suivante dans le nom du fichier ; exploration de la page du diplôme si renseignée ; une nouvelle version ne remplace jamais l'ancienne d'office (statut « à revoir ») |
| **Validation du référentiel** | une fois par diplôme et par version : tableau CSV pour un enseignant (valide, libellé corrigé, commentaire) |
| **Rattachement** | chaque séquence ↔ une capacité visée ; code inexistant ou hors cible → retiré et signalé ; couverture de toutes les capacités visées |
| **Validation du rattachement** | par l'enseignant, dans la page web ou le CSV ; un rattachement validé est **mémorisé** et réutilisé (« déjà validé ») |
| **Contrôle du niveau** | (1) verbe de l'objectif classé selon la taxonomie de Bloom (1 se souvenir … 6 créer), comparé au niveau attendu pour le public et au verbe de la capacité ; (2) lisibilité du texte (formule de Kandel et Moles, adaptation française de Flesch) ; seuils **proposés, à calibrer** |
| **Formation non diplômante** | pas de référentiel : niveau contrôlé par les verbes et la lisibilité |

---

## 5. Les contrats d'échange (formats)

| Fichier | Produit par | Lu par | Contenu |
|---|---|---|---|
| `demande.yaml` | M0 (page, YAML) | M5, M7, M8 | les 7 critères |
| `data/documents.jsonl` | M1 | M2 à M7 | un document par ligne : id, adresse, source, titre, date, nature, licence, privé, empreinte, statut |
| `data/text/<id>.json` | M2 | M3, M4, M7 | pages de texte (ou description, transcription, métadonnées) |
| `data/fiches.jsonl` | M3 | M5, M6, M7, évaluation | une fiche par document : chaque champ = valeur, preuve, confiance, méthode |
| `config/referentiels/<id>.yaml` | M8 | M0, M7 | diplôme, version, capacités, statuts de validation |
| `data/exports/selection-*.json` | M5, M6 | NotebookLM (via .txt), M7 | documents classés, justification, demande structurée |
| `data/formations/<date>/formation.json` | M7 | page web, autre outil | la formation complète, rechargeable |
| `data/rattachements_valides.jsonl` | M8 | M7 | rattachements validés par les enseignants |

---

## 6. Trois parcours d'utilisateurs

**Enseignante de BTSA, formation diplômante**
1. Coche « diplômante », choisit BTSA ACS'Agri, coche C4.2 et C4.3 ; public étudiants BTS ; présentiel, écrit et oral.
2. Obtient 20 sources justifiées, avec alertes (« contexte éloigné », « résultats de 2016 »).
3. Crée la formation : une séquence par capacité, points clés sourcés, QCM, déroulé de séance ; le tableau de niveau signale un objectif trop bas.
4. Valide les rattachements dans la page ; ajoute ses exemples dans les blocs personnels ; régénère sans les perdre.

**Conseiller, éleveurs en formation continue à distance**
1. Profil conseiller, chefs d'entreprise confirmés, distanciel ; sources publiques seulement ; sorties : fiche technique, synthèse, podcast.
2. Les expérimentations chiffrées sont favorisées (préférence du profil) ; ses notes du groupe d'éleveurs sont ajoutées, privées.
3. Récupère la fiche technique, la synthèse, le QCM pour Moodle, le script du podcast (audio avec NotebookLM).

**Formateur qui préfère NotebookLM**
1. Remplit la demande, obtient la sélection.
2. Télécharge le `.txt` (adresses) ou le `.zip` (PDF) et le charge dans NotebookLM ; garde le `.csv` des fiches pour vérifier les sources.

---

## 7. Garde-fous, confidentialité, conformité

| Sujet | Règle dans le code |
|---|---|
| Hallucinations | chaque contenu doit se retrouver dans sa source ; chiffres à l'identique ; sinon retiré et listé (annexe B) |
| Valeurs inventées | « non trouvé » plutôt qu'une valeur devinée ; valeur du modèle sans preuve retrouvée → rejetée |
| Documents privés et contenu personnel | jamais envoyés à un modèle en ligne, sauf accord explicite (`autoriser_cloud_personnel`) ; jamais d'adresse dans les exports ni le MCP |
| Transparence (règlement européen sur l'IA) | chaque support porte la mention « contenu généré par IA, à relire avant diffusion » |
| Licences | conservées par document (RD Agri : CC BY-NC-SA, usage non commercial) ; alerte de droits sur les photos et vidéos |
| Collecte | robots.txt, une requête par seconde, identifiant de robot explicite sans adresse personnelle |
| Secrets | clés d'API dans `.env`, jamais dans le code |
| Modèle en ligne | niveau gratuit de Gemini réservé aux essais ; un service ouvert à des utilisateurs de l'EEE doit passer au niveau payant |

---

## 8. Propositions pour les questions ouvertes

Pour pouvoir tout coder sans attendre, chaque question a une **valeur par défaut** : la plus probable, et modifiable en un endroit.

| Question ouverte | Proposition codée | Où la changer | À valider par |
|---|---|---|---|
| Colonnes de « l'Excel » de qualification | les 10 champs de la fiche (section 4, M3) | `core/models.py` (Fiche) + consigne du modèle | Janick, Lionel |
| Valeurs des 7 critères | listes de la section 4, M0 | `core/demande.py` | métier |
| Préférences par profil et par public | conseiller → expérimentations ; enseignant → synthèses ; chefs d'entreprise → témoignages ; salariés, apprentis → guides techniques | `PREFERENCES` dans `core/demande.py` | métier |
| Référentiels prioritaires | BTSA ACS'Agri (C4 pour le fil rouge), bac pro CGEA, CAPa Métiers de l'agriculture | `config/referentiels/catalogue.yaml` | enseignants |
| Source des référentiels | chlorofil.fr | catalogue | métier |
| Seuils de niveau | verbes : CAP 1 à 3, bac pro 1 à 4, BTS 2 à 6, licence 3 à 6 ; lisibilité minimale : CAP 60, bac pro 50, BTS 35 | `referentiel/niveau.py` | enseignants, sur des supports réels |
| Documents privés | jamais vers un modèle en ligne | `qualify/pipeline.py`, `formation/corpus.py` | équipe |
| Photos et vidéos | indexées sur leurs métadonnées ; transcription locale facultative ; pas d'analyse d'image | `collect/media.py` | métier (besoin réel ?) |
| Podcast | script à deux voix ; audio par NotebookLM ou voix de synthèse plus tard | `formation/builder.py` | métier |
| Modèle | local qwen2.5:3b (souverain, gratuit) ; Gemini Flash-Lite par configuration pour les documents publics | `config/*.yaml` | équipe |
| Hébergement de la démonstration (Tech Élevage) | un serveur avec Ollama (aucune donnée ne sort), ou Gemini en niveau payant | configuration | organisateurs |
| Connecteur RD Agri | import du catalogue du Lexicon en attendant la documentation du MCP | `collect/catalog.py` | OSFARM |
| Nombre de sources | 30 par défaut (50 au plus conseillé pour NotebookLM) | `nombre_sources` | formateurs |
| Dépôt du code | Forge OSFARM | — | organisateurs |

---

## 9. Évaluation

| Mesure | Référence | Indicateurs |
|---|---|---|
| **Trouver** | 10 à 20 demandes réelles + documents attendus (`data/eval/demandes.jsonl`) | rappel@N et MRR, comparés à : titres seuls (≈ moteur par mots-clés), mots seuls, sens seul, hybride, sélection complète |
| **Qualifier** | 30 à 50 documents qualifiés à la main (`sourcia eval gabarit` prépare le tableau) | exactitude par champ et **taux de valeurs fausses** |
| **Produire** | supports relus par des formateurs | part de contenus retirés par les contrôles ; erreurs restantes trouvées à la relecture ; comparaison avec NotebookLM sur la même sélection |
| **Niveau** | supports jugés par des enseignants | accord entre l'alerte de niveau et l'avis de l'enseignant |
| **Coût** | — | secondes et appels au modèle par document et par formation |

⚠️ Les exemples fournis (`data/samples`) sont **fictifs** et écrits avec les formulations des règles : ils vérifient que le code marche, **ils ne mesurent pas** la qualité réelle.

---

## 10. Ce qui est testé, ce qui ne l'est pas encore

**Testé (63 tests automatiques, dont une vingtaine construits sur des résultats réels) et sur le PC de l'auteure (CPU, 8 Go, qwen2.5:3b, 9 novembre 2026)** :

| Bloc | Résultat réel |
|---|---|
| Installation, tests, démonstration | OK sous Windows |
| M8 référentiels | 3 référentiels extraits des PDF officiels ; **téléchargement direct depuis chlorofil.fr réussi** (empreinte identique) |
| M0 + M5 demande structurée | filtres et alertes justes (« contexte éloigné (essai en Bretagne) ») |
| M4 recherche e5 | hors-sujet écartés grâce à une règle relative (un seuil absolu ne marche pas avec e5) |
| M3 passe modèle | 0 valeur fausse ; meilleures valeurs que les règles ; **200 s par document** sur CPU → modèle seulement sur les N premiers |
| M7 formation diplômante | après 6 itérations sur les résultats réels : 8 points clés justes, QCM justes, rattachements C4.2 / C4.3, 6 à 15 min |
| M8 validation enseignant + contenu personnel | validation importée ; bloc personnel conservé à la régénération |
| M7 formation non diplômante, à distance | sources publiques seulement respecté ; notes personnelles citées |
| M6 page web | parcours complet sans erreur |

**Ce que les essais réels ont appris** (détail dans `JOURNAL_TESTS.md`) : le petit modèle invente des chiffres, mélange les sources (sorgho / méteil), part en boucle, recopie la consigne, cite le mauvais passage. Les contrôles dans le code ont été ajustés pour **retirer ces erreurs sans rejeter les phrases justes** ; un QCM faux (méteil / juin) a été détecté puis bloqué. Les QCM construits **sans modèle** à partir des points vérifiés sont les plus fiables.

**Pas encore testé** : vrais sites et vrais PDF (étape 12), Gemini (étape 13), transcription audio et vidéo, seuils de niveau sur des supports réels jugés par des enseignants.

## 11. Limites et suites

- Contrôles **lexicaux** : ni paraphrase ni négation comprises → relecture humaine obligatoire ; évolution possible : modèle d'inférence (NLI) local.
- Photos et vidéos : métadonnées seulement ; évolutions : transcription systématique, description d'image par un modèle de vision local.
- Pas d'OCR des PDF scannés ; tableaux des PDF non exploités (le dispositif y est souvent).
- BTSA ACS'Agri : capacités générales C1 à C3 à compléter avec le référentiel de diplôme complet.
- Seuils de niveau à calibrer ; règles de qualification à recalibrer sur de vrais documents.

---

## 12. Annexe : commandes

```text
sourcia doctor                                   vérifier l'installation
sourcia demo                                     tout le pipeline sur les exemples fictifs
sourcia demande ma_demande.yaml                  modèle de demande structurée à remplir
sourcia add-site <adresse> [--medias]            M1 : un site (PDF, et vidéos, photos, données)
sourcia import-catalog <fichier> --source <nom>  M1 : un catalogue (RD Agri…)
sourcia add-folder <dossier>                     M1 : documents privés
sourcia download · extract · qualify [--llm] · index
sourcia select --demande-fichier ma_demande.yaml --export json,txt,csv
sourcia formation [--demande-fichier …] [--reprendre <dossier>]
sourcia valider-formation <dossier> --par "Nom"
sourcia referentiel liste | voir <id> | construire <id> | verifier <id> | valider <id> | importer <id> --csv … --par …
sourcia eval trouver | qualifier | gabarit
sourcia serve                                    page web : http://127.0.0.1:8000
sourcia mcp                                      serveur MCP
```
