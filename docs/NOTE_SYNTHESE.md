# SourcIA — note de synthèse (Défi 1)

9 novembre 2026 · Corinne Bergès

## En bref

SourcIA tourne de bout en bout sur un PC sans GPU : de la demande d'un formateur (les 7 critères) jusqu'à un support de formation sourcé, contrôlé et rattaché au référentiel du diplôme.

- **Ce que fait SourcIA** : trouver 30 à 50 sources, les qualifier (organisme, année, lieu, type, dispositif, chiffrage), puis produire plan, points clés, QCM, fiche technique, synthèse, cas concret et script de podcast.
- **Garde-fou** : chaque phrase produite doit se retrouver dans sa source ; ce qui ne passe pas est retiré et listé, jamais caché.
- **État** : 14 étapes de test passées sur PC réel (dont vrais PDF et Gemini) ; 72 tests automatiques ; dossier d'architecture à jour.
- **Ce qu'on demande à l'équipe** : valider le découpage en sous-défis, fournir le jeu de référence métier, trancher l'hébergement de la démo.

## Les 7 critères du mail des organisateurs

Les 7 critères sont tous couverts : ils forment le formulaire de demande (`demande.yaml`, page web, serveur MCP), lu par tous les modules.

| # | Critère | Ce que fait SourcIA | Testé sur PC |
|---|---|---|---|
| 1 | Profil du demandeur | enseignant, formateur, conseiller, intervenant : préférences de sources (conseiller → expérimentations) et ton du support | oui |
| 2 | Type de formation | diplômante ou non ; présentiel, distanciel, oral, écrit ; durée : décide des sorties (déroulé en présentiel) et du référentiel | oui |
| 3 | Public cible | type d'apprenant, niveau (CAP → licence), expérience : contrôle du niveau (verbes de Bloom, lisibilité) | oui |
| 4 | Types de ressources | données, R&D, essais, témoignages, photos, vidéos : filtres et bonus ; photos et vidéos qualifiées sur leurs métadonnées | oui (sans vidéo réelle) |
| 5 | Forme du résultat | fiche technique, QCM (+ export Moodle), synthèse, cas concret, glossaire, script de podcast | oui |
| 6 | Précisions sur les sources | publique ou non, année de publication séparée de l'année des résultats, dispositif, organisme, lieu, alertes | oui, sur vrais PDF |
| 7 | Contenu personnel | notes et fichiers du formateur ; blocs personnels conservés si on régénère ; jamais envoyés à un modèle en ligne | oui |

