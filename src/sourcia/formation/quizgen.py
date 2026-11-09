"""QCM construits SANS modèle à partir des points clés déjà vérifiés (repli quand le petit modèle échoue).

Principe : dans une phrase vérifiée, on masque une information précise (une valeur chiffrée avec son unité,
sinon une culture ou un animal) ; la bonne réponse est l'information masquée ; les distracteurs sont d'autres
valeurs de même unité trouvées dans les sources (sinon des valeurs voisines), ou d'autres cultures citées.
La question est juste PAR CONSTRUCTION : elle reprend mot pour mot une phrase soutenue par sa source.
"""
from __future__ import annotations

import hashlib
import re

from sourcia.core.text import normalize
from sourcia.formation.checks import ENTITIES, entities

UNIT = r"(?:t\s?MS/ha|t\s?MS|kg/ha|q/ha|€/t\s?MS|€/ha|€|%|mm|°C|ha|unités|vaches|cm|jours|UFL/kg\s?MS)"
VALUE_RE = re.compile(rf"(\d+(?:[,.]\d+)?)\s?({UNIT})")


DISPLAY = {"mais": "maïs", "meteil": "méteil", "trefle": "trèfle", "fetuque": "fétuque", "feverole": "féverole",
           "ble": "blé", "chicoree": "chicorée", "chevre": "chèvre", "equin": "équin"}


def _fmt(x: float, like: str) -> str:
    dec = len(like.split(",")[1]) if "," in like else len(like.split(".")[1]) if "." in like else 0
    s = f"{x:.{dec}f}"
    return s.replace(".", ",") if "," in like else s


def _values(texts: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for t in texts:
        for v, u in VALUE_RE.findall(t):
            out.setdefault(" ".join(u.split()), set()).add(v)
    return out


def _order(key: str, n: int) -> int:
    return int(hashlib.sha1(key.encode()).hexdigest(), 16) % n


def make_question(text: str, corpus_texts: list[str], topic: frozenset = frozenset()) -> dict | None:
    """Une question à partir d'une phrase vérifiée, ou None si rien de précis à demander.
    ``topic`` : mots du sujet ; on ne masque pas une culture du sujet (« Le …… fourrager » : trop facile)."""
    m = VALUE_RE.search(text)
    if m:
        val, unit = m.group(1), " ".join(m.group(2).split())
        in_sentence = {v for v, _ in VALUE_RE.findall(text)}            # pas de distracteur présent dans la phrase
        pool = [v for v in sorted(_values(corpus_texts).get(unit, set())) if v not in in_sentence]
        x = float(val.replace(",", "."))
        for f in (0.5, 0.75, 1.5, 2.0, 1.25):                          # valeurs voisines si les sources n'en ont pas assez
            cand = _fmt(x * f, val)
            if cand not in in_sentence and cand not in pool:
                pool.append(cand)
        wrong = pool[:3]
        right = f"{val} {unit}"
        choices = [f"{w} {unit}" for w in wrong]
        stem = text[: m.start()] + "……" + text[m.end():]
    else:
        from sourcia.core.text import tokenize

        ents = entities(text)
        askable = sorted(e for e in ents if not set(tokenize(e)) & topic)
        if not askable:
            return None
        target = askable[0]
        t_norm = normalize(text)
        mm = re.search(rf"\b{re.escape(target)}s?\b", t_norm)
        if not mm or len(t_norm) != len(text):
            return None
        right = text[mm.start(): mm.end()]
        others = sorted({e for t in corpus_texts for e in entities(t)} - ents) or [e for e in ENTITIES if e not in ents]
        if len(others) < 3:
            others += [e for e in ENTITIES if e not in ents and e not in others]
        others = [o for o in others if o not in entities(text)]
        choices = [DISPLAY.get(o, o) for o in others[:3]]
        stem = text[: mm.start()] + "……" + text[mm.end():]
    pos = _order(text, 4)
    choices.insert(pos, right)
    if len({normalize(c) for c in choices}) != 4:
        return None
    return {"enonce": f"Complétez : « {stem.strip()} »", "choix": choices, "bonne_reponse": pos,
            "explication": text}
