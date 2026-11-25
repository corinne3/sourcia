"""Compte de démonstration (pour le jury, une présentation) : ``sourcia comptes demo``.

Crée (ou renouvelle) le compte ``demo@sourcia.local`` et lui prépare un dossier déjà rempli avec quelques
documents PUBLICS du catalogue sur un sujet, traités et cochés : on peut construire un corpus tout de suite.
Rien n'existe tant que l'administrateur ne lance pas cette commande ; ``sourcia comptes retirer
demo@sourcia.local`` le supprime. Le dossier reste visible seulement avec le jeton de démonstration.
"""
from __future__ import annotations

import uuid

from sourcia.comptes import DEMO_EMAIL, Comptes
from sourcia.core.models import Document


def create_demo(ctx, sujet: str = "sorgho fourrager", n: int = 4, log=lambda *a: None) -> tuple[str, str, list[dict]]:
    """Renvoie (jeton, identifiant du dossier, documents avec leur état)."""
    from sourcia.api.dossiers import Dossiers

    picked, seen = [], set()
    for hit in ctx.index.search(sujet, k=40):
        doc = ctx.store.get(hit.doc_id)
        if doc and not doc.private and doc.id not in seen:
            seen.add(doc.id)
            picked.append(doc)
        if len(picked) >= n:
            break
    if not picked:
        raise ValueError(f"Aucun document public du catalogue sur « {sujet} » : chargez d'abord un catalogue "
                         "(sourcia demo, ou sourcia collect-sites puis sourcia index).")
    token = Comptes(ctx.settings.path("comptes.json")).ajouter(DEMO_EMAIL, remplacer=True, demo=True)
    store = Dossiers(ctx)
    folder_id = uuid.uuid4().hex
    copies = []
    with store.db(write=True) as db:
        db.execute("INSERT INTO folders (id, title, owner) VALUES (?, ?, ?)", (folder_id, f"Démo : {sujet}", DEMO_EMAIL))
        for source in picked:                        # même copie que l'ajout depuis le catalogue (api/dossiers.py)
            copy = source.model_copy(update={"id": uuid.uuid4().hex, "error": None})
            db.execute("INSERT INTO documents (id, folder, catalog_id, payload) VALUES (?, ?, ?, ?)",
                       (copy.id, folder_id, source.id, copy.model_dump_json()))
            copies.append(copy)
    for copy in copies:
        log(f"  traitement : {copy.title}")
        store.process(copy.id)                       # téléchargement si besoin, extraction, fiche, index
    with store.db() as db:
        rows = store.list_documents(db, folder_id)
    return token, folder_id, [{"titre": Document.model_validate_json(r["payload"]).title, "statut": r["status"]}
                              for r in rows]
