"""Supports (étape 4) par l'API : la logique commune aux corpus du catalogue et aux corpus de dossier.

- corpus du catalogue (sans jeton, comme /api/formation) : routes ``/api/supports…`` dans app.py ;
- corpus de dossier (jeton, droit de lecture) : routes ``…/corpus-pedagogique/{cid}/supports…`` dans
  dossier_corpus.py.
Construction en tâche de fond (la fiche, le glossaire et le podcast prennent plusieurs minutes avec un vrai
modèle), ``statut.json`` dans ``<corpus>/supports/supports-<date>/``, une seule construction à la fois par corpus.
Le serveur tourne en UN processus : une liste en mémoire suffit ; après un redémarrage, une construction restée
« en_cours » est montrée en erreur (interrompue).
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sourcia.formation.corpus_pedagogique import load_corpus
from sourcia.formation.dossier_context import now, read_status, write_status
from sourcia.formation.supports import (SANS_MODELE, build_supports, chosen_sequences, new_supports_folder,
                                        write_supports)

logger = logging.getLogger(__name__)
SID_RE = re.compile(r"^supports-\d{8}-\d{6}(-\d+)?$")
FILES = {"supports.json": "application/json", "qcm_apprenants.md": "text/markdown", "qcm_corrige.md": "text/markdown",
         "qcm_moodle.gift.txt": "text/plain", "cartes_anki.csv": "text/csv", "cartes.html": "text/html",
         "infographie.html": "text/html", "fiche_technique.md": "text/markdown", "glossaire.md": "text/markdown",
         "podcast_script.md": "text/markdown",
         "presentation.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
NO_STORE = {"Cache-Control": "private, no-store"}
Support = Literal["qcm", "cartes", "presentation", "infographie", "fiche", "glossaire", "podcast"]


class SupportsRequest(BaseModel):
    sequences: list[int] | None = None               # numéros des séquences (défaut : toutes)
    supports: list[Support] = Field(default_factory=lambda: list(SANS_MODELE), min_length=1)
    avec_modele: bool = False                        # le modèle complète le QCM (questions contrôlées)
    qcm_par_sequence: int = Field(default=4, ge=1, le=10)


class CatalogueSupportsRequest(SupportsRequest):
    corpus_id: str                                   # corpus-<date> sous data/corpus/


def safe(base: Path, *parts: str) -> Path:
    p = Path(base).joinpath(*parts).resolve()
    if Path(base).resolve() not in p.parents or not p.is_file():
        raise HTTPException(404, "Fichier introuvable")
    return p


class SupportsJobs:
    def __init__(self, ctx):
        self.ctx = ctx
        self.running: set[str] = set()               # corpus dont des supports sont en construction
        self.lock = threading.Lock()

    def start(self, corpus_dir: Path, req: SupportsRequest, tasks, by: str) -> dict:
        if read_status(corpus_dir).get("statut") in ("en_cours", "erreur") or not (corpus_dir / "corpus.json").is_file():
            raise HTTPException(409, "Ce corpus n'est pas prêt : attendez la fin de sa construction")
        cp = load_corpus(corpus_dir)
        try:
            seqs = chosen_sequences(cp, req.sequences)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        key = str(corpus_dir.resolve())
        with self.lock:
            if key in self.running:
                raise HTTPException(409, "Des supports sont déjà en construction pour ce corpus")
            self.running.add(key)
        try:
            folder = new_supports_folder(corpus_dir)
            write_status(folder, id=folder.name, statut="en_cours", cree_le=now(), sequences=seqs,
                         supports=list(dict.fromkeys(req.supports)), demande_par=by)
        except Exception:
            with self.lock:
                self.running.discard(key)
            raise
        tasks.add_task(self.run, key, corpus_dir, folder, req)
        return {"id": folder.name, "statut": "en_cours"}

    def run(self, key: str, corpus_dir: Path, folder: Path, req: SupportsRequest) -> None:
        try:
            cp = load_corpus(corpus_dir)
            sup = build_supports(cp, req.sequences, req.supports, ctx=self.ctx, avec_modele=req.avec_modele,
                                 qcm_par_sequence=req.qcm_par_sequence)
            write_supports(sup, cp, corpus_dir, folder=folder)
            write_status(folder, statut="pret", termine_le=now(), fichiers=sup.fichiers, questions=len(sup.qcm),
                         cartes=len(sup.cartes), remarques=sup.remarques[:10], appels_modele=sup.appels_modele)
        except Exception as exc:
            logger.exception("Échec des supports %s", folder)
            write_status(folder, statut="erreur", termine_le=now(), erreur=f"{type(exc).__name__} : {str(exc)[:300]}")
        finally:
            with self.lock:
                self.running.discard(key)

    def _status(self, corpus_dir: Path, folder: Path) -> dict:
        st = read_status(folder)
        if st.get("statut") == "en_cours" and str(corpus_dir.resolve()) not in self.running:
            st = st | {"statut": "erreur", "erreur": "construction interrompue (serveur arrêté) : relancez-la"}
        return st

    def folder(self, corpus_dir: Path, sid: str) -> Path:
        folder = corpus_dir / "supports" / sid
        if not SID_RE.match(sid) or not folder.is_dir():
            raise HTTPException(404, "Supports introuvables")
        return folder

    def list(self, corpus_dir: Path) -> list[dict]:
        root = corpus_dir / "supports"
        folders = [f for f in root.glob("supports-*") if f.is_dir() and SID_RE.match(f.name)] if root.exists() else []
        return [self._status(corpus_dir, f) for f in sorted(folders, key=lambda f: f.name, reverse=True)]

    def status(self, corpus_dir: Path, sid: str) -> dict:
        return self._status(corpus_dir, self.folder(corpus_dir, sid))

    def file(self, corpus_dir: Path, sid: str, name: str) -> FileResponse:
        if name not in FILES:
            raise HTTPException(404, "Fichier introuvable")
        return FileResponse(safe(self.folder(corpus_dir, sid), name), media_type=FILES[name], filename=name,
                            headers=NO_STORE)
