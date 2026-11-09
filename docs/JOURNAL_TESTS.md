# SourcIA : journal des tests

> Une ligne par essai : date, étape, configuration, résultat, problème, correction.
> Les étapes renvoient à [`PLAN_TESTS.md`](PLAN_TESTS.md).

---

## Version s1 : tests faits pendant le développement (conteneur Linux, sans modèle ni Internet)

| Étape | Résultat | Remarque |
|---|---|---|
| Tests automatiques | 26 réussis, 1 sauté | le test de l'API web est sauté : fastapi non installable dans le conteneur ; il tournera sur ton PC |
| Démonstration (`demo`, `config/test.yaml`) | 5 documents sélectionnés, essai 2023 en tête, porcherie exclue | embeddings « hashing » |
| Extraction d'un vrai PDF (lecture pypdf) | 3 pages, texte correct, fiche remplie | PDF généré à partir d'un exemple |
| `eval qualifier` (règles, exemples fictifs) | 0 valeur fausse | ⚠️ exemples écrits avec les mêmes formulations que les règles : ce n'est pas une mesure réelle |
| `eval trouver` (exemples fictifs) | rappel : titres 0,88 ; hybride 1,00 | 4 demandes seulement |

### Problèmes trouvés et corrigés pendant le développement

| Problème | Cause | Correction |
|---|---|---|
| Tous les documents remontaient, même la porcherie | la recherche par le sens classe **tout** le corpus | seuil `min_dense_sim`, à calibrer par modèle d'embeddings |
| Le modèle pouvait citer une vraie phrase (« essai 2016 ») et donner une autre année (2023) | on vérifiait que la preuve existe, pas qu'elle contient la valeur | **garde-fou n° 2** : un nombre doit figurer dans sa preuve (testé) |
| Preuves trop longues (plusieurs lignes collées) | découpage en phrases sans tenir compte des retours à la ligne | une ligne = au plus une phrase |
| Lieu sans majuscules ni accents (« Vendee ») | valeur prise dans le texte normalisé | on reprend le passage d'origine |
| `chiffrage_economique` compté faux alors qu'il était juste | comparaison Python enchaînée mal écrite | parenthèses |
| Alerte « contexte éloigné » parfois coupée | seules 3 alertes affichées, la région en dernier | la région passe en tête |
| Deux configurations avec des embeddings différents partageaient le même index | vecteurs de tailles différentes | un index par modèle d'embeddings |
| Chemin d'un document privé dans l'export Markdown | lien écrit pour tous les documents | pas de lien pour un document privé |

## Version s2 : ajout de M7 Formation (conteneur, modèle simulé)

| Étape | Résultat | Remarque |
|---|---|---|
| Tests automatiques | 33 réussis, 1 sauté (API web) | 7 nouveaux tests pour M7 |
| Modèle simulé qui recopie les sources + une invention par contenu | les 3 inventions retirées (point « 25 t MS/ha en Alaska », QCM « capitale du sorgho » à l’explication fausse, terme inventé) ; le reste gardé | listées en annexe B |
| Modèle qui ne répond que du texte invalide | plan de repli par thèmes ; « fiche non générée » écrit dans le support | l'échec est dit, pas caché |
| Modèle en ligne + document privé | le document privé n'est jamais envoyé ; son nom est dans le support (🔒) | testé |

### Problèmes trouvés et corrigés (s2)

| Problème | Cause | Correction |
|---|---|---|
| La mention « EXEMPLE FICTIF » des exemples devenait un point clé et une question | elle était en première ligne de chaque document | mention déplacée en fin de document |
| Même point clé dans deux séquences, même terme trois fois dans le glossaire | aucun contrôle de doublon | doublons retirés |
| « 0 appel au modèle » affiché alors que le modèle avait été appelé | les appels échoués n'étaient pas comptés | comptés |
| Durées du plan de repli : 88 min au lieu de 90 | division entière | le reste va à la dernière séquence |

