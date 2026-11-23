# SourcIA : film de démonstration (jury du hackathon SAED 2026, défi 1)

**La seule chose à retenir** : SourcIA transforme des centaines de fiches techniques en supports de cours vérifiés,
chaque phrase renvoyant à sa source.

- Format : 1920×1080, 30 i/s, environ 66 s, en français. Voix off (le fil du temps), musique en fond, quelques bruitages.
- Public : jury du hackathon, enseignants et formateurs agricoles. Rien de technique à l'écran.

## Le look : celui de l'application (personne ne doit être perdu)

| Rôle | Valeur |
|---|---|
| Fond (« craie ») | `#f7f8f3` ; planches blanches `#ffffff`, bord `#dcd8c9` 2 px, rayon 20 px |
| Texte | `#2a231c` (terre), secondaire `#5e5145` |
| Action (« bleuet ») | `#2f4fb8`, rebord `#213a8c` (boutons qui s'enfoncent) |
| Choix, étape en cours (« colza ») | `#f5c518` / pâle `#fdf3c4` / texte `#6a5300` |
| Prêt, vérifié (« prairie ») | `#2e7d4b` / pâle `#e3f1e6` |
| Référence (« blé ») | `#efe3be` / texte `#6b5418`, étiquette de semis à pointe |
| Retiré (« coquelicot ») | `#c93a23` / pâle `#fbe7e2` |
| Titres | Fredoka 500–600 ; texte : Atkinson Hyperlegible 400/700 (polices de l'app, `assets/app/fonts`) |

- Les écrans sont ceux de l'app (`capture/` : HTML des vrais écrans, vrais fichiers produits), reconstruits pièce par
  pièce à 1,6–1,9× leur taille : mêmes libellés, mêmes nombres (603 documents, sorgho 86, 16 points, 12 questions,
  16 cartes, 10 diapos).
- Le moment fort, une seule fois : la frise des 4 pots qui poussent (comme dans l'app). Le reste reste calme.
- Accent rationné : le colza pour le choix, la prairie pour « vérifié », le coquelicot une seule fois (la phrase retirée).

## Les plans

| # | Temps | Monde | Voix | Ce qui se passe |
|---|---|---|---|---|
| 1 | 0–7,5 | mur de vraies fiches | v1 | trois colonnes de fiches réelles qui défilent ; compteur jusqu'à 603 |
| 2 | 7,5–14 | le mur flou | v2 | « Lesquelles choisir ? », années qui défilent, « Et en classe ? » |
| 3 | 14–19 | craie | v3 | « SourcIA » lettre à lettre, les 4 pots poussent, le sillon se remplit |
| 4 | 19–29,5 | l'app : Ajouter une source | v4, v5 | clic sur « sorgho », la liste change, « Ajouter » ×2, documents « prêt », PDF personnel + case d'accord |
| 5 | 29,5–43,5 | l'app : Mon corpus | v6, v7 | séquence + capacité C4.4, gros plan sur « S2, page 1 », l'extrait s'ouvre, une phrase barrée « retirée » |
| 6 | 43,5–54 | l'app : Mes supports | v8 | les 12 boutons arrivent, puis les vrais fichiers : diapos, infographie, cartes, une question du QCM |
| 7 | 54–60 | craie | v9 | trois lignes, une à la fois |
| 8 | 60–66 | craie | v10 | la frise se replie dans « SourcIA », « Du champ à la classe », le lien |

## Mouvement

- Arrivées `expo.out` 0,5–0,7 s ; caméra `power2.inOut` 0,6 s ; sorties 40 % plus courtes que les entrées.
- Un seul mouvement principal par plan ; les titres posés ne bougent plus.
- Curseur grand (≈ 64 px), le clic déclenche l'effet sur la même image.
- Transitions : zoom à travers un pot (3 → 4), carry du document vers la liste (4), « l'objet devient le monde »
  (bouton Présentation → diapo plein cadre, 6), changement de fond (7), repli de la frise (8).

## BANNED

Fond sombre, lueurs, particules, dégradés violets, cartes en verre ; tout centré ; tout qui glisse vers le haut ;
trois cartes en rang ; logo dans un coin ; texte qui bouge pendant la lecture ; interface inventée ; capture inclinée en 3D.
