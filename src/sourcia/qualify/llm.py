"""Qualification, passe 2 : un modèle lit les premières pages et remplit la fiche, AVEC PREUVES.

Garde-fous :
- chaque valeur doit citer un passage ; si ce passage ne se retrouve pas dans le texte,
  la valeur est REJETÉE (le modèle ne peut pas inventer une année ou un lieu) ;
- pour un nombre (année, modalités, répétitions), la valeur doit figurer dans la preuve citée ;
- « non trouvé » est une réponse valide, encouragée par la consigne ;
- un document privé n'est jamais envoyé à un modèle en ligne.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from sourcia.core.models import DOC_TYPES, Field_, Fiche
from sourcia.core.text import normalize, tokenize
from sourcia.llm.base import Message, chat_structured

SYSTEM = (
    "Tu qualifies des documents de R&D agricole pour des formateurs. Tu lis le début d'un document "
    "et tu remplis une fiche en JSON. Pour CHAQUE champ, donne la valeur ET la preuve : une phrase "
    "COPIÉE MOT POUR MOT du document. Si l'information n'est pas dans le texte, mets null pour la "
    "valeur et pour la preuve : ne devine jamais. "
    f"Le type est l'une de ces valeurs : {', '.join(DOC_TYPES)}. Une « experimentation » a un dispositif "
    "(modalités, répétitions, témoin) ; un « retour_experience » raconte des pratiques d'agriculteurs. "
    "« annee » est l'année des RÉSULTATS (essai, campagne) ; « annee_publication » l'année de sortie du document."
)


class Champ(BaseModel):
    valeur: Optional[str | int | float | bool] = None
    preuve: Optional[str] = None


class FicheLLM(BaseModel):
    organisme: Champ
    annee: Champ
    annee_publication: Champ = Champ()
    lieu: Champ
    contexte_pedoclimatique: Champ
    type: Champ
    modalites: Champ
    repetitions: Champ
    chiffrage_economique: Champ
    resume: Optional[str] = None


def evidence_found(evidence: str | None, text: str, min_overlap: float) -> bool:
    """La preuve se retrouve-t-elle dans le texte ? (part de ses mots présents, à l'ordre près)."""
    if not evidence or len(evidence.strip()) < 4:
        return False
    ev, tx = tokenize(evidence), set(tokenize(text))
    if not ev:
        return evidence.strip().lower() in text.lower()
    return sum(w in tx for w in ev) / len(ev) >= min_overlap


NUM_WORDS = {2: "deux", 3: "trois", 4: "quatre", 5: "cinq", 6: "six", 7: "sept", 8: "huit", 9: "neuf", 10: "dix"}


def value_in_evidence(name: str, value, evidence: str) -> bool:
    """Garde-fou n° 2 : pour un nombre, la valeur doit figurer DANS la preuve.

    Sans cela, le modèle peut citer une vraie phrase (« essai 2016 ») et donner une autre valeur (2023)."""
    if name not in ("annee", "annee_publication", "modalites", "repetitions"):
        return True
    words = set(re.findall(r"\w+", normalize(evidence or "")))
    return str(value) in words or NUM_WORDS.get(value, "§") in words


def _coerce(name: str, value):
    if value in (None, "", "null", "non trouvé", "inconnu"):
        return None
    if name in ("annee", "annee_publication", "modalites", "repetitions"):
        try:
            return int(str(value)[:4]) if name.startswith("annee") else int(value)
        except (TypeError, ValueError):
            return None
    if name == "chiffrage_economique":
        return value if isinstance(value, bool) else str(value).lower() in ("true", "oui", "vrai", "1")
    if name == "type":
        v = str(value).lower().replace(" ", "_").replace("'", "_").replace("é", "e")
        return v if v in DOC_TYPES else None
    return str(value)[:200]


def qualify_llm(llm, text: str, min_overlap: float) -> tuple[Fiche, dict]:
    """Renvoie la fiche du modèle (valeurs sans preuve vérifiée retirées) et un rapport."""
    msgs = [Message("system", SYSTEM), Message("user", f"Document :\n\"\"\"\n{text}\n\"\"\"\n\nRemplis la fiche.")]
    out, attempts = chat_structured(llm, msgs, FicheLLM, max_tokens=700)
    f = Fiche(document_id="")
    report = {"rejetes": [], "tentatives": attempts}
    for name in Fiche.FIELDS:
        c: Champ = getattr(out, name)
        value = _coerce(name, c.valeur)
        if value is None:
            continue
        if name == "chiffrage_economique" and value is False:
            setattr(f, name, Field_(value=False, confidence=0.4, method="llm"))
            continue
        if not evidence_found(c.preuve, text, min_overlap) or not value_in_evidence(name, value, c.preuve):
            report["rejetes"].append(name)                 # pas de preuve retrouvée : valeur écartée
            continue
        setattr(f, name, Field_(value=value, evidence=c.preuve[:300], confidence=0.75, method="llm"))
    f.resume = (out.resume or "")[:400] or None
    f.passes.append("llm")
    return f, report