En plus du mail : niveau validé avec les référentiels officiels de chlorofil.fr (CAPa, bac pro CGEA, BTSA ACS'Agri), avec validation par un enseignant.

## Les sous-défis proposés

Proposition : découper le Défi 1 en 6 sous-défis, un par groupe de modules ; chacun peut être pris par une personne ou un groupe, car les formats d'échange (demande, fiche, sélection, formation) sont fixés.

| Sous-défi | Objet | Modules | Livrable vérifiable |
|---|---|---|---|
| 1a. Structurer la demande | le formulaire des 7 critères | M0 | `demande.yaml` validé par le métier |
| 1b. Trouver | des milliers de documents → 30 à 50 sources | M1 collecte, M4 recherche, M5 sélection | rappel@50 sur les demandes de référence |
| 1c. Qualifier | la fiche de chaque document, avec preuves | M2 extraction, M3 qualification | exactitude par champ, taux de valeurs fausses |
| 1d. Rattacher au référentiel | diplôme, capacités, niveau | M8 | référentiels et rattachements validés par un enseignant |
| 1e. Produire | le support (NotebookLM ou SourcIA) | M6 exports, M7 formation | part de contenus retirés ; avis des formateurs |
| 1f. Évaluer | jeu de référence et comparaisons | Évaluation | tableau de résultats partagé |

1e reste ouvert : les équipes qui préfèrent NotebookLM partent des exports de M6 (.txt, .zip, .csv) ; SourcIA propose M7 à côté, pour comparer.

## Résultats des tests sur PC réel

Sur la même demande (conseiller, chefs d'entreprise, « cultures fourragères d'été en année sèche »), Gemini produit un support complet en 7 s, sans aucune information fausse après contrôle ; le modèle local donne un support juste mais en 6 à 15 min.

| | Local qwen2.5:3b (CPU) | Gemini 3.1 Flash-Lite |
|---|---|---|
| Durée d'une formation | 6 à 15 min | 7 à 18 s |
| Réponses illisibles du modèle | fréquentes au début (boucles), 0 après réglages | 0 |
| Contenu produit | 3 à 8 points clés, QCM souvent complétés sans modèle | 9 points clés, 4 QCM, fiche, synthèse, podcast |
| Retiré par les contrôles | 10 à 20, surtout des inventions | 9, surtout des phrases trop générales |
| Information fausse dans le support final | 0 après 6 itérations de règles | 0 |
| Documents privés | restent sur le PC | non envoyés (verrou vérifié) |
| Coût | 0 € | API payante à l'usage ; niveau gratuit utilisé pour les tests |

**Vrais PDF** (essais sorgho, guides, comptes rendus de chambres, d'instituts, de Suisse et de Belgique) :

- 1er essai : 5 adresses sur 6 trouvées par recherche web étaient périmées (404, 503, site injoignable).
- 2e essai : 6 PDF sur 6 téléchargés, qualifiés en 0,08 s par fiche avec les règles seules ; organisme trouvé 4 fois sur 6, puis aussi pour les sources suisses et les sites spécialisés après correctifs.
- Qualification par le modèle local : 0 valeur fausse, mais 200 s par document sur CPU.
- Classement : l'essai le plus pertinent (compte rendu 2021-2024) n'arrive que 3e ; les poids sont à calibrer avec le métier.

## Leçons des tests pour l'équipe

La leçon principale : un modèle, petit ou grand, invente ou enjolive ; c'est le contrôle dans le code, puis la relecture du formateur, qui rendent le support fiable.

- **Un petit modèle local suffit pour qualifier, pas pour rédiger vite.** Le 3B qualifie sans erreur mais rédige lentement et invente plus ; Gemini rédige bien, mais seulement sur des documents publics.
- **Le contrôle doit suivre le modèle.** Le 3B invente des chiffres et mélange les cultures ; Gemini reformule. Le premier contrôle mot à mot retirait 20 contenus justes de Gemini ; avec synonymes, contrôle du sens (avant / après, supérieur / inférieur) et chiffres exacts, on garde le juste et on refuse toujours l'inventé.
- **Les chiffres et les cultures sont les meilleurs témoins.** Un chiffre absent de la source, ou une culture absente du passage, signale presque toujours une invention.
- **Les adresses de PDF vieillissent vite.** Partir des pages vivantes des sites (exploration) plutôt que de listes d'adresses.
- **Les règles de qualification écrites sur des exemples français ratent l'étranger** (Suisse, Belgique) : pays déduit du domaine, organismes ajoutés.
- **Tout ce qui est retiré doit être visible.** L'annexe « retiré par les contrôles » et le fichier des échecs du modèle ont permis chaque correction.
- **Une fuite évitée** : le chemin d'un document privé apparaissait dans l'export CSV ; corrigé et testé.

## Questions en suspens et propositions

Chaque question a déjà une valeur par défaut codée (la plus probable), modifiable en un seul endroit : on peut avancer sans attendre, puis ajuster.

| Question | Proposition codée | À valider par |
|---|---|---|
| Colonnes de « l'Excel » de qualification | les 10 champs de la fiche SourcIA (organisme, année des résultats, année de publication, lieu, contexte, type, dispositif, chiffrage…) | Janick, Lionel |
| Valeurs possibles des 7 critères | listes fermées (profils, publics, niveaux, supports, sorties) | métier |
| Préférences par profil | conseiller → expérimentations ; enseignant → synthèses ; chefs d'entreprise → témoignages ; salariés, apprentis → guides | métier |
| Référentiels prioritaires | BTSA ACS'Agri (bloc C4 pour le fil rouge), bac pro CGEA, CAPa Métiers de l'agriculture, lus sur chlorofil.fr | enseignants |
| Seuils de niveau | verbes : CAP 1 à 3, bac pro 1 à 4, BTS 2 à 6 ; lisibilité minimale : CAP 60, bac pro 50, BTS 35 | enseignants, sur des supports réels |
| Modèle | local qwen2.5:3b par défaut (souverain, gratuit) ; Gemini par configuration, documents publics seulement | équipe |
| Hébergement de la démo | un serveur Python avec Ollama (aucune donnée ne sort), ou avec une clé Gemini | organisateurs |
| Photos et vidéos | qualifiées sur leurs métadonnées ; transcription locale facultative | métier : besoin réel ? |
| Podcast | script à deux voix ; audio par NotebookLM ou une voix de synthèse | métier |
| Connecteur RD Agri | import du catalogue en attendant la documentation du MCP | OSFARM |
| Nombre de sources | 30 par défaut, 50 au plus pour NotebookLM | formateurs |
| Dépôt du code | Forge OSFARM | organisateurs |

## Décisions attendues et prochaines étapes

Trois décisions débloquent la suite : le découpage en sous-défis, le jeu de référence métier, l'hébergement de la démo.

**À décider ensemble**

- [ ] Valider (ou modifier) les 6 sous-défis et qui prend quoi
- [ ] Obtenir du métier 5 à 10 demandes de référence avec les sources attendues : sert à calibrer le classement et à mesurer le gain
- [ ] Choisir l'hébergement de la démo : serveur Python avec Ollama, ou avec une clé Gemini
- [ ] Valider les colonnes de « l'Excel » de qualification (Janick, Lionel)

**Pistes pour qui reprend SourcIA**

- [ ] Calibrer les poids du classement avec le jeu de référence
- [ ] Tester l'exploration d'un site qui liste vraiment ses PDF
- [ ] Faire relire un support généré par un enseignant et un conseiller
- [ ] Option : contrôle sémantique local (NLI) en plus du contrôle par mots
- [ ] Copier le code sur la Forge OSFARM

Détails : dossier d'architecture (`docs/DOSSIER_ARCHITECTURE.md`) et journal des tests (`docs/JOURNAL_TESTS.md`) dans le dépôt.
