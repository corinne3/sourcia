"""Formes attendues du modèle (JSON validé par Pydantic). Schémas volontairement SIMPLES :
un schéma compliqué dégrade les petits modèles."""
from __future__ import annotations

from typing import Literal

import re

from pydantic import BaseModel, Field, field_validator


def _num(v):
    """Tolérance : le petit modèle écrit « [3] », « passage 3 » ou « 3 » pour le numéro de passage."""
    if isinstance(v, str):
        m = re.search(r"\d+", v)
        return int(m.group(0)) if m else v
    if isinstance(v, list) and v:
        return _num(v[0])
    return v


def _short(limit: int):
    """Coupe un texte trop long à la dernière fin de phrase avant la limite. Le petit modèle part parfois en boucle
    (« Elle est également appelée… » × 20) : la réponse JSON était coupée, donc invalide (vu le 09/11)."""
    def f(cls, v):
        if not isinstance(v, str) or len(v) <= limit:
            return v
        cut = v[:limit]
        end = max(cut.rfind(". "), cut.rfind(" ; "))
        return cut[: end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "…"
    return classmethod(f)


def _letter(v):
    """« B », « b) », « 2 » ou 2 → index 0 à 3 (« B » = 1)."""
    if isinstance(v, str):
        t = v.strip().upper()
        if t[:1] in "ABCD" and (len(t) == 1 or not t[1].isalpha()):
            return "ABCD".index(t[0])
        m = re.search(r"\d", t)
        return int(m.group(0)) if m else v
    return v

Public = Literal["bac_pro", "bts", "licence_pro", "agriculteurs", "conseillers"]
PUBLICS: dict[str, str] = {
    "bac_pro": "élèves de bac pro agricole (vocabulaire de base expliqué, exemples concrets d'exploitation)",
    "bts": "étudiants de BTS agricole (vocabulaire technique, mécanismes expliqués, chiffres clés)",
    "licence_pro": "étudiants de licence professionnelle (mécanismes détaillés, limites des essais)",
    "agriculteurs": "agriculteurs en formation continue (concret, pratique, économique, peu de théorie)",
    "conseillers": "conseillers agricoles (résultats d'essais, conditions de validité, nuances)",
}


class Sequence(BaseModel):
    titre: str = Field(description="Titre court de la séquence")
    objectif: str = Field(description="Ce que l'apprenant saura faire à la fin : une phrase qui COMMENCE par un verbe d'action")
    capacite: str | None = Field(default=None, description="Code de la capacité du référentiel visée (formation diplômante)")
    duree_min: int = Field(description="Durée en minutes", ge=10, le=240)
    mots_cles: list[str] = Field(description="3 à 6 mots-clés pour retrouver les passages utiles", min_length=1, max_length=8)


class PlanFormation(BaseModel):
    titre: str
    sequences: list[Sequence] = Field(min_length=1, max_length=8)


class PointCle(BaseModel):
    texte: str = Field(max_length=400, description="Une information du passage, en une ou deux phrases")
    source: int = Field(ge=1, description="Numéro du passage [n] qui contient cette information")

    _src = field_validator("source", mode="before")(classmethod(lambda cls, v: _num(v)))
    _txt = field_validator("texte", mode="before")(_short(400))


class FicheSequence(BaseModel):
    points_cles: list[PointCle] = Field(min_length=2, max_length=8)
    a_retenir: str = Field(description="Une phrase de conclusion")


class QuestionQCM(BaseModel):
    enonce: str = Field(max_length=250)
    choix: list[str] = Field(description="Exactement 4 propositions courtes (10 mots au plus, sans parenthèses)",
                             min_length=4, max_length=4)
    # l'explication AVANT l'index : le modèle raisonne d'abord, l'index en découle
    explication: str = Field(max_length=300, description="UNE phrase (30 mots au plus) reprise du passage cité")
    bonne_reponse: int = Field(ge=0, le=3, description="Index (0 à 3) de la proposition que l'explication justifie")
    source: int = Field(ge=1, description="Numéro du passage [n] qui justifie la réponse")

    _src = field_validator("source", mode="before")(classmethod(lambda cls, v: _num(v)))
    _rep = field_validator("bonne_reponse", mode="before")(classmethod(lambda cls, v: _letter(v)))
    _exp = field_validator("explication", mode="before")(_short(300))
    _enc = field_validator("enonce", mode="before")(_short(250))

    @field_validator("choix", mode="before")
    @classmethod
    def choix_courts(cls, v):
        return [c if not isinstance(c, str) or len(c) <= 120 else c[:120].rsplit(" ", 1)[0] for c in v] if isinstance(v, list) else v

    @field_validator("choix")
    @classmethod
    def distincts(cls, v: list[str]) -> list[str]:
        if len({c.strip().lower() for c in v}) != len(v):
            raise ValueError("les 4 choix doivent être différents")
        return v


class Quiz(BaseModel):
    questions: list[QuestionQCM] = Field(min_length=1, max_length=12)


class Terme(BaseModel):
    terme: str = Field(max_length=60)
    definition: str = Field(max_length=250, description="UNE phrase (25 mots au plus) tirée du passage")
    source: int = Field(ge=1)
    _def = field_validator("definition", mode="before")(_short(250))

    _src = field_validator("source", mode="before")(classmethod(lambda cls, v: _num(v)))


class Glossaire(BaseModel):
    termes: list[Terme] = Field(min_length=2, max_length=15)


class CasPratique(BaseModel):
    contexte: str = Field(description="Une exploitation FICTIVE et son problème, en 3 à 5 phrases")
    questions: list[str] = Field(min_length=2, max_length=5)
    elements_de_reponse: list[PointCle] = Field(min_length=2, max_length=8)


class FicheTechnique(BaseModel):
    titre: str
    recommandations: list[PointCle] = Field(min_length=2, max_length=10, description="Ce qu'il faut faire, chiffré si possible")
    vigilance: list[PointCle] = Field(default_factory=list, max_length=6, description="Points de vigilance")


class Synthese(BaseModel):
    paragraphes: list[PointCle] = Field(min_length=2, max_length=8)
    conclusion: str


class Replique(BaseModel):
    voix: Literal["animateur", "expert"]
    texte: str
    source: int | None = Field(default=None, description="Numéro du passage [n] (obligatoire pour l'expert)")

    _src = field_validator("source", mode="before")(classmethod(lambda cls, v: _num(v) if v not in ("", None) else None))


class ScriptPodcast(BaseModel):
    titre: str
    repliques: list[Replique] = Field(min_length=4, max_length=30)
