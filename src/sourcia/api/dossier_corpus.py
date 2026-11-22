"""Corpus pédagogique d'un dossier enseignant (étape 3), routes ajoutées au routeur des dossiers.

Mêmes jetons et mêmes droits que les dossiers ; le droit de LECTURE suffit.
- ``POST /api/dossiers/{id}/corpus-pedagogique``           : lance la construction (tâche de fond), renvoie l'id
- ``GET  /api/dossiers/{id}/corpus-pedagogique``           : les corpus du dossier, avec leur statut
- ``GET  /api/dossiers/{id}/corpus-pedagogique/{cid}``     : le statut d'un corpus (pour suivre la construction)
- ``GET  /api/dossiers/{id}/corpus-pedagogique/{cid}/corpus.json`` (ou ``corpus_pedagogique.docx``, ``demande.yaml``)
- ``GET  /api/dossiers/{id}/corpus-pedagogique/{cid}/illustrations/{fichier}``

Rangement : ``data/dossiers/corpus/<folder_id>/corpus-<date>/`` (corpus.json, Word, illustrations, statut.json).
Une seule construction à la fois par dossier. Le serveur tourne en UN processus (SQLite, tâches de fond) : une
liste en mémoire suffit ; après un redémarrage, un corpus resté « en_cours » est montré en erreur (interrompu).
La route existante ``GET /api/dossiers/{id}/corpus`` (documents cochés + texte) ne change pas.
"""
from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

from fastapi import BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from sourcia.core.demande import Demande
from sourcia.formation.corpus_pedagogique import new_corpus_folder
from sourcia.formation.dossier_context import (build_dossier_corpus, corpus_root, mark_ready, now, read_status,
                                               write_status)

logger = logging.getLogger(__name__)
CID_RE = re.compile(r"^corpus-\d{8}-\d{6}(-\d+)?$")
FILES = {"corpus.json": "application/json",
         "corpus_pedagogique.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         "demande.yaml": "text/yaml"}
NO_STORE = {"Cache-Control": "private, no-store"}


class CorpusRequest(BaseModel):
    demande: Demande
    sequences: int = Field(default=4, ge=1, le=12)
    autoriser_documents_prives: bool = False         # accord explicite : PDF téléversés vers un modèle en ligne
    max_illustrations: int = Field(default=12, ge=0, le=40)


def safe(base: Path, *parts: str) -> Path:
    """Chemin sous ``base`` seulement (pas de « ../ »), et existant ; sinon 404 (même principe que app.py)."""
    p = Path(base).joinpath(*parts).resolve()
    if Path(base).resolve() not in p.parents or not p.is_file():
        raise HTTPException(404, "Fichier introuvable")
    return p


def add_corpus_routes(router, ctx, store, identity) -> None:
    """``store`` : les Dossiers (api/dossiers.py) ; ``identity`` : la dépendance qui vérifie le jeton."""
    running: set[str] = set()                        # dossiers dont un corpus est en construction
    lock = threading.Lock()

    def readable(folder_id: str, email: str) -> None:
        with store.db() as db:
            store.folder(db, folder_id, email)       # 404 si le dossier n'est pas à lui ni partagé avec lui

    def corpus_folder(folder_id: str, cid: str) -> Path:
        folder = corpus_root(store, folder_id) / cid
        if not CID_RE.match(cid) or not folder.is_dir():
            raise HTTPException(404, "Corpus introuvable")
        return folder

    def status(folder_id: str, folder: Path) -> dict:
        st = read_status(folder)
        if st.get("statut") == "en_cours" and folder_id not in running:
            st = st | {"statut": "erreur", "erreur": "construction interrompue (serveur arrêté) : relancez-la"}
        return st

    def run(folder_id: str, folder: Path, req: CorpusRequest) -> None:
        try:
            cp, _ = build_dossier_corpus(ctx, store, folder_id, req.demande, sequences=req.sequences,
                                         autoriser_documents_prives=req.autoriser_documents_prives,
                                         max_illustrations=req.max_illustrations, folder=folder)
            mark_ready(folder, cp)
        except Exception as exc:
            logger.exception("Échec du corpus %s du dossier %s", folder.name, folder_id)
            write_status(folder, statut="erreur", termine_le=now(), erreur=f"{type(exc).__name__} : {str(exc)[:300]}")
        finally:
            with lock:
                running.discard(folder_id)

    @router.post("/{folder_id}/corpus-pedagogique", status_code=202)
    def start_corpus(folder_id: str, req: CorpusRequest, tasks: BackgroundTasks, email: str = Depends(identity)):
        if not req.demande.sujet.strip():
            raise HTTPException(422, "Le sujet de la demande est vide")
        with store.db() as db:
            store.folder(db, folder_id, email)
            ready = [r for r in store.list_documents(db, folder_id, selected=True) if r["status"] == "pret"]
        if not ready:
            raise HTTPException(409, "Aucun document coché et prêt dans ce dossier : cochez des documents et "
                                     "attendez la fin de leur traitement")
        with lock:
            if folder_id in running:
                raise HTTPException(409, "Un corpus est déjà en construction pour ce dossier")
            running.add(folder_id)
        try:
            folder = new_corpus_folder(corpus_root(store, folder_id))
            write_status(folder, id=folder.name, statut="en_cours", cree_le=now(), sujet=req.demande.sujet,
                         demande_par=email, documents=len(ready))
        except Exception:
            with lock:
                running.discard(folder_id)
            raise
        tasks.add_task(run, folder_id, folder, req)
        return {"id": folder.name, "statut": "en_cours"}

    @router.get("/{folder_id}/corpus-pedagogique")
    def list_corpus(folder_id: str, email: str = Depends(identity)):
        readable(folder_id, email)
        root = corpus_root(store, folder_id)
        folders = [f for f in root.glob("corpus-*") if f.is_dir() and CID_RE.match(f.name)] if root.exists() else []
        return [status(folder_id, f) for f in sorted(folders, key=lambda f: f.name, reverse=True)]

    @router.get("/{folder_id}/corpus-pedagogique/{cid}")
    def corpus_status(folder_id: str, cid: str, email: str = Depends(identity)):
        readable(folder_id, email)
        return status(folder_id, corpus_folder(folder_id, cid))

    @router.get("/{folder_id}/corpus-pedagogique/{cid}/illustrations/{name}")
    def corpus_image(folder_id: str, cid: str, name: str, email: str = Depends(identity)):
        readable(folder_id, email)
        folder = corpus_folder(folder_id, cid)
        return FileResponse(safe(folder / "illustrations", name), headers=NO_STORE)

    @router.get("/{folder_id}/corpus-pedagogique/{cid}/{name}")
    def corpus_file(folder_id: str, cid: str, name: str, email: str = Depends(identity)):
        readable(folder_id, email)
        if name not in FILES:
            raise HTTPException(404, "Fichier introuvable")
        return FileResponse(safe(corpus_folder(folder_id, cid), name), media_type=FILES[name], filename=name,
                            headers=NO_STORE)