## Version s3 : demande structurée, référentiels, ressources, nouvelles sorties (conteneur, modèle simulé)

| Étape | Résultat | Remarque |
|---|---|---|
| Tests automatiques | 46 réussis, 1 sauté (API web : fastapi non installable ici) | 47 au total ; sur ton PC, 47 attendus |
| API : chaque route appelée dans le conteneur (via Starlette) | sélection, export, fiche, formation, validation des rattachements : OK ; chemin « ../../ » bloqué | |
| Page web pilotée dans un navigateur (Playwright) | formulaire des 7 critères, diplôme BTSA, C4.2 + C4.3, sélection, formation, validation par « Mme Test » : aucune erreur JavaScript | |
| Extraction des capacités sur tes **vrais** PDF | CAPa MA 2024 : 28 capacités ; bac pro CGEA 2024 : 35 ; BTSA ACS'Agri 2025 : 21 (C4 à C8) | coupures de mots de pypdf (« équil ibre ») : PyMuPDF sur ton PC devrait faire mieux |
| Demande diplômante simulée | plan rattaché ; code inexistant (C9.9) retiré ; capacité non couverte (C4.4) ajoutée ; « Citer » signalé trop bas pour un BTS | |
| Contenu personnel | notes ajoutées comme document privé ; bloc personnel conservé à la régénération ; jamais envoyé au modèle en ligne | |
| Sorties : fiche technique, synthèse, podcast | chaque invention du modèle simulé retirée (« semer le 1er janvier », « double le revenu », « guérit en 3 jours ») | |

### Problèmes trouvés et corrigés (s3)

