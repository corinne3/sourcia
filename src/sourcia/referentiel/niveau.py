"""Contrôle du niveau d'une formation, sans modèle.

1. VERBES DES OBJECTIFS (taxonomie de Bloom révisée) : le premier verbe d'un objectif dit le niveau d'exigence
   (1 se souvenir … 6 créer). On compare au niveau attendu pour le public, et, pour une formation diplômante,
   au verbe de la capacité du référentiel visée.
2. LISIBILITÉ : formule de Kandel et Moles (adaptation française de Flesch) sur le texte produit.
   Plus le score est haut, plus le texte est facile.
Les seuils sont des PROPOSITIONS, à calibrer avec des enseignants (docs/DOSSIER_ARCHITECTURE.md).
"""
from __future__ import annotations

import re

from sourcia.core.text import normalize, split_sentences

BLOOM: dict[int, list[str]] = {
    1: ["citer", "nommer", "identifier", "reconnaitre", "lister", "definir", "reperer", "connaitre", "decrire", "situer"],
    2: ["expliquer", "comprendre", "illustrer", "resumer", "interpreter", "distinguer", "classer", "presenter",
        "caracteriser", "exprimer", "communiquer", "s'exprimer", "positionner"],
    3: ["appliquer", "realiser", "mettre", "utiliser", "calculer", "effectuer", "executer", "assurer", "alimenter",
        "organiser", "conduire", "repondre", "agir", "adopter", "adapter", "s'adapter", "inserer", "s'inserer",
        "manager", "gerer", "cooperer", "contribuer", "developper", "stimuler", "prendre", "interagir", "s'approprier"],
    4: ["analyser", "comparer", "diagnostiquer", "etudier", "examiner", "exploiter", "debattre", "observer",
        "faire", "construire"],
    5: ["evaluer", "justifier", "argumenter", "choisir", "decider", "estimer", "ajuster", "piloter", "juger",
        "formuler", "accompagner", "elaborer", "interpreter"],
    6: ["concevoir", "proposer", "imaginer", "creer", "inventer", "planifier", "definir"],
}
VERB_LEVEL = {}
for lvl, verbs in sorted(BLOOM.items()):
    for v in verbs:
        VERB_LEVEL.setdefault(v, lvl)
BLOOM_LABEL = {1: "se souvenir", 2: "comprendre", 3: "appliquer", 4: "analyser", 5: "évaluer", 6: "créer"}

# niveau d'exigence attendu (min, max) selon le niveau d'étude : PROPOSITION à calibrer
EXPECTED_BLOOM = {"sans_diplome": (1, 3), "cap": (1, 3), "bac_pro": (1, 4), "bac": (1, 4), "bts": (2, 6),
                  "licence": (3, 6), "master_ingenieur": (3, 6)}
# lisibilité minimale (Kandel-Moles) : PROPOSITION à calibrer
MIN_READABILITY = {"sans_diplome": 65, "cap": 60, "bac_pro": 50, "bac": 45, "bts": 35, "licence": 30, "master_ingenieur": 25}


def verb_level(text: str) -> tuple[str | None, int | None]:
    words = re.findall(r"[\w’']+", normalize(text).replace("’", "'"))
    if not words:
        return None, None
    w = words[0]
    if w in ("s", "se", "d", "l") and len(words) > 1:
        w = f"s'{words[1]}"
    if w.startswith("s'") and w not in VERB_LEVEL:
        w = w[2:]
    for cand in (w, w.split("'")[-1]):
        if cand in VERB_LEVEL:
            return cand, VERB_LEVEL[cand]
    return w, None


def _syllables(word: str) -> int:
    w = normalize(word)
    n = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and n > 1:
        n -= 1                                            # e muet final
    return max(1, n)


def readability(text: str) -> float | None:
    """Kandel et Moles (1958) : 207 − 1,015 × (mots / phrases) − 73,6 × (syllabes / mots)."""
    sentences = [s for s in split_sentences(text) if s.strip()]
    words = re.findall(r"[A-Za-zÀ-ÿ’'-]+", text)
    if not sentences or len(words) < 20:
        return None
    syl = sum(_syllables(w) for w in words)
    return round(207 - 1.015 * len(words) / len(sentences) - 73.6 * syl / len(words), 1)


def check_objectives(objectives: list[tuple[str, str]], niveau: str, ref=None, codes: list[str | None] | None = None) -> list[dict]:
    """objectives : (titre de la séquence, objectif). Renvoie une ligne par séquence avec alerte éventuelle."""
    lo, hi = EXPECTED_BLOOM.get(niveau, (1, 6))
    out = []
    for i, (title, obj) in enumerate(objectives):
        verb, lvl = verb_level(obj)
        row = {"sequence": title, "verbe": verb, "niveau_bloom": lvl, "attendu": f"{lo} à {hi}", "alerte": None}
        code = (codes or [None] * len(objectives))[i]
        cap = ref.get(code) if (ref and code) else None
        if cap:
            cverb, clvl = verb_level(cap.libelle)
            row |= {"capacite": cap.code, "verbe_capacite": cverb, "niveau_capacite": clvl}
            if lvl and clvl and lvl < clvl - 2:
                row["alerte"] = (f"objectif « {verb} » ({BLOOM_LABEL[lvl]}) bien en dessous de la capacité "
                                 f"{cap.code} « {cverb} » ({BLOOM_LABEL[clvl]})")
        if row["alerte"] is None and lvl and not lo <= lvl <= hi:
            row["alerte"] = (f"objectif « {verb} » ({BLOOM_LABEL[lvl]}) hors du niveau attendu pour ce public "
                             f"({BLOOM_LABEL[lo]} à {BLOOM_LABEL[hi]})")
        if lvl is None:
            row["alerte"] = f"verbe « {verb} » non reconnu : vérifier que l'objectif commence par un verbe d'action"
        out.append(row)
    return out


def check_readability(text: str, niveau: str) -> dict:
    score = readability(text)
    mini = MIN_READABILITY.get(niveau)
    alert = None
    if score is not None and mini is not None and score < mini:
        alert = f"texte difficile pour ce public (lisibilité {score} < {mini} attendu) : phrases plus courtes, mots plus simples"
    return {"lisibilite": score, "minimum": mini, "alerte": alert}
