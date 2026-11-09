"""Un référentiel = un diplôme, une version, des capacités (code + libellé), un statut de validation."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Statut = Literal["extrait_automatiquement", "valide", "a_revoir"]

# Niveaux du cadre national des certifications professionnelles (2019)
NIVEAUX_CNCP = {"capa": 3, "cap": 3, "bacpro": 4, "bp": 4, "bts": 5, "btsa": 5, "licence": 6}


class Capacite(BaseModel):
    code: str                                     # C4.2, CP5.1, CG1…
    libelle: str
    parent: str | None = None                     # C4 pour C4.2
    variantes: list[str] = Field(default_factory=list)   # libellés différents selon le support (ex. CAPa)
    statut: Statut = "extrait_automatiquement"
    commentaire: str = ""


class Referentiel(BaseModel):
    id: str                                       # btsa-acsagri
    nom: str
    type: str                                     # capa, bacpro, btsa…
    niveau: int | None = None                     # niveau CNCP
    version: str = ""                             # année ou date de la version
    sources: list[dict] = Field(default_factory=list)    # {fichier|url, sha1}
    statut: Statut = "extrait_automatiquement"
    valide_par: str = ""
    capacites: list[Capacite] = Field(default_factory=list)

    def get(self, code: str) -> Capacite | None:
        code = normalize_code(code)
        return next((c for c in self.capacites if c.code == code), None)

    def children(self, code: str) -> list[Capacite]:
        return [c for c in self.capacites if c.parent == normalize_code(code)]

    def leaves(self, codes: list[str]) -> list[Capacite]:
        """Les capacités « feuilles » visées : C4 → C4.1…C4.4 ; C4.2 → C4.2."""
        out = []
        for code in codes:
            c = self.get(code)
            if c is None:
                continue
            kids = self.children(c.code)
            out += kids or [c]
        return list({c.code: c for c in out}.values())

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump()
        path.write_text("# Référentiel extrait par SourcIA. statut « valide » seulement après relecture par un enseignant.\n"
                        + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "Referentiel":
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def normalize_code(code: str) -> str:
    return code.upper().replace(" ", "").rstrip(".")


class ReferentielStore:
    """Les référentiels disponibles : ``config/referentiels/<id>.yaml``."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.yaml") if p.stem != "catalogue")

    def get(self, rid: str) -> Referentiel | None:
        p = self.folder / f"{rid}.yaml"
        return Referentiel.load(p) if p.exists() else None

    def all(self) -> list[Referentiel]:
        return [r for r in (self.get(i) for i in self.ids()) if r]