| Problème | Cause | Correction |
|---|---|---|
| « Publié en 2021 » pris pour l'année des résultats | le mot « en » suivi d'une année comptait comme un essai | les mentions de publication sont retirées avant de chercher l'année des résultats |
| Libellés de capacités suivis de bruit (« L'examen comporte 7 é… », « Candidats en ») | fin de libellé mal détectée | arrêt sur les mots de début de tableau (Liste, Candidats, Épreuve…) |
| BTSA : capacité « C2 » fantôme | renvoi à C2.2 dans un module | retirée ; C1 à C3 à compléter avec le référentiel de diplôme |
| Alerte « contexte éloigné de Pays de la Loire » pour un essai dans le Maine-et-Loire | le lieu ne citait pas la région | table régions-départements (nom ou numéro) |
| CSV enregistré par Excel illisible | Excel en français enregistre en Windows-1252 | lecture UTF-8, sinon Windows-1252 |
| Nature « texte » affichée pour chaque exemple | étiquette affichée pour toutes les natures | seulement données, photo, vidéo, audio |

### Diagnostic de l'étape 8 (formation diplômante avec qwen2.5:3b, 09/11)

| Constat | Cause | Correction (s3.3) |
|---|---|---|
| Points vrais retirés (« l'implantation après le 15 mai… sécurise le stock fourrager ») | le modèle écrit la citation DANS la phrase : « (Sorgho fourrager… essai 2023, [3]) » ; le « 3 » et le « 2023 » faisaient échouer la règle « chiffre à l'identique », les mots du titre diluaient la comparaison | citations retirées du texte avant contrôle (la source est gardée à part) |
| Points vrais retirés car le modèle cite le mauvais numéro de passage | petit modèle | si le passage cité ne convient pas, on cherche le passage qui soutient la phrase parmi ceux fournis (« source corrigée », signalé) |
| QCM tous retirés (« explication non retrouvée ») | mêmes causes | mêmes corrections pour les explications |
| « Le sorgho a été testé en Bretagne en 2016 » (c'étaient des méteils) | mélange de deux sources | **nouveau contrôle** : une culture ou un animal cité dans la phrase doit être dans le passage ; toujours retiré ✅ |
| « Le passage [2] montre que… » | le modèle décrit le passage au lieu d'en donner l'information | écarté comme « méta » |
| **« À retenir » non contrôlé** : contenait « testé en Bretagne en 2016 » | oubli de contrôle | chaque phrase du « à retenir » (et de la conclusion de synthèse) doit être soutenue, sinon retirée |
| Codes de capacité dans les mots-clés au lieu du champ prévu → 2 séquences ajoutées, 4 au lieu de 2, durée 240 au lieu de 180 min | petit modèle | code déduit des mots-clés ou du libellé le plus proche ; consigne avec exemple ; durées ramenées à la durée demandée ; titres « C4.2 : … » pour les séquences ajoutées |
| Glossaire et un QCM non générés (JSON invalide) | réponse coupée | plus de place pour la réponse (QCM 1 800, glossaire 1 200 jetons) |
| Limite restante | contrôle par les mots : « maximiser son rendement » passe alors que la source ne le dit pas | relecture humaine ; évolution : modèle d'inférence (NLI) local |

### Étape 8 bis (s3.3, 09/11) : 10 points clés gardés, mais encore des défauts

| Constat | Cause | Correction (s3.4) |
|---|---|---|
| 10 points clés gardés (1 avant) ; 6 justes et précis, mais 3 phrases vagues passent : « le choix du sorgho est influencé par les résultats d'essais précédents » | les mots du **sujet** (sorgho, fourrager, sécheresse…) sont partout : ils suffisaient à atteindre le seuil | les mots du sujet ne comptent plus dans le contrôle ; rejoué sur tes points : les 4 phrases vagues ou fausses retirées, 1 paraphrase juste perdue (« caractéristiques du sol et de l'année ») |
| « Le mélange triticale-pois-vesce a donné 8,2 t MS/ha (méteils 2016) », **vrai**, retiré | le mot « méteil » est dans le titre du document, pas dans le passage de la page 2 ; et ce passage n'était pas parmi les 6 fournis pour la séquence | le titre du document compte dans le contrôle ; si le passage n'est pas parmi ceux de la séquence, on cherche dans tout le mini-corpus |
| **0 QCM** : 2 fois JSON invalide, 4 questions vagues (« Quel est le critère de sélection… ») | le petit modèle écrit mal le format (« [3] » au lieu de 3, « B » au lieu de 1 ?) et pose des questions sans réponse dans les sources | format tolérant (« [3] », « B ») ; **repli sans modèle** : QCM construits à partir des points clés vérifiés (une valeur chiffrée ou une culture masquée, distracteurs tirés des sources) ; réponses invalides enregistrées dans `echecs_modele.json` pour diagnostic |
| Glossaire non généré (JSON invalide) | idem | format tolérant ; 3 à 6 termes au lieu de 5 à 10 |
| Cas concret : « région de l'Est », « 50 vaches de vache de croisière » | texte fictif non contrôlable | consigne : exploitation dans la région du formateur, 3 phrases simples et cohérentes ; reste à relire |
| 44 min (15 appels) | nouvelles tentatives après chaque JSON invalide (2 à 3 min chacune) | une seule nouvelle tentative pour le QCM et le glossaire (le repli prend le relais) |

### Pourquoi le QCM et le glossaire du modèle échouaient (`echecs_modele.json`, 09/11)

| Constat dans les réponses du 3B | Conséquence | Correction (s3.5) |
|---|---|---|
| **Boucle** : « Elle est également appelée sorgho fourrager en conditions sèches… » répété jusqu'à la limite de longueur | JSON coupé au milieu → invalide → glossaire perdu | longueurs maximales dans le schéma (Ollama les impose pendant la génération) ; texte trop long coupé à la dernière phrase plutôt que rejeté ; pénalité de répétition (`repeat_penalty` 1,15) |
| Explications de 10 lignes qui recopient tous les passages | idem | explication : UNE phrase de 30 mots au plus |
| Propositions de QCM avec de longues parenthèses | idem | propositions de 10 mots au plus, sans parenthèses |
| **Chiffres inventés** : « 9,2 t MS/ha (variété A) », « maïs témoin 6,5 t MS/ha » (la source dit 9,5 et 7,8) | ces questions auraient été retirées par le contrôle « chiffre à l'identique » | consigne « n'invente aucun chiffre » ; le contrôle reste le vrai garde-fou |
| Connaissance générale hors sources : « le sorgho est plus résistant aux maladies » | aurait été retiré (absent des sources) | — (le contrôle fait son travail) |

### Étape 8 quater (s3.5, 09/11, 21 h 31) : plus d'échec de format, mais la qualité du 3B limite

Résultat : 9 appels, 7,5 min ; plus aucune réponse illisible (les longueurs bornées marchent) ; 8 points clés, 6 QCM (dont 4 écrits par le modèle), 1 terme.

| Défaut constaté | Exemple réel | Correction (s3.6) |
|---|---|---|
| **QCM faux qui passait** | « Date limite d'implantation du **méteil** ? » réponse « **Juin** », expliquée par « implantation [du sorgho] après le 15 mai » | une culture citée dans la question doit être dans le passage qui la justifie ; la bonne réponse doit apparaître dans l'explication, sinon la question est retirée |
| Propositions mal formées | « {A) Semis direct} », « B) Le maïs » | nettoyage des accolades et des lettres |
| Consigne recopiée dans l'explication | « … L'explication est UNE phrase reprise du passage cité. N' » | phrases qui recopient la consigne supprimées |
| Restes de citations | « Ce résultat est mentionné dans. », « Ce point est basé sur et. » | phrases qui finissent par « dans », « sur », « et »… supprimées |
| Enjolivements gardés | « … a été essentiel pour maintenir les vaches en état », « … solution de repli » | seuil relevé de 0,50 à **0,65** (mesuré sur 14 phrases réelles : 4 enjolivements retirés, 1 phrase vague juste perdue) ; **chaque phrase** d'un point doit être soutenue (une 2e phrase inventée fait tomber le point) |
| Aveu du modèle gardé | « … inférieur à celui du maïs (non précisé dans le passage) » | phrases avec « non précisé », « non mentionné », « supposé » retirées |
| Glossaire presque vide (1 terme) | les définitions sont de la connaissance générale, absente des passages | le terme doit être dans les sources ; une définition non sourcée est gardée **marquée « proposée, à vérifier »**, avec la phrase des sources où le terme apparaît ; jamais de chiffre non sourcé |
| Questions du cas concret avec « [2] », « [5] » | « 1. [2] Quels sont les avantages… » | citations retirées |
| Limite qui reste | « … a permis de maximiser son rendement » (0,67) | relecture humaine ; évolution : vérification par inférence (NLI) ou modèle plus grand (Gemini) pour les documents publics |

