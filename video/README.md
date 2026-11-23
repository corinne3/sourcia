# Vidéo de démonstration de SourcIA (HyperFrames)

Film de 75 s pour le jury : le parcours Catalogue → Dossier → Corpus → Supports, au design de l'application, avec
voix off française, musique et bruitages. La fiche du film est dans [`SPEC.md`](SPEC.md), le texte de la voix dans
[`VOIX.md`](VOIX.md).

| Dossier | Contenu |
|---|---|
| `index.html` | le film : 8 scènes, la voix (10 phrases), la musique, les bruitages |
| `compositions/` | une scène par fichier (`s1-fiches.html` … `s8-fin.html`) |
| `assets/app/` | polices et feuille de style de l'application |
| `assets/voice/` | voix off (Gemini TTS, voix « Kore ») |
| `assets/sfx/` | bruitages (Pixabay, licence libre, voir `CREDITS.md`) |
| `assets/bgm/`, `assets/supports/`, `capture/` | musique et vrais supports produits : hors de git (voir `.gitignore`) |
| `outils/faire_s1.py` | écrit la scène 1 à partir des titres réels du catalogue |

## Voir, modifier, rendre

HyperFrames s'utilise avec son lanceur (skill `hyperframes`) ; sur un PC où Windows bloque son navigateur, donner
Edge : `$env:HYPERFRAMES_BROWSER_PATH = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"`.

```powershell
npx hyperframes preview            # aperçu modifiable dans le navigateur
npx hyperframes render --docker -q delivery -o renders/sourcia-demo.mp4
```

Le rendu dans Docker évite d'installer FFmpeg sur le PC. Le lien de fin est une variable (`lien`, dans
`compositions/s8-fin.html`) : mettre l'adresse Azure définitive avant le rendu final.

## Refaire la voix et la musique

- Voix : `audio_request.json` (Gemini TTS, clé `GEMINI_API_KEY`). Le niveau gratuit permet 3 phrases par minute.
- Musique : Lyria (même clé), consigne dans `VOIX.md`, 78 s à 100 bpm.
- Captures : un vrai dossier « sorgho » construit dans l'app (5 documents, corpus de 16 points, 7 supports).
