# Mettre SourcIA en ligne

Ce guide part d'un dépôt cloné et d'un PC qui a déjà un catalogue (voir le README, « Utiliser l'application web »).
Il mène à un lien `https://…` que le jury et les enseignants peuvent ouvrir.

## Le principe en trois morceaux

| Morceau | Ce que c'est | Où il vit |
|---|---|---|
| **L'image Docker** | l'application seule (`Dockerfile`), **sans secret ni donnée** | construite par l'hébergeur depuis GitHub |
| **Le volume `/data`** | le catalogue, les comptes, les dossiers des enseignants | un disque persistant chez l'hébergeur |
| **Les 2 secrets** | `GEMINI_API_KEY` et `SOURCIA_SESSION_SECRET` | les réglages de l'hébergeur (variables d'environnement) |

L'image utilise `config/serveur.yaml` : Gemini, recherche légère, données dans `/data`, et le **mode serveur**
(chercher est ouvert à tous ; lancer une formation ou des supports demande d'être connecté).

## Ce qu'il faut

- un hébergeur qui accepte **Docker**, un **disque persistant** (1 Go suffit pour commencer) et le **HTTPS** :
  Render, Railway, Fly.io, ou un serveur de l'établissement avec Docker ;
- une clé Gemini (Google AI Studio). ⚠️ Le niveau gratuit est réservé aux essais : un service ouvert à de vrais
  utilisateurs (Espace économique européen) doit passer au niveau payant ;
- Docker Desktop sur son PC pour l'essai de l'étape 2.

## 1. Préparer les secrets

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Le résultat est le `SOURCIA_SESSION_SECRET` : il signe les cookies de connexion. Gardez **le même** à chaque
redémarrage (sinon tout le monde est déconnecté) ; changez-le seulement si vous voulez déconnecter tout le monde.
Sans lui, ou s'il fait moins de 32 caractères, le serveur refuse de démarrer.

Ces deux valeurs ne vont **jamais** dans le code, dans git, dans une capture d'écran ou sur un canal de discussion.

## 2. Essayer sur son PC (10 minutes)

Dans `.env` (à la racine du dépôt, jamais commité) :

```
GEMINI_API_KEY=la-clé
SOURCIA_SESSION_SECRET=le-secret-de-l-étape-1
```

```powershell
docker compose up --build -d
docker compose ps                       # la colonne STATUS doit finir par « (healthy) »
```

L'application répond sur http://localhost:8000. Le catalogue est vide : c'est l'étape 3.
`docker compose logs -f` montre ce qui se passe ; `docker compose down` arrête (le volume, lui, est gardé).

## 3. Le catalogue

Le catalogue n'est ni dans git ni dans l'image : ce sont des contenus de tiers. Sur le PC qui l'a :

```powershell
python scripts/catalogue_paquet.py creer          # → catalogue-AAAAMMJJ.tar.gz (≈ 6 Mo)
```

Le paquet contient les fiches, les textes extraits, les pages web enregistrées et l'index de recherche. Il ne contient
**ni PDF** (retéléchargés depuis leur site quand un enseignant ajoute le document à un dossier), **ni comptes, ni
dossiers, ni chemin de l'ordinateur** d'origine. Il reste un contenu de tiers : il se transmet en privé.

Import dans le conteneur, puis redémarrage (l'application lit le catalogue au démarrage) :

```powershell
docker compose cp catalogue-AAAAMMJJ.tar.gz sourcia:/tmp/catalogue.tar.gz
docker compose exec sourcia python scripts/catalogue_paquet.py importer /tmp/catalogue.tar.gz
docker compose restart
```

Le script refuse un paquet suspect (chemin `../`, fichier inattendu) et n'écrase pas un catalogue déjà présent sans
`--remplacer`. La page Catalogue affiche « Le catalogue est vide… » tant que rien n'est importé.

**Autre possibilité**, sans transférer de paquet : collecter directement sur le serveur (plus long, demande Internet) :

```powershell
docker compose exec sourcia sourcia collect-sites
docker compose exec sourcia sourcia extract
docker compose exec sourcia sourcia qualify
docker compose exec sourcia sourcia index
docker compose restart
```

## 4. Les comptes

Avec `acces_libre: true` (réglage par défaut de `config/serveur.yaml`, pour le prototype), il n'y a rien à faire :
chaque visiteur a un compte anonyme sans jeton, limité à 3 corpus et 3 productions de supports par jour. Les comptes
ci-dessous restent utiles pour les vrais enseignants (pas de limite) et pour le compte démo du jury.

```powershell
docker compose exec sourcia sourcia comptes ajouter prenom.nom@lycee.fr --url https://adresse-publique
docker compose exec sourcia sourcia comptes demo --url https://adresse-publique
docker compose exec sourcia sourcia comptes lister
```

- Chaque commande affiche un **lien de connexion** une seule fois : c'est un secret, à envoyer en privé à la personne.
- `--url` est l'adresse que les gens ouvriront (`http://localhost:8000` pour l'essai, l'adresse `https://…` en ligne).
- `comptes demo` crée `demo@sourcia.local` avec un dossier déjà rempli (`--sujet`, `--documents`) : c'est le lien à
  donner au jury. Le relancer donne un nouveau lien et rend l'ancien inutilisable (à faire si un lien a circulé).
- `comptes ajouter … --remplacer` renouvelle le lien d'un enseignant ; `comptes retirer …` supprime l'accès.

## 5. Chez l'hébergeur

Les noms des menus changent d'un hébergeur à l'autre ; ce qu'il faut régler est toujours le même :

| Réglage | Valeur |
|---|---|
| Source | le dépôt GitHub, branche `main`, construit avec le `Dockerfile` |
| Variables d'environnement | `GEMINI_API_KEY`, `SOURCIA_SESSION_SECRET` (en « secret » si l'hébergeur le propose) |
| Disque persistant | monté sur **`/data`** |
| Port | l'image écoute sur la variable `PORT` (8000 par défaut) ; laisser l'hébergeur la fixer s'il le fait |
| Vérification de santé | chemin **`/api/etat`** |
| HTTPS | automatique chez Render, Railway et Fly.io ; sur un serveur de l'établissement, derrière un proxy HTTPS (Caddy, Nginx) |

Puis, une fois le service démarré :
1. ouvrir le terminal du service (« Shell », `fly ssh console`, ou `docker compose exec` sur un serveur) ;
2. y copier le paquet du catalogue et lancer `python scripts/catalogue_paquet.py importer …`, puis redémarrer le service ;
3. créer les comptes et le compte démo avec `--url https://adresse-publique` (étape 4, sans `docker compose exec`) ;
4. faire les vérifications de l'étape 6.

Si l'hébergeur ne permet pas de copier un fichier, utilisez la collecte directe de l'étape 3.

## 6. Vérifier

- [ ] cadenas dans la barre d'adresse (HTTPS) ;
- [ ] `https://adresse-publique/api/etat` répond : nombre de documents, `"configuration": "serveur"` ;
- [ ] sans être connecté : la recherche du Catalogue marche ; « Créer la formation » répond « Connectez-vous d'abord » ;
- [ ] le lien de connexion ouvre « Mes dossiers », connecté ;
- [ ] parcours complet : dossier, 4 ou 5 documents ajoutés (ils passent à « prêt »), corpus, supports téléchargés ;
- [ ] après un redémarrage du service : toujours connecté, dossiers toujours là.

## 7. Sauvegarder

Tout ce qui compte est dans `/data` : comptes (empreintes des jetons), dossiers, PDF téléversés par les enseignants
(parfois privés), corpus et supports. Une sauvegarde contient donc des données personnelles : rangez-la en privé.

Sur un serveur avec Docker Compose :

```powershell
docker compose stop
docker run --rm -v saed-defi1_sourcia-data:/data -v ${PWD}:/sauvegarde alpine tar czf /sauvegarde/sourcia-data.tar.gz -C /data .
docker compose start
```

(`saed-defi1_sourcia-data` : nom du volume, visible avec `docker volume ls`.) Chez un hébergeur, utilisez ses
sauvegardes ou instantanés du disque.

## 8. Mettre à jour

- **L'application** : fusionner dans `main` (la CI doit être verte). Les hébergeurs reliés à GitHub reconstruisent tout
  seuls ; sur un serveur : `git pull`, puis `docker compose up --build -d`. Le volume `/data` n'est pas touché.
- **Le catalogue** : nouveau paquet, puis `importer … --remplacer` et un redémarrage. Les comptes et les dossiers ne
  sont jamais touchés.

## Problèmes fréquents

| Ce qu'on voit | Pourquoi | Que faire |
|---|---|---|
| « Mode serveur : la variable SOURCIA_SESSION_SECRET doit contenir au moins 32 caractères » et le service s'arrête | secret absent ou trop court | étape 1, puis redémarrer |
| « Le catalogue est vide » sur la page Catalogue | catalogue pas importé, ou pas de redémarrage après l'import | étape 3 |
| « GEMINI_API_KEY absente » dans les journaux, corpus sans point clé | clé absente ou fausse | vérifier la variable, redémarrer |
| Tout le monde est déconnecté après un redémarrage | `SOURCIA_SESSION_SECRET` a changé | garder toujours la même valeur |
| « Connectez-vous d'abord » en lançant une formation | normal en mode serveur pour un visiteur | ouvrir son lien de connexion |
| Dossiers et comptes disparus après un redémarrage | pas de disque persistant sur `/data` | ajouter le disque, puis refaire les étapes 3 et 4 |
| Un document reste en erreur après l'ajout | PDF injoignable sur son site d'origine | bouton « Relancer », ou choisir un autre document |