### Étape 10 (09/11, 21 h 50) : agriculteurs à distance

| Constat | Cause | Correction (s3.7) |
|---|---|---|
| Fiche technique : « semer vers le 20 mai **(n°5)** » (vrai, notes personnelles) retiré | citation écrite « (n°5) » : le « 5 » faisait échouer la règle des chiffres | formats « (n°5) », « n°5 », « [n] », « (passage 3) » retirés avant contrôle |
| Synthèse : « Une étude sur les méteils **a montré que** le mélange triticale-pois-vesce… » (vrai) retiré | le cadre « une étude a montré que » ajoutait des mots absents de la source | on contrôle l'**affirmation**, sans le cadre (« selon X », « le témoignage a montré que ») ; rejoué : ce paragraphe et celui des notes personnelles sont gardés |
| Podcast : « Selon, il a permis… », « [n] - Le sorgho… » | citations mal écrites | « Selon, » et « [n] - » retirés |
| Toujours retirés, à juste titre | « le **maïs témoin** a montré 8,2 t MS/ha avec triticale-pois-vesce » (mélange de deux essais), « le trèfle violet maintient une production **élevée** » (la source dit 45 %) | — |
| Retirés à tort (limite du contrôle par les mots) | « semer » ≠ « semis » ; « solution efficace » ≠ « m'a sauvé l'été » | — relecture ; évolution : contrôle par le sens |
| QCM : « Sorgho (50 %)}, {B) Triticale (40 %)}, {C)… » | le modèle met les 4 propositions dans une seule | proposition de plus de 12 mots ou contenant « B) » → question retirée |
| 1 séquence de 20 min pour une formation de 90 min | durées ramenées à la durée demandée seulement pour les formations diplômantes | toujours ramenées (90 min) |
| Titre « Séquence 1 : … » | le modèle a titré le plan comme une séquence | titre = le sujet |
| Notes personnelles marquées « PDF scanné » | une note courte (< 200 caractères) était prise pour un scan | « scanné » seulement pour un PDF |
| Pas de `podcast_script.md`, sans explication | toutes les répliques de l'expert retirées → pas de podcast | remarque dans le support : « podcast demandé mais non produit : tout a été retiré par les contrôles (annexe B) » |

