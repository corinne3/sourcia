# Défi 1 : proposition d'architecture pour « trouver » et « qualifier » les sources de R&D

> **Auteure** : Corinne Bergès · **Statut** : proposition, à discuter sur le forum
> **Nom de travail du projet** : *SourcIA* (provisoire)
> **En une phrase** : aider un formateur à passer de **milliers de documents de R&D** à **environ 50 sources pertinentes, récentes et qualifiées**, justifiées une par une, prêtes à être chargées dans NotebookLM ou tout autre outil de génération.

---

## 1. Principes

| Principe | Conséquence |
|---|---|
| **La valeur est en amont** | on ne refait pas NotebookLM : on livre une **sélection de documents qualifiés** ; l'outil de génération reste **interchangeable** |
| **Le métier définit la qualité** | les critères de qualification (« l'Excel » de Janick et Lionel) et les demandes de formateurs deviennent le **jeu de référence** qui mesure l'outil |
| **Traçable** | chaque information extraite (année, lieu, dispositif…) est accompagnée du **passage du PDF** qui la justifie ; « non trouvé » plutôt qu'une valeur inventée |
| **Frugal** | ne pas faire lire tous les PDF par un gros modèle : **entonnoir en deux passes** (métadonnées, puis lecture courte des seuls candidats) ; coût mesuré par document |
| **Pas d'ontologie lourde** | recherche **sémantique** (embeddings) pour les synonymes ; un petit lexique métier facultatif (ex. fissurateur / décompacteur) seulement si la mesure montre qu'il manque |
| **Modulaire** | 6 modules reliés par des **formats d'échange simples** (JSON) : chacun peut être développé, testé et remplacé séparément |

---

## 2. Vue d'ensemble

```
 Sites de référence        RD Agri (MCP Lexicon)       Documents privés du formateur
 (adresse ajoutée)                │                     (essais non publiés, ancien support)
        │                         │                               │
        ▼                         ▼                               ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ M1 COLLECTE : connecteurs, liste des PDF, doublons  → documents.jsonl   │
 └─────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ M2 EXTRACTION : texte des PDF (premières pages d'abord), nettoyage       │
 └─────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ M3 QUALIFICATION : fiche par document (organisme, année, lieu, contexte, │
 │    type expé / retour d'expérience, dispositif) + preuves → fiches.jsonl │
 └─────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ M4 RECHERCHE : index hybride (mots + sens) + reranker + filtres          │
 └─────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ M5 SÉLECTION : entonnoir → ≈ 50 documents classés, justification courte, │
 │    diversité (sources, types, années)                                   │
 └─────────────────────────────────────────────────────────────────────────┘
        ▼
 ┌─────────────────────────────────────────────────────────────────────────┐
 │ M6 SORTIES : interface formateur, export (liste, PDF, tableau), API, MCP │
 └─────────────────────────────────────────────────────────────────────────┘
 Transverse : ÉVALUATION (jeu de référence métier), coûts, traces
```

---

## 3. Les modules

| Module | Rôle | Entrée → sortie | Points durs |
|---|---|---|---|
| **M1 Collecte** | ajouter une source par son adresse ; lister ses PDF ; brancher RD Agri via le MCP du Lexicon ; verser des documents privés | adresse ou connecteur → `documents.jsonl` (url, source, titre, date si connue, empreinte, licence) | plans de site incomplets ; respect des conditions des sites ; doublons entre sites |
| **M2 Extraction** | lire le texte des PDF, d'abord les 2 ou 3 premières pages | PDF → texte + pages | PDF scannés, tableaux, mises en page complexes |
| **M3 Qualification** | remplir la **fiche de qualification** de chaque document, avec preuve et niveau de confiance | texte → `fiches.jsonl` | qualité de l'extraction ; coût ; distinguer expérimentation et retour d'expérience |
| **M4 Recherche** | trouver les documents qui répondent à la demande du formateur, synonymes compris | demande → documents classés | vocabulaire métier ; documents longs |
| **M5 Sélection** | filtrer en entonnoir et produire ≈ 50 documents justifiés | documents + fiches + filtres → liste finale | équilibre pertinence / récence / diversité ; justification courte et vraie |
| **M6 Sorties** | interface formateur ; export vers NotebookLM ou autre ; API et MCP pour d'autres outils (ex. agent Duc) | liste → fichiers, écrans | rester indépendant de l'outil de génération |

---

## 4. La fiche de qualification (proposition, à valider par le métier)

```json
{
  "document_id": "rdagri-12345",
  "organisme": {"valeur": "Chambre d'agriculture Pays de la Loire", "preuve": "p.1 : « … »", "confiance": 0.9},
  "annee": {"valeur": 2019, "preuve": "p.1 : « Essai 2017-2019 »", "confiance": 0.8},
  "lieu": {"valeur": "Les Trinottières (49)", "preuve": "…", "confiance": 0.7},
  "contexte_pedoclimatique": {"valeur": "sol limono-argileux, été sec", "preuve": "…", "confiance": 0.5},
  "type": {"valeur": "experimentation", "choix": ["experimentation", "retour_experience", "synthese", "autre"]},
  "dispositif": {"modalites": 4, "repetitions": 3, "preuve": "…"},
  "themes": ["sorgho", "prairies", "sécheresse"],
  "chiffrage_economique": {"valeur": false},
  "alertes": ["résultats antérieurs aux canicules de 2022", "contexte éloigné de la région du formateur"]
}
```

- **Chaque champ a une preuve** (le passage du PDF) et un **niveau de confiance** ; un champ introuvable vaut `null`, jamais une valeur devinée.
- **Les alertes** reprennent les points de vigilance du kick-off : date, contexte, éloignement, absence de chiffrage, réglementation ancienne.
- **Les colonnes définitives viendront de « l'Excel »** de Janick et Lionel.

---

## 5. Frugalité : l'entonnoir en deux passes

| Passe | Ce qui est fait | Sur combien de documents | Coût |
|---|---|---|---|
| **0. Index** | titre, mots-clés, URL, métadonnées existantes ; vecteurs du titre et du début | tous (milliers) | très faible |
| **1. Tri** | recherche + filtres sur la demande du formateur | tous → quelques centaines | faible |
| **2. Lecture courte** | modèle léger sur les 2 ou 3 premières pages : fiche de qualification | quelques centaines → ≈ 50 | moyen, **mesuré** |
| **Cache** | une fiche calculée une fois est réutilisée par tous les formateurs | — | nul ensuite |

- À tester : l'outil de classification frugal présenté par Bertrand (réponses « vrai / faux », score, choix sur un extrait).
- On mesurera le **coût et le temps par document qualifié**, et on les comparera à une lecture par un gros modèle.

---

## 6. Évaluation : comment saura-t-on que ça marche ?

| Quoi | Comment | Qui fournit la référence |
|---|---|---|
| **Trouver** | 10 à 20 demandes réelles de formateurs (fil rouge sorgho) + documents attendus → part des bons documents dans les 50 proposés | métier, formateurs |
| **Qualifier** | 30 à 50 PDF qualifiés à la main avec l'Excel → exactitude de chaque champ extrait automatiquement | Janick, Lionel |
| **Comparer** | même demande avec Google `filetype:pdf`, le moteur de RD Agri, le chatbot RAG existant | équipe |
| **Coût** | temps et coût par document qualifié et par demande | équipe |

- Sans ce jeu de référence, on ne peut pas savoir si l'outil fait mieux que l'existant. **C'est la contribution la plus précieuse du métier.**

---

## 7. Réutilisation de l'existant

- **Lexicon et MCP RD Agri** (OSFARM) : point d'entrée de M1.
- **Agent Duc** : client possible des modules M4 et M5 via MCP.
- **Chatbot RAG RD Agri** : à étudier pour comprendre pourquoi ses réponses sont « bruitées ».
- **Aspirateur de PDF** de Martin Hollet : retour d'expérience pour M1.
- **TransfIA** (projet personnel open source, préparé avant le hackathon) : briques déjà écrites et testées pour la lecture des PDF, la recherche hybride avec reranker, l'évaluation avec jeu de référence, le serveur MCP et le changement de modèle par configuration (local ou cloud).

---

## 8. Ce que je propose de faire

- Je développe un **prototype complet de bout en bout** (M1 à M6), centré sur le fil rouge sorgho, pour avoir vite une démonstration et un banc de mesure.
- Les **formats d'échange** (`documents.jsonl`, `fiches.jsonl`) permettent à chacun de brancher ou de remplacer un module.
- Je prends volontiers en charge les modules que l'équipe me confiera, en priorité **M3 Qualification** et **l'évaluation**.

---

## 9. Questions ouvertes

1. Les **colonnes de « l'Excel »** : quand peut-on les avoir ?
2. **Des formateurs** pour écrire 10 à 20 demandes réelles et juger les résultats ?
3. **Documents privés** : quelle confidentialité ? Peuvent-ils passer par un modèle en ligne, ou seulement en local ?
4. **Licences et conditions d'usage** des sites à indexer (RD Agri est en CC BY-NC-SA).
5. **Hébergement** de la démonstration pour le test à Tech Élevage : quelle infrastructure ?
6. **Modèles disponibles** (API, crédits) pour l'équipe ?
