"""Corpus pédagogique à partir d'un DOSSIER ENSEIGNANT (étape 2 → étape 3).

``build_corpus`` a été écrit pour le catalogue : il lit ``ctx.store``, ``ctx.qualifier``, ``ctx.text_of``,
``ctx.settings``, ``ctx.llm`` et ``ctx.embedder``. ``DossierContext`` sert les mêmes choses, mais pour les
documents d'un dossier (``api/dossiers.py``) :
- ``store`` : un magasin EN MÉMOIRE (jamais enregistré) avec les documents COCHÉS et PRÊTS du dossier ;
- ``qualifier.get`` : la fiche rangée dans la colonne ``fiche`` de la base des dossiers ;
- ``text_of`` : le texte, rangé par document dans ``data/dossiers/<id>/text/<id>.json`` ;
- ``settings``, ``llm``, ``embedder`` : ceux du contexte normal.

Un document venu du catalogue garde son adresse (et ``meta["catalog_id"]``) ; un PDF téléversé est marqué
``meta[FOURNI]`` : cité « Document fourni par le formateur », sans lien, et ses images peuvent être reprises.
Ce module n'importe pas FastAPI : l'API et la ligne de commande s'en servent toutes les deux.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sourcia.collect.store import DocumentStore
from sourcia.core.demande import Demande
from sourcia.core.models import Document, Fiche
from sourcia.extract.pdf import load_text
from sourcia.formation.corpus_pedagogique import (FOURNI, CorpusPedagogique, build_corpus, new_corpus_folder,
                                                  write_corpus)

STATUS_FILE = "statut.json"


class _Fiches:
    """Le seul service du « qualifier » dont le corpus a besoin : ``get(doc_id)``."""

    def __init__(self, fiches: dict[str, Fiche]):
        self.fiches = fiches

    def get(self, doc_id: str) -> Fiche | None:
        return self.fiches.get(doc_id)


class DossierContext:
    def __init__(self, ctx, dossiers, folder_id: str):
        self.ctx = ctx
        self.dossiers = dossiers
        self.folder_id = folder_id
        self.settings = ctx.settings
        # magasin en mémoire : le chemin ne sert qu'à le créer (il n'existe pas et n'est jamais écrit)
        self.store = DocumentStore(corpus_root(dossiers, folder_id) / "documents-en-memoire.jsonl")
        fiches: dict[str, Fiche] = {}
        self.not_ready: list[str] = []               # cochés mais pas encore prêts (ou en erreur)
        with dossiers.db() as db:
            rows = dossiers.list_documents(db, folder_id, selected=True)
        for row in rows:
            doc = Document.model_validate_json(row["payload"])
            if row["status"] != "pret":
                self.not_ready.append(doc.title or doc.id)
                continue
            if row["catalog_id"]:
                doc.meta["catalog_id"] = row["catalog_id"]
            else:
                doc.meta[FOURNI] = True              # PDF téléversé par le formateur
            self.store.docs[doc.id] = doc
            if row["fiche"]:
                fiches[doc.id] = Fiche.model_validate_json(row["fiche"])
        self.qualifier = _Fiches(fiches)

    @property
    def doc_ids(self) -> list[str]:
        """Les documents cochés et prêts, dans l'ordre du dossier."""
        return list(self.store.docs)

    @property
    def llm(self):
        return self.ctx.llm

    @property
    def embedder(self):
        return self.ctx.embedder

    def text_of(self, doc_id: str) -> dict | None:
        """Texte d'un document du dossier : ``Dossiers.settings(id)`` pointe sur ``data/dossiers/<id>``."""
        return load_text(doc_id, self.dossiers.settings(doc_id).data / "text")


# ---------------------------------------------------------------------- rangement et statut
def corpus_root(dossiers, folder_id: str) -> Path:
    """Les corpus d'un dossier : ``data/dossiers/corpus/<folder_id>/corpus-<date>/``."""
    return Path(dossiers.root) / "corpus" / folder_id


def read_status(folder: Path) -> dict:
    p = Path(folder) / STATUS_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"id": Path(folder).name}


def write_status(folder: Path, **fields) -> dict:
    """Complète ``statut.json`` (id, statut en_cours/pret/erreur, dates, sujet, nombre de documents…)."""
    data = read_status(folder) | fields
    (Path(folder) / STATUS_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def mark_ready(folder: Path, cp: CorpusPedagogique, **fields) -> dict:
    """Statut « pret » d'un corpus construit (API ou ligne de commande)."""
    return write_status(folder, id=Path(folder).name, statut="pret", termine_le=now(), sujet=cp.demande.sujet,
                        documents=len(cp.doc_ids), exclus_prives=cp.exclus_prives,
                        illustrations=len(cp.illustrations), appels_modele=cp.appels_modele, **fields)


# ---------------------------------------------------------------------- construction
def build_dossier_corpus(ctx, dossiers, folder_id: str, demande: Demande, *, sequences: int = 4,
                         autoriser_documents_prives: bool = False, max_illustrations: int = 12,
                         folder: Path | None = None, log=lambda *a: None) -> tuple[CorpusPedagogique, list[Path]]:
    """Construit, écrit (corpus.json, demande.yaml, illustrations, Word) et renvoie le corpus d'un dossier.

    ``autoriser_documents_prives`` : accord EXPLICITE pour envoyer les documents privés (PDF téléversés) à un
    modèle en ligne ; sans lui, ils sont exclus avec un modèle en ligne et listés dans ``exclus_prives``."""
    dctx = DossierContext(ctx, dossiers, folder_id)
    if not dctx.doc_ids:
        raise ValueError("Aucun document coché et prêt dans ce dossier : cochez des documents et attendez la fin "
                         "de leur traitement")
    if autoriser_documents_prives:
        demande = demande.model_copy(update={"autoriser_cloud_personnel": True})
    cp = build_corpus(dctx, demande, dctx.doc_ids, n_seq=sequences, log=log)
    cp.dossier_id = folder_id
    cp.remarques += [f"document coché mais pas encore prêt, laissé de côté : « {t} »" for t in dctx.not_ready]
    folder = folder if folder is not None else new_corpus_folder(corpus_root(dossiers, folder_id))
    paths = write_corpus(cp, folder.parent, ctx=dctx if max_illustrations > 0 else None,
                         max_illustrations=max_illustrations, folder=folder)
    try:
        from sourcia.formation.export_word import corpus_to_docx

        paths.append(corpus_to_docx(cp, folder / "corpus_pedagogique.docx"))
    except Exception as exc:                         # corpus.json est écrit : le Word pourra être refait
        write_status(folder, avertissement=f"document Word non produit ({type(exc).__name__} : {str(exc)[:200]})")
    return cp, paths