### Étape 12 (09/11, 23 h 18) : six vrais PDF

| Constat | Cause | Correction (s3.10) |
|---|---|---|
| Saône-et-Loire → Auvergne-Rhône-Alpes | le département « Loire » trouvé dans « Saône-et-Loire » ; ponctuation collée aux noms | noms les plus longs d'abord ; ponctuation ignorée |
| Pays étrangers sans alerte (Suisse, Wallonie) | table limitée à la France | pays reconnus : « contexte éloigné (essai en Suisse) » |
| Guide « conduite technique en 2025 » avec « résultats 2025 » | « en 2025 » pris pour une année d'essai | pour un guide ou une synthèse, l'année sans mot d'essai devient l'année de publication |
| CR d'essais 2021-2024 « publié en 2021 » | une mention « 2021 » prise pour la publication | une publication antérieure aux résultats est écartée |
| Type non trouvé pour « Synthese Sorgho Fourrager » | le titre n'était pas lu par les règles | le titre compte (triple) ; vocabulaire des guides élargi (« conduite technique », « préconisation »…) |
| Organisme = « web-reel » | le nom donné à la source servait de repli | repli sur le **site** : geves.fr → GEVES, prometerre.ch → Prométerre, *.chambres-agriculture.fr → « Chambre d'agriculture (saoneetloire) » ; organismes ajoutés (GEVES, Sorghum ID, Agroscope, CRA-W…) |
| « Chambre d'agriculture » sans territoire | nom canonique seul | « Chambre d'agriculture de Saône-et-Loire » quand le territoire suit |
| Ordre : le CR d'essais 2021-2024 seulement 3e, derrière un document de règles d'inscription GEVES | pertinence par le rang ; poids 0,6 / 0,2 / 0,2 non calibrés | **à calibrer avec le jeu de référence du métier** (`sourcia eval trouver`) |
| Page Bretagne : 0 PDF trouvé en 5 pages | la page de publication ne propose peut-être pas de PDF (ou le lien est créé par JavaScript) | à vérifier à la main ; leçon : tester `add-site` sur une page qui liste des PDF |

---

## Tests sur ton PC

