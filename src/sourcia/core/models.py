"""Les objets échangés entre modules. Les deux formats d'échange publics :

- ``documents.jsonl`` : un ``Document`` par ligne (sortie de la collecte, M1) ;
- ``fiches.jsonl``    : une ``Fiche`` de qualification par ligne (sortie de M3).

Un module d'un autre membre de l'équipe peut produire ou lire ces fichiers : c'est le contrat.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field


def doc_id_for(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()[:16]


class Document(BaseModel):
    """Un document trouvé par la collecte (pas encore lu)."""

    id: str
    url: str                                     # adresse d'origine (ou chemin local pour un document privé)
    source: str                                  # site ou connecteur : "arvalis.fr", "rdagri", "prive"...
    title: str = ""
    date: str | None = None                      # date connue par la source (AAAA ou AAAA-MM-JJ)
    keywords: list[str] = Field(default_factory=list)
    licence: str | None = None
    private: bool = False                        # document privé : jamais envoyé à un modèle en ligne
    local_path: str | None = None                # fichier téléchargé
    sha1: str | None = None                      # empreinte du contenu (doublons entre sites)
    meta: dict[str, Any] = Field(default_factory=dict)
    kind: Literal["pdf", "texte", "page", "donnees", "video", "image", "audio"] = "pdf"   # nature de la ressource
    status: Literal["listed", "downloaded", "extracted", "qualified", "error"] = "listed"
    error: str | None = None


class Field_(BaseModel):
    """Un champ qualifié : une valeur, la PREUVE (passage du document) et un niveau de confiance.

    Règle : sans preuve retrouvée dans le texte, la valeur est rejetée (``value=None``)."""

    value: Any = None
    evidence: str | None = None
    confidence: float = 0.0
    method: Literal["source", "regles", "llm", "humain", "none"] = "none"


DOC_TYPES = ["experimentation", "retour_experience", "synthese", "guide_technique", "autre"]


class Fiche(BaseModel):
    """Fiche de qualification d'un document (colonnes à aligner sur « l'Excel » du métier)."""

    document_id: str
    organisme: Field_ = Field(default_factory=Field_)
    annee: Field_ = Field(default_factory=Field_)
    lieu: Field_ = Field(default_factory=Field_)
    contexte_pedoclimatique: Field_ = Field(default_factory=Field_)
    annee_publication: Field_ = Field(default_factory=Field_)        # année de sortie du document
    type: Field_ = Field(default_factory=Field_)                     # une valeur de DOC_TYPES
    modalites: Field_ = Field(default_factory=Field_)                # nombre de modalités testées
    repetitions: Field_ = Field(default_factory=Field_)              # nombre de répétitions
    chiffrage_economique: Field_ = Field(default_factory=Field_)     # True / False
    themes: list[str] = Field(default_factory=list)
    resume: str | None = None                                        # 1 à 2 phrases (si LLM)
    alertes: list[str] = Field(default_factory=list)
    passes: list[str] = Field(default_factory=list)                  # "regles", "llm"
    cout_s: float = 0.0                                              # temps de qualification

    # « annee » = année des RÉSULTATS (essai, campagne) ; « annee_publication » = année de sortie du document
    FIELDS: ClassVar[tuple[str, ...]] = ("organisme", "annee", "annee_publication", "lieu", "contexte_pedoclimatique", "type",
              "modalites", "repetitions", "chiffrage_economique")

    def get(self, name: str) -> Any:
        return getattr(self, name).value

    def year(self) -> int | None:
        """Année de référence : celle des résultats, sinon celle de publication."""
        y = self.get("annee")
        return y if isinstance(y, int) else (self.get("annee_publication") if isinstance(self.get("annee_publication"), int) else None)


@dataclass
class Chunk:
    id: str
    doc_id: str
    text: str
    page: int = 1


@dataclass
class Hit:
    chunk: Chunk
    score: float
    source: str = ""
    rank: int = 0


@dataclass
class Candidate:
    """Un document candidat pour la sélection, avec ses scores et sa justification."""

    document: Document
    fiche: Fiche | None
    relevance: float = 0.0
    passage: str = ""                     # meilleur passage pour la demande
    page: int = 1
    score: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    justification: str = ""
