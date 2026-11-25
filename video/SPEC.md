# SourcIA : film de démonstration (jury du hackathon SAED 2026, défi 1)

**La seule chose à retenir** : SourcIA transforme des centaines de fiches techniques en supports de cours vérifiés,
chaque phrase renvoyant à sa source.

- Format : 1920×1080, 30 i/s, environ 75 s, en français. Voix off (le fil du temps), musique en fond, quelques bruitages.
- Public : jury du hackathon, enseignants et formateurs agricoles. Rien de technique à l'écran.

## Le look : celui du site (style SAED, personne ne doit être perdu)

| Rôle | Valeur |
|---|---|
| Fond | `#f7f6fc` ; planches blanches `#ffffff`, bord `#e2dfef` 2 px, grands rayons |
| Texte | `#202033`, secondaire `#626176` |
| Action, titres (bleu nuit) | `#090773` ; boutons en pilule bleu nuit, texte blanc |
| Choix, étape (lavande) | `#eeebf9` / `#e2dfef` / `#9a8bd0` ; pastilles numérotées 1 à 4 |
| Prêt, vérifié | `#2e7d4b` / pâle `#e3f1e6` (seulement l'étiquette « prêt ») |
| Retiré | `#c93a23` / pâle `#fbe7e2` (une seule fois) |
| Titres | Playfair Display (proche du Georgia du site) ; boutons : Inter ; texte : Atkinson Hyperlegible |
| Marque | le « S » blanc dans son carré bleu nuit, « SourcIA », « RESSOURCES PÉDAGOGIQUES », « Du champ à la classe » |

- Les écrans sont ceux de l'app (`capture/` : HTML des vrais écrans, vrais fichiers produits), reconstruits pièce par
  pièce à 1,6–1,9× leur taille : mêmes libellés, mêmes nombres (603 documents, sorgho 86, 16 points, 12 questions,
  16 cartes, 10 diapos).
- Le moment fort, une seule fois : les 4 étapes du site qui s'allument (Catalogue, Mon dossier, Mon contenu, Mes supports).
- Accent rationné : la lavande pour le choix, le vert pour « prêt », le rouge une seule fois (la phrase retirée).

## Les plans

| # | Temps | Monde | Voix | Ce qui se passe |
|---|---|---|---|---|
| 1 | 0–7,5 | mur de vraies fiches | v1 | trois colonnes de fiches réelles qui défilent ; compteur jusqu'à 603 |
| 2 | 7,5–14 | le mur flou | v2 | « Lesquelles choisir ? », années qui défilent, « Et en classe ? » |
| 3 | 14–19 | craie | v3 | la marque SourcIA, puis les 4 étapes numérotées s'allument ; zoom à travers l'étape 1 |
| 4 | 19–29,5 | l'app : Ajouter une source | v4, v5 | clic sur « sorgho », la liste change, « Ajouter » ×2, documents « prêt », PDF personnel + case d'accord |
| 5 | 29,5–43,5 | l'app : Mon contenu | v6, v7 | séquence + capacité C4.4, gros plan sur « S2, page 1 », l'extrait s'ouvre, une phrase barrée « retirée » |
| 6 | 43,5–54 | l'app : Mes supports | v8 | « Supports produits » et ses boutons rangés par groupe, puis les vraies pages : QCM corrigé, cartes, diapo, infographie, fiche technique, glossaire, podcast |
| 7 | 54–60 | craie | v9 | trois lignes, une à la fois |
| 8 | 60–66 | craie | v10 | la marque, « Du champ à la classe », le lien du site |

## Mouvement

- Arrivées `expo.out` 0,5–0,7 s ; caméra `power2.inOut` 0,6 s ; sorties 40 % plus courtes que les entrées.
- Un seul mouvement principal par plan ; les titres posés ne bougent plus.
- Curseur grand (≈ 64 px), le clic déclenche l'effet sur la même image.
- Transitions : zoom à travers l'étape 1 (3 → 4), carry du document vers la liste (4), « l'objet devient le monde »
  (bouton Présentation → diapo plein cadre, 6), changement de fond (7), la marque qui se pose (8).

## BANNED

Fond sombre, lueurs, particules, dégradés violets, cartes en verre ; tout centré ; tout qui glisse vers le haut ;
trois cartes en rang ; logo dans un coin ; texte qui bouge pendant la lecture ; interface inventée ; capture inclinée en 3D.