| Date | Étape | Configuration | Résultat | Problème | Correction |
|---|---|---|---|---|---|
| 09/11 | 0 Installation | rapide | OK : tous les modules présents, Ollama et qwen2.5:1.5b joignables | avertissement « fitz est obsolète » | import `pymupdf` (s3.1) |
| 09/11 | 1 Tests | — | 47 réussis en 5,6 s (dont l'API web) | — | — |
| 09/11 | 2 Démo | rapide | essai 2023 en tête, porcherie absente, alertes 2016 et glyphosate justes | le guide technique affichait « résultats 2022 » (c'est l'année de publication) | l'année accolée au genre du document (« Guide technique 2022 », « Fiche témoignage 2024 », « Synthèse 2019 ») devient l'année de publication (s3.1) |
| 09/11 | 3 Fiches | rapide | preuves justes, « — » quand l'information manque, témoignage bien `retour_experience` | témoignage : « 2024 » pris pour l'année des résultats ; synthèse : « en » trouvé dans « références » | même correction ; recherche des mots d'essai en mots entiers (s3.1) |
| 09/11 | 4 Référentiels | rapide | 3 référentiels listés ; BTSA C4 à C8 corrects ; **téléchargement direct depuis chlorofil.fr réussi**, fichier identique à celui extrait (empreinte) | guide technique : alerte « année des résultats non trouvée » inutile (un guide n'a pas de résultats d'essai) | alerte supprimée pour guides et synthèses datés (s3.2) |
| 09/11 | 5 Demande structurée | rapide | méteil : « contexte éloigné (essai en Bretagne) » ; sorgho (Maine-et-Loire) et témoignage (Vendée) sans alerte : justes | luzerne (Chambre d'agriculture de **Normandie**) sans alerte : le lieu (« ferme de la Haute Lande ») ne dit pas la région | si le lieu ne donne pas la région, on prend celle de l'organisme (s3.2) |
| 09/11 | 6 Recherche e5 | local | « fissurateur » non testé ; bons documents trouvés | avec e5, toutes les similarités sont serrées (0,80 à 0,92) : la porcherie (0,877) dépasse le méteil (0,873) → **aucun seuil absolu ne sépare** | règle relative : un document trouvé par le sens SEUL est gardé s'il est à moins de 0,03 du meilleur ; simulé sur tes valeurs : porcherie écartée pour le sorgho, seule gardée pour « ventilation » (s3.2) |
| 09/11 | 6 bis Recherche e5 (s3.2) | local | « sorgho » : 5 documents utiles, porcherie écartée ; « ventilation » : porcherie seule | — | — |
| 09/11 | 7 Passe modèle | local (qwen2.5:3b) | règles seules et règles + modèle : 0 valeur fausse, exactitude 1,00 sur les 4 documents de référence ; le modèle **améliore** les valeurs (organisme complet « Chambre d'agriculture des Pays de la Loire », lieu avec le département, contexte pédoclimatique rempli) et l'accord règles + modèle monte la confiance (0,90) | **coût : 200 s par document** sur le processeur ; exemples trop simples pour départager règles et modèle ; affichage « 0,00 » pour des champs absents de la référence | entonnoir confirmé : modèle seulement sur les N premiers candidats (`--llm-top`) ; affichage « — » (s3.3) |
| 09/11 | 8 Formation diplômante | local (qwen2.5:3b) | 16 appels, 31 min ; plan fait par le modèle ; C4.2 et C4.3 couvertes ; alerte de niveau juste (« définir » trop bas pour un BTS) ; cas concret correct et chiffré | **1 point clé gardé sur 21, 0 QCM, 0 terme** ; diagnostic dans le tableau ci-dessous | s3.3 : rejoué sur tes 20 points retirés → 13 gardés (vrais), 3 mélanges de sources toujours retirés, 5 phrases « Le passage [n] montre… » écartées ; 1 faux positif restant (« maximiser son rendement ») |
| 09/11 | 8 bis Formation diplômante (s3.3) | local (qwen2.5:3b) | 15 appels, 44 min ; 10 points clés (6 justes et précis) ; cas concret chiffré juste ; C4.2 déduite des mots-clés, C4.3 ajoutée ; durées = 180 min | 3 points vagues ; 0 QCM ; 0 terme ; voir le tableau « Étape 8 bis » | s3.4 |
| 09/11 | 8 ter Formation diplômante (s3.4) | local (qwen2.5:3b) | 12 appels, **6 min** (réponses déjà en cache pour le plan et une partie des séquences) ; **8 points clés justes, 6 QCM justes** (construits sans modèle), cas concret cohérent en Pays de la Loire, tous chiffres exacts | un point « Le document fictif… indique que… » ; « à retenir » énumératif encore gardé ; 3 QCM trop faciles (« Le …… fourrager » → sorgho, le sujet) ; glossaire et QCM du modèle toujours en échec | s3.5 : phrases « Le document… indique » écartées ; seuil plus strict pour le « à retenir » ; pas de QCM sur une culture du sujet ; échecs du modèle à analyser (`echecs_modele.json`) |
| 09/11 | 8 quater Formation (s3.5) | local (qwen2.5:3b) | 9 appels, 7,5 min ; **0 réponse illisible** ; 8 points, 6 QCM (4 du modèle), 1 terme | 1 QCM faux (méteil / juin), restes de citations, enjolivements ; voir le tableau « Étape 8 quater » | s3.6 |
| 09/11 | 9 Validation, contenu personnel | local | rattachements validés dans le CSV (oui, non, oui) → « Validés : 2 · refusés : 1 » ; tableau du support à jour (✅ validé / ❌ refusé) ; **phrase personnelle conservée** après régénération | consigne du support : « sourcia formation valider » au lieu de « sourcia valider-formation » | texte corrigé (s3.7) |
| 09/11 | 10 Formation non diplômante | local (qwen2.5:3b) | 6 appels, 6,6 min ; sources publiques seulement (ancien support privé exclu ✅) ; **notes personnelles citées** (S5 🔒) ; pas de déroulé (distanciel écrit ✅) ; 6 points clés justes (luzerne 70 % / trèfle 45 %, triticale-pois-vesce, 3 exploitations depuis 2022…) | **fiche technique, synthèse et podcast vides** ; 1 seule séquence de 20 min pour 90 min ; 2 QCM mal formés (4 propositions dans une) ; notes marquées « PDF scanné » ; pas de `podcast_script.md` sans explication | voir le tableau « Étape 10 » (s3.7) |
| 09/11 | 11 Page web | local (qwen2.5:3b) | parcours complet : formulaire, sélection, fiche et preuves, formation (11 appels, 14,6 min), exports ; « interface sobre, mais c'est bien » ; QCM tous justes (9,5 t MS/ha, 0,78 UFL, 12 °C) ; glossaire : définitions non sourcées bien marquées « à vérifier » (dont une fausse : « multicoupe = plusieurs épis ») | objectifs « Comparer … » (le 3B a recopié l'exemple de la consigne) ; séquence 1 vide sans explication ; questions retirées en double dans l'annexe B ; **chemin du document privé dans le CSV exporté** | exemple réaliste dans la consigne et objectif incomplet remplacé par le titre ; remarque « aucun point clé retenu » ; doublons supprimés ; plus aucun chemin privé dans les exports (s3.8) |
| 09/11 | 12 Vrais documents (1er essai) | reel (e5, règles) | 6 adresses de PDF trouvées par recherche web : **1 seule téléchargée** (3 × HTTP 404, 1 × HTTP 503, 1 × site injoignable) ; le PDF arrivé (Wallonie) : type, année, contexte trouvés ; **organisme, lieu, répétitions non trouvés ; titre vide** | les adresses trouvées par un moteur de recherche sont souvent **périmées** (sites des chambres en migration : « old- », « refonte- ») ; règles écrites sur des exemples français ; le programme ne disait pas pourquoi un téléchargement échouait | raison de chaque échec affichée, message court ; titre tiré du nom du fichier ; leçon pour l'équipe : partir des **pages vivantes** des sites (add-site) plutôt que de listes d'adresses (s3.9) |
| 09/11 | 12 bis Vrais documents (adresses récentes) | reel (e5, règles) | **6/6 PDF téléchargés**, 70 passages, 0,08 s par fiche ; organisme trouvé 4 fois sur 6 (INRAE, Idele, chambre), lieu « Ferme expérimentale de Jalogny et Lycée de Fontaines » juste ; alerte « résultats 2020 » juste | **Saône-et-Loire classée en Auvergne-Rhône-Alpes** (« Loire » trouvé dans « Saône-et-Loire ») ; guide 2025 avec « résultats 2025 » ; CR 2021-2024 « publié en 2021 » ; 3 types non trouvés (dont « Synthèse » dans le titre) ; organisme = « web-reel » (nom de la source) ; documents suisses sans alerte ; l'essai 2021-2024 n'est que 3e (les poids du score sont à calibrer) ; exploration de la page Bretagne : 0 PDF (la page n'en propose peut-être pas) | voir le tableau « Étape 12 » (s3.10) |
| 09/11 | 12 ter Vrais documents (s3.10) | reel | Saône-et-Loire → Bourgogne-Franche-Comté ✅ ; organismes : Sorghum ID, GEVES, Chambre d'agriculture de Saône-et-Loire, Prométerre ✅ ; guide 2025 « publié en 2025 · guide technique » ✅ ; synthèse reconnue ✅ | document suisse sans alerte (ni lieu ni pays dans le texte) ; synthèse Sorghum ID sans année (adresse « …/2017/10/… ») classée 1re ; titres = noms de fichiers (« 1608792721 20rap01p… ») | pays déduit du domaine (.ch, .be) ; année tirée de l'adresse en dernier recours (indice faible) ; titre = 1re ligne parlante du document quand le PDF n'a pas de titre (s3.11) |
| 09/11 | 13 Gemini (s3.11) | gcp (gemini-3.1-flash-lite) | **68 s, 4 appels** (contre 6 à 15 min en local) ; verrou « 1 privés exclus » ✅ ; capacités C4.2, C4.3 au bon endroit ✅ ; 5 points clés justes ; cas concret juste ; 3 QCM de repli | **QCM du modèle ×2 et glossaire : « Exception »** sans détail ; messages LiteLLM « Give Feedback / Get Help » | schéma rendu portable (sans longueurs ni motifs, Pydantic les vérifie après) ; si le fournisseur refuse quand même le schéma : 2e essai en JSON simple, schéma dans la consigne ; toute erreur du fournisseur notée dans `echecs_modele.json` avec son message ; seuil du contrôle réglable (`formation_threshold`, 0,6 pour Gemini) ; messages LiteLLM coupés (s3.12) |
| 09/11 | 13 bis Gemini (s3.12) | gcp | **18 s, 8 appels, aucun échec du modèle** (le correctif de schéma marche) ; 4 QCM du modèle, tous justes ; fiche technique et synthèse produites ; 3 points clés justes | **20 contenus retirés, dont beaucoup JUSTES** : Gemini reformule (« sécheresse estivale », « conserve », « doit être réalisée ») et le contrôle mot à mot les refuse ; QCM chiffrés retirés (« 70 % » ignoré) ; même question en S1 et S2 ; objectif terminé par « ,. » ; « Conclusion : » vide ; podcast entièrement retiré | contrôle : synonymes et abréviations (sécheresse = sec, t MS/ha = tonnes de matière sèche par hectare), mots de style ignorés, phrase « ancrée » (chiffres et cultures retrouvés) un peu plus tolérée ; **nouveau contrôle du sens** (avant / après, supérieur / inférieur, hausse / baisse doivent être dans la source) ; chiffres comptés dans les propositions de QCM ; doublons entre séquences ; ponctuation nettoyée ; conclusion vide masquée (s3.13) |
| 09/11 | 13 ter Gemini (s3.13) | gcp | **7,4 s, 8 appels, aucun échec** ; 9 points clés, 4 QCM, fiche technique, synthèse (5 paragraphes), podcast (7 répliques) ; 9 retraits au lieu de 20 ; **relecture : 0 information fausse** dans le support (chaque chiffre et chaque date vérifiés dans les sources) | 2 points de S1 redits en S2 avec d'autres mots ; 3 QCM « quelle culture fait le mieux » retirés comme ambigus (l'explication cite les deux chiffres) ; distracteur discutable « Il demande moins d'eau » (vrai en général) ; QCM « réserve utile 90 mm » juste mais peu utile ; séquence 2 (ensilage, méteils) peu couverte : le mini-corpus n'en parle presque pas | reformulations en double repérées d'une séquence à l'autre (s3.14) ; le reste : relecture du formateur (c'est son rôle) |
