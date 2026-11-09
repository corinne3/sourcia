"""M0 Demande structurée : le « bon de commande » du formateur, contrat commun de tous les modules.

Les 7 critères du point avec le métier (mail du 09/11/2026), plus le référentiel pour une formation diplômante.
Chaque critère a une valeur PAR DÉFAUT proposée (la plus probable) pour qu'on puisse coder sans attendre ;
elles sont listées dans docs/DOSSIER_ARCHITECTURE.md, section « Propositions », à valider par l'équipe.

Où chaque critère sert :
| critère                 | M5 sélection                        | M7 formation                               |
| profil du demandeur     | préférences de types de documents   | ton, attentes (référentiel, chiffres…)      |
| type de formation       | —                                   | diplômante → référentiel ; modalité → sorties |
| public cible            | préférences de types                 | niveau de langue, verbes des objectifs      |
| types de ressources     | filtres (type, nature)               | —                                          |
| formes de résultat      | —                                   | quels contenus produire                    |
| précisions sur sources  | filtres (années, privé, région…)     | annexe des sources                          |
| contenu personnel       | ajouté au corpus (privé)             | intégré et protégé à la régénération       |
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Profil = Literal["enseignant", "formateur", "conseiller", "intervenant_exterieur", "autre"]
Modalite = Literal["presentiel", "distanciel", "hybride"]
Support = Literal["ecrit", "oral", "pratique"]
TypeApprenant = Literal["eleves", "apprentis", "etudiants", "salaries", "chefs_entreprise", "conseillers", "autre"]
NiveauEtude = Literal["sans_diplome", "cap", "bac_pro", "bac", "bts", "licence", "master_ingenieur"]
Experience = Literal["debutant", "intermediaire", "confirme"]
Ressource = Literal["resultats_rd", "experimentation", "temoignage", "synthese", "guide_technique",
                    "donnees", "photo", "video", "audio"]
Sortie = Literal["plan", "fiche_technique", "synthese", "points_cles", "quiz", "cas_concret", "glossaire",
                 "podcast", "deroule_oral"]

PROFILS = {
    "enseignant": "un enseignant : le contenu doit servir les capacités du référentiel et préparer l'évaluation",
    "formateur": "un formateur : contenu concret, directement utilisable en séance",
    "conseiller": "un conseiller agricole : résultats chiffrés, conditions de validité, nuances",
    "intervenant_exterieur": "un intervenant extérieur : support autonome, contexte rappelé, vocabulaire défini",
    "autre": "un demandeur : contenu clair et sourcé",
}
APPRENANTS = {
    "eleves": "des élèves", "apprentis": "des apprentis (alternance : lien fort avec le terrain)",
    "etudiants": "des étudiants", "salaries": "des salariés agricoles", "chefs_entreprise": "des chefs d'exploitation",
    "conseillers": "des conseillers", "autre": "des apprenants",
}
NIVEAUX = {
    "sans_diplome": "sans diplôme : phrases très courtes, aucun jargon",
    "cap": "niveau CAP : phrases courtes, gestes et repères concrets, vocabulaire de base expliqué",
    "bac_pro": "niveau bac pro : vocabulaire technique de base expliqué, exemples d'exploitation",
    "bac": "niveau bac : vocabulaire technique expliqué",
    "bts": "niveau BTS : vocabulaire technique, mécanismes expliqués, chiffres clés",
    "licence": "niveau licence : mécanismes détaillés, limites des essais",
    "master_ingenieur": "niveau master ou ingénieur : nuances, conditions de validité, débats",
}
EXPERIENCES = {"debutant": "débutants dans le domaine", "intermediaire": "ayant déjà une pratique",
               "confirme": "expérimentés : aller vite sur les bases, insister sur les nouveautés"}
# types de ressources → types de documents (fiche) et natures (Document.kind)
RESSOURCE_TYPES = {"resultats_rd": ["experimentation", "synthese"], "experimentation": ["experimentation"],
                   "temoignage": ["retour_experience"], "synthese": ["synthese"], "guide_technique": ["guide_technique"]}
RESSOURCE_KINDS = {"donnees": ["donnees"], "photo": ["image"], "video": ["video"], "audio": ["audio"]}
# préférences par profil et par public : bonus de score selon le type de document
PREFERENCES = {
    "conseiller": {"experimentation": 0.15}, "enseignant": {"synthese": 0.1, "guide_technique": 0.05},
    "chefs_entreprise": {"retour_experience": 0.15}, "salaries": {"guide_technique": 0.15},
    "apprentis": {"guide_technique": 0.1, "retour_experience": 0.1},
}


class Demande(BaseModel):
    # 0. le sujet
    sujet: str = Field(description="ce que le formateur veut traiter, en une phrase")
    # 1. profil du demandeur
    profil: Profil = "formateur"
    # 2. type de formation
    diplomante: bool = False
    diplome: str | None = None                       # id d'un référentiel (config/referentiels/<id>.yaml)
    capacites: list[str] = Field(default_factory=list)   # codes visés : C4, C4.2…
    modalite: Modalite = "presentiel"
    supports: list[Support] = Field(default_factory=lambda: ["ecrit"])
    duree_min: int = 120
    # 3. public cible
    apprenants: TypeApprenant = "etudiants"
    niveau: NiveauEtude = "bts"
    experience: Experience = "debutant"
    effectif: int | None = None
    # 4. types de ressources (vide = toutes)
    ressources: list[Ressource] = Field(default_factory=list)
    # 5. formes de résultat
    sorties: list[Sortie] = Field(default_factory=lambda: ["plan", "points_cles", "quiz", "glossaire", "cas_concret"])
    # 6. précisions sur les sources
    annee_min: int | None = None
    annee_max: int | None = None
    sources_publiques_seulement: bool = False
    region: str | None = None
    organismes: list[str] = Field(default_factory=list)       # sources à privilégier (bonus), pas un filtre
    nombre_sources: int = 30
    # 7. contenu personnel
    notes_personnelles: str = ""                              # texte du formateur, intégré au support
    fichiers_personnels: list[str] = Field(default_factory=list)   # dossiers ou fichiers (privés)
    autoriser_cloud_personnel: bool = False                   # contenu personnel vers un modèle en ligne : non par défaut

    # ------------------------------------------------------------------ dérivés
    def public_description(self) -> str:
        return (f"{APPRENANTS[self.apprenants]}, {NIVEAUX[self.niveau]}, {EXPERIENCES[self.experience]}"
                + (f", {self.effectif} personnes" if self.effectif else ""))

    def profil_description(self) -> str:
        return PROFILS[self.profil]

    def doc_types(self) -> list[str]:
        return sorted({t for r in self.ressources for t in RESSOURCE_TYPES.get(r, [])})

    def kinds(self) -> list[str]:
        k = sorted({t for r in self.ressources for t in RESSOURCE_KINDS.get(r, [])})
        return (k + ["pdf", "texte", "page"]) if k and self.doc_types() else k

    def type_bonus(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for key in (self.profil, self.apprenants):
            for t, b in PREFERENCES.get(key, {}).items():
                out[t] = out.get(t, 0) + b
        return out

    def filters(self):
        from sourcia.select.funnel import Filters

        return Filters(annee_min=self.annee_min, annee_max=self.annee_max, types=self.doc_types(), kinds=self.kinds(),
                       region=self.region, publiques_seulement=self.sources_publiques_seulement,
                       bonus_types=self.type_bonus(), bonus_organismes=self.organismes)

    def wants(self, sortie: str) -> bool:
        return sortie in self.sorties

    @classmethod
    def load(cls, path: Path) -> "Demande":
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")))

    def save(self, path: Path) -> Path:
        Path(path).write_text(yaml.safe_dump(self.model_dump(), allow_unicode=True, sort_keys=False), encoding="utf-8")
        return Path(path)
