# SourcIA : installation et plan de tests pas à pas

> On avance **bout par bout** : chaque étape a ses commandes, ce qu'on doit voir, et des cases à cocher.
> Après chaque étape, colle la sortie dans la conversation : on corrige avant de passer à la suivante.
> Les résultats vont dans [`JOURNAL_TESTS.md`](JOURNAL_TESTS.md).

Toutes les commandes se tapent dans **PowerShell**.

---

## Étape 0 : installation (15 min, une seule fois)

Prérequis déjà présents sur ton PC (installés pour TransfIA) : Python, Ollama. SourcIA a son **propre** environnement : TransfIA n'est pas touché.

```powershell
cd C:\dev
Expand-Archive -Path "$env:USERPROFILE\Downloads\sourcia-s3.zip" -DestinationPath C:\dev -Force
cd C:\dev\sourcia
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[recommended]"
sourcia -c config/rapide.yaml doctor
```

- Si `Activate.ps1` est refusé : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` puis relancer l'activation.
- Chaque nouvelle fenêtre PowerShell : `cd C:\dev\sourcia` puis `.\.venv\Scripts\Activate.ps1` (le début de ligne affiche `(.venv)`).

**On doit voir** : `SourcIA s3`, des ✅ pour pypdf, fitz, fastapi, mcp, sentence_transformers ; Ollama joignable.

- [ ] installation sans erreur
- [ ] `doctor` lisible

## Étape 1 : tests automatiques (2 min)

```powershell
pytest
```

**On doit voir** : `47 passed` (aucun réseau, aucun modèle : modèle simulé).

- [ ] tous les tests passent

## Étape 2 : démonstration sans modèle (1 min)

```powershell
sourcia -c config/rapide.yaml demo
```

**On doit voir** : 8 documents **fictifs**, 8 fiches, une sélection pour « sorgho fourrager en conditions sèches » : l'essai 2023 en premier, la porcherie absente.

- [ ] l'ordre te paraît logique pour un formateur
- [ ] les alertes (2016, glyphosate, pas de chiffrage) sont justes

## Étape 3 : M3, une fiche et ses preuves

```powershell
sourcia -c config/rapide.yaml fiche essai_sorgho
sourcia -c config/rapide.yaml fiche temoignage
```

**À vérifier** : chaque valeur est suivie de sa phrase de preuve (↳) ; « — » quand l'information manque ; année des **résultats** et année de **publication** séparées ; le témoignage est bien `retour_experience`.

- [ ] preuves justes, rien d'inventé

## Étape 4 : M8, les référentiels

```powershell
sourcia -c config/rapide.yaml referentiel liste
sourcia -c config/rapide.yaml referentiel voir btsa-acsagri
sourcia -c config/rapide.yaml referentiel voir capa-ma
```

**À vérifier** : les capacités ressemblent à celles des PDF (codes, libellés) ; CAPa : les variantes selon le support.
Puis, sur ton PC (accès à Internet), le **téléchargement direct** depuis chlorofil.fr :

```powershell
sourcia -c config/rapide.yaml referentiel verifier bacpro-cgea
```

- [ ] libellés corrects (sinon noter lesquels)
- [ ] téléchargement depuis chlorofil.fr : inchangés / nouveaux / injoignables

## Étape 5 : M0 et M5, une demande structurée

```powershell
sourcia -c config/rapide.yaml select --demande-fichier config/demandes/btsa_sorgho_c4.yaml --export json,csv,txt
```

**À vérifier** : alerte « contexte éloigné de Pays de la Loire (essai en Bretagne) » pour le méteil, **pas** pour la Vendée ni le Maine-et-Loire ; le `.txt` ne contient pas l'ancien support privé.

- [ ] filtres et alertes justes

## Étape 6 : M4, recherche avec le vrai modèle d'embeddings (e5)

```powershell
sourcia -c config/local.yaml demo
sourcia -c config/local.yaml search "sorgho fourrager en conditions sèches" -k 8
sourcia -c config/local.yaml search "ventilation des bâtiments" -k 8
```

**À vérifier** : la porcherie n'apparaît plus pour le sorgho, et elle est seule (ou presque) pour « ventilation ». Règle utilisée : un document trouvé **par le sens seul** (pas de mot commun) n'est gardé que s'il est à moins de `dense_only_margin` (0,03) du meilleur ; avec e5, un seuil absolu ne marche pas (toutes les similarités entre 0,80 et 0,92).

- [ ] hors-sujet écartés

## Étape 7 : M3, passe « modèle » (Ollama, qwen2.5:3b)

```powershell
ollama list
sourcia -c config/local.yaml eval qualifier
sourcia -c config/local.yaml eval qualifier --llm
```

**À regarder** : la colonne **FAUSSES** (doit rester à 0) ; le temps par document.

- [ ] valeurs fausses : 0 ?
- [ ] temps par document noté

## Étape 8 : M7, formation diplômante (≈ 15 à 25 min)

```powershell
sourcia -c config/local.yaml formation --demande-fichier config/demandes/btsa_sorgho_c4.yaml --sequences 2 --quiz 2
```

Les fichiers sont dans `data\formations\formation-<date>\`. Ouvre `support_formateur.md` (VS Code, ou le Bloc-notes) :

- **Rattachement au référentiel** : chaque séquence a sa capacité (C4.2, C4.3) ; couverture ✅ ;
- **Contrôle du niveau** : verbes des objectifs et lisibilité ;
- points clés avec « (S1, p. 2) » : vérifier 3 points au hasard dans le document ;
- QCM : une seule bonne réponse, explication juste ;
- annexe A (sources et alertes), annexe B (ce qui a été retiré : était-ce bien faux ?).

- [ ] durée, appels au modèle, contenus gardés / retirés notés
- [ ] aucune information fausse dans ce qui est gardé

## Étape 9 : M8, validation par l'enseignant et contenu personnel

1. Ouvre `rattachements.csv` dans Excel, mets `oui` dans la colonne « valide », enregistre (format CSV).
2. Ajoute une phrase dans un bloc `<!-- PERSONNEL:seq-1 -->` du support, enregistre.

```powershell
sourcia -c config/local.yaml valider-formation data\formations\formation-<date> --par "Corinne"
```

**On doit voir** : « Validés : 2 » ; dans le support, statut « ✅ validé » ; **ta phrase est toujours là**.

- [ ] validation enregistrée, bloc personnel conservé

## Étape 10 : M7, non diplômante, distanciel, fiche technique et podcast

```powershell
sourcia -c config/local.yaml formation --demande-fichier config/demandes/agriculteurs_secheresse.yaml --sequences 2 --quiz 2
```

**À vérifier** : fiche technique, synthèse, `podcast_script.md` ; les notes du groupe d'éleveurs (contenu personnel) citées comme « personnel ».

- [ ] sorties présentes et sourcées

## Étape 11 : page web

```powershell
sourcia -c config/local.yaml serve
```

Ouvrir http://127.0.0.1:8000 : remplir la demande (diplômante, BTSA, C4.2), « Trouver les sources », déplier une fiche, « Créer la formation », valider les rattachements. Ctrl+C pour arrêter.

- [ ] parcours complet sans erreur

## Étape 12 : de vrais documents

```powershell
sourcia -c config/local.yaml add-folder "C:\chemin\vers\mes_pdf"
sourcia -c config/local.yaml add-site "<page de publications>" --include "fourrag|sorgho|prairie" --max-pages 30 --medias --no-download
sourcia -c config/local.yaml download --limit 10
sourcia -c config/local.yaml extract
sourcia -c config/local.yaml qualify
sourcia -c config/local.yaml index
sourcia -c config/local.yaml stats
```

- [ ] robots.txt respecté ; titres lisibles ; vidéos et photos trouvées (`--medias`)
- [ ] première mesure sur de vrais documents

## Étape 13 (facultatif) : Gemini, documents publics seulement

```powershell
sourcia -c config/gcp.yaml doctor
sourcia -c config/gcp.yaml formation --demande-fichier config/demandes/agriculteurs_secheresse.yaml --sequences 2 --quiz 2
```

- [ ] « Documents privés non envoyés » affiché ; comparaison 3B / Gemini notée

---

## Remarques

- **Les fiches sont en cache** (`data/fiches.jsonl`) : pour comparer deux modèles, `qualify --force`.
- **Repartir de zéro** : `Get-ChildItem data -Exclude samples | Remove-Item -Recurse -Force`.
- **Formation trop lente** : `--sequences 2 --quiz 2`, moins de sorties dans la demande, ou `config/gcp.yaml` (documents publics).
- **Beaucoup de contenus retirés** : c'est le garde-fou ; regarder l'annexe B.
- **Une erreur** : colle la sortie complète dans la conversation.
