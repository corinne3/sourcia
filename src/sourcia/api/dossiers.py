"""Dossiers enseignants isolés du catalogue et des exports historiques."""
from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from sourcia.collect.store import file_sha1
from sourcia.collect.web import WebCollector
from sourcia.core.models import Candidate, Document, Fiche
from sourcia.core.text import normalize
from sourcia.export.exporters import export
from sourcia.extract.pdf import extract, load_text
from sourcia.qualify.pipeline import Qualifier
from sourcia.search.index import SearchIndex

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)
MAX_UPLOAD = 25_000_000


class NewFolder(BaseModel):
    title: str = Field(default="", max_length=200)


class CatalogResource(BaseModel):
    document_id: str = Field(min_length=1, max_length=200)


class Selection(BaseModel):
    selected: bool


class Sharing(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["lecture", "modification"] | None


class Dossiers:
    def __init__(self, ctx):
        self.ctx = ctx
        self.root = ctx.settings.path("dossiers", ".keep").parent
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS folders (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, owner TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS shares (
                    folder TEXT REFERENCES folders(id), email TEXT, role TEXT NOT NULL,
                    PRIMARY KEY (folder, email)
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, folder TEXT REFERENCES folders(id), catalog_id TEXT,
                    payload TEXT NOT NULL, fiche TEXT, selected INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'en_attente', error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE (folder, catalog_id)
                );
            """)

    @contextmanager
    def db(self, *, write=False):
        db = sqlite3.connect(self.root / "dossiers.sqlite3")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                yield db
        finally:
            db.close()

    def folder(self, db, folder_id, email, *, write=False, owner=False):
        row = db.execute("""
            SELECT f.*, CASE WHEN f.owner = ? THEN 'proprietaire' ELSE s.role END AS role
            FROM folders f LEFT JOIN shares s ON s.folder = f.id AND s.email = ?
            WHERE f.id = ? AND (f.owner = ? OR s.email IS NOT NULL)
        """, (email, email, folder_id, email)).fetchone()
        if row is None:
            raise HTTPException(404, "Dossier introuvable")
        if (owner and row["role"] != "proprietaire") or (write and row["role"] == "lecture"):
            raise HTTPException(403, "Droits insuffisants")
        return row

    def settings(self, document_id):
        return self.ctx.settings.model_copy(update={"data_dir": str(self.root / document_id)})

    def document(self, db, folder_id, document_id):
        row = db.execute("SELECT * FROM documents WHERE folder = ? AND id = ?",
                         (folder_id, document_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Document introuvable")
        return row

    def list_documents(self, db, folder_id, selected=False):
        return db.execute("""
            SELECT * FROM documents WHERE folder = ? AND (? = 0 OR selected = 1)
            ORDER BY created_at, id
        """, (folder_id, selected)).fetchall()

    def process(self, document_id):
        # Ce verrou est propre au document et libéré même si le serveur s'arrête.
        lock = sqlite3.connect(self.settings(document_id).data / "traitement.sqlite3", timeout=0)
        try:
            try:
                lock.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                if getattr(error, "sqlite_errorcode", None) == getattr(sqlite3, "SQLITE_BUSY", 5) or str(error) == "database is locked":
                    return
                raise
            self.process_locked(document_id)
        finally:
            lock.close()

    def process_locked(self, document_id):
        with self.db() as db:
            claimed = db.execute("""
                UPDATE documents SET status = 'traitement', error = NULL
                WHERE id = ? AND status IN ('en_attente', 'erreur', 'traitement')
                RETURNING payload, catalog_id
            """, (document_id,)).fetchone()
        if not claimed:
            return
        try:
            doc = Document.model_validate_json(claimed["payload"])
            settings = self.settings(document_id)
            if claimed["catalog_id"] and not doc.local_path:
                collector = WebCollector(settings)
                if doc.kind == "pdf":
                    collector.download(doc, settings.data)
                    if not doc.local_path:
                        raise ValueError(doc.error or "Téléchargement PDF désactivé")
                elif doc.kind == "page":
                    response = collector.get(doc.url)
                    response.raise_for_status()
                    if "html" not in response.headers.get("Content-Type", "").lower():
                        raise ValueError("La ressource ne contient pas de page HTML")
                    if len(response.content) > MAX_UPLOAD:
                        raise ValueError("La page est trop volumineuse")
                    path = settings.data / "source.html"
                    path.write_bytes(response.content)
                    doc.local_path = str(path)
            if doc.local_path:
                source = Path(doc.local_path)
                target = settings.data / ("source" + source.suffix.lower())
                if source != target:
                    shutil.copyfile(source, target)
                doc.local_path = str(target)
                doc.sha1 = file_sha1(target)
            result = extract(doc, settings.path("text", ".keep").parent, settings.extract.max_pages)
            if not any(page.strip() for page in result["pages"]):
                raise ValueError("Aucun texte exploitable")
            doc.meta.update({"pages": result["n_pages"]})
            if doc.local_path:
                doc.meta["taille_octets"] = Path(doc.local_path).stat().st_size
            author = result["meta"].get("author")
            if author:
                doc.meta["auteur"] = author
            fiche = Qualifier(settings).qualify(doc)
            if not fiche.resume:
                first_page = next(page.strip() for page in result["pages"] if page.strip())
                fiche.resume = " ".join(first_page.split()[:45])
            SearchIndex(settings).build([doc])
            with self.db() as db:
                db.execute("UPDATE documents SET payload = ?, fiche = ?, status = 'pret' WHERE id = ?",
                           (doc.model_dump_json(), fiche.model_dump_json(), document_id))
        except Exception:
            logger.exception("Échec du traitement du document %s", document_id)
            with self.db() as db:
                db.execute("UPDATE documents SET status = 'erreur', error = ? WHERE id = ?",
                           ("Téléchargement ou indexation impossible. Vérifiez la source avant de réessayer.", document_id))


def serialize(row):
    doc = Document.model_validate_json(row["payload"])
    fiche = Fiche.model_validate_json(row["fiche"]) if row["fiche"] else None
    return {
        "id": doc.id, "title": doc.title, "source": doc.source, "kind": doc.kind,
        "url": None if doc.private else doc.url, "private": doc.private, "date": doc.date,
        "metadata": {k: doc.meta[k] for k in ("pages", "taille_octets", "auteur", "metadonnees_seules") if k in doc.meta},
        "keywords": doc.keywords, "selected": bool(row["selected"]), "status": row["status"],
        "error": row["error"], "fiche": fiche.model_dump() if fiche else None,
    }


def create_dossiers_router(ctx):
    router = APIRouter(prefix="/api/dossiers", tags=["Dossiers"])
    accounts = json.loads(os.environ.get("SOURCIA_DOSSIER_ACCOUNTS", "{}"))
    if (not isinstance(accounts, dict)
            or any(not isinstance(token, str) or not token.isascii() or len(token) < 32 for token in accounts.values())
            or len(set(accounts.values())) != len(accounts)):
        raise ValueError("SOURCIA_DOSSIER_ACCOUNTS doit associer chaque adresse à un jeton ASCII unique d'au moins 32 caractères.")
    normalized_accounts = {email.strip().casefold(): token for email, token in accounts.items()}
    if len(normalized_accounts) != len(accounts) or any("@" not in email or any(c.isspace() for c in email)
                                                       for email in normalized_accounts):
        raise ValueError("Adresses de comptes SourcIA invalides ou en double.")
    store = Dossiers(ctx)

    def identity(response: Response, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        response.headers["Cache-Control"] = "private, no-store"
        if credentials:
            supplied = credentials.credentials.encode()
            for email, token in normalized_accounts.items():
                if secrets.compare_digest(supplied, token.encode()):
                    return email
        raise HTTPException(401, "Jeton enseignant requis", headers={"WWW-Authenticate": "Bearer"})

    @router.get("")
    def folders(email: str = Depends(identity)):
        with store.db() as db:
            return [dict(row) for row in db.execute("""
                SELECT f.id, f.title, f.created_at,
                    CASE WHEN f.owner = ? THEN 'proprietaire' ELSE s.role END AS role
                FROM folders f LEFT JOIN shares s ON s.folder = f.id AND s.email = ?
                WHERE f.owner = ? OR s.email IS NOT NULL ORDER BY f.created_at DESC, f.id
            """, (email, email, email))]

    @router.post("", status_code=201)
    def new_folder(req: NewFolder, email: str = Depends(identity)):
        folder_id = uuid.uuid4().hex
        title = req.title.strip() or f"Dossier pédagogique {folder_id[:6]}"
        with store.db() as db:
            db.execute("INSERT INTO folders (id, title, owner) VALUES (?, ?, ?)", (folder_id, title, email))
        return {"id": folder_id, "title": title, "role": "proprietaire"}

    @router.get("/{folder_id}")
    def detail(folder_id: str, q: str = "", kind: str = "", status: str = "",
               sort: Literal["ajout", "titre", "date"] = "ajout", email: str = Depends(identity)):
        with store.db() as db:
            folder = store.folder(db, folder_id, email)
            docs = [serialize(row) for row in store.list_documents(db, folder_id)]
            shares = ([dict(row) for row in db.execute("SELECT email, role FROM shares WHERE folder = ?", (folder_id,))]
                      if folder["role"] == "proprietaire" else [])
        query = normalize(q)
        result = []
        for doc in docs:
            if (kind and doc["kind"] != kind) or (status and doc["status"] != status):
                continue
            if query and not all(word in normalize(json.dumps(doc, ensure_ascii=False)) for word in query.split()):
                if doc["status"] != "pret":
                    continue
                index = SearchIndex(store.settings(doc["id"]))
                if not index.load() or not index.bm25.search(q, 1):
                    continue
            result.append(doc)
        if sort == "titre":
            result.sort(key=lambda doc: normalize(doc["title"]))
        elif sort == "date":
            result.sort(key=lambda doc: doc["date"] or "", reverse=True)
        notification = None
        if docs and all(doc["status"] in ("pret", "erreur") for doc in docs):
            errors = sum(doc["status"] == "erreur" for doc in docs)
            notification = f"Traitement terminé. {len(docs) - errors} document(s) prêt(s), {errors} en erreur."
        selected = [doc for doc in docs if doc["selected"]]
        return {"id": folder_id, "title": folder["title"], "role": folder["role"], "documents": result,
                "export_disponible": bool(selected) and all(doc["status"] == "pret" for doc in selected),
                "shares": shares, "notification": notification,
                "en_cours": any(doc["status"] in ("en_attente", "traitement") for doc in docs)}

    @router.get("/{folder_id}/recherche-catalogue")
    def catalog_search(folder_id: str, q: str, email: str = Depends(identity)):
        with store.db() as db:
            store.folder(db, folder_id, email)
        hits = []
        for hit in ctx.index.search(q, k=30):
            doc = ctx.store.get(hit.doc_id)
            if doc and not doc.private:
                hits.append({"id": doc.id, "titre": doc.title, "source": doc.source})
        return hits

    @router.post("/{folder_id}/catalogue", status_code=202)
    def add_catalog(folder_id: str, req: CatalogResource, tasks: BackgroundTasks, email: str = Depends(identity)):
        with store.db(write=True) as db:
            store.folder(db, folder_id, email, write=True)
            source = ctx.store.get(req.document_id)
            if not source or source.private:
                raise HTTPException(404, "Ressource publique introuvable")
            document = source.model_copy(update={"id": uuid.uuid4().hex, "error": None})
            try:
                db.execute("INSERT INTO documents (id, folder, catalog_id, payload) VALUES (?, ?, ?, ?)",
                           (document.id, folder_id, source.id, document.model_dump_json()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "Cette ressource figure déjà dans le dossier")
        tasks.add_task(store.process, document.id)
        return {"id": document.id, "status": "en_attente"}

    @router.post("/{folder_id}/documents", status_code=202)
    def upload(folder_id: str, tasks: BackgroundTasks, file: UploadFile = File(...), email: str = Depends(identity)):
        with store.db() as db:
            store.folder(db, folder_id, email, write=True)
        filename = Path((file.filename or "").replace("\\", "/")).name
        if not filename.lower().endswith(".pdf") or not file.file.read(5).startswith(b"%PDF-"):
            raise HTTPException(415, "Un fichier PDF est attendu")
        file.file.seek(0)
        content = file.file.read(MAX_UPLOAD + 1)
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "Le PDF dépasse 25 Mo")
        document_id = uuid.uuid4().hex
        path = store.settings(document_id).data / "source.pdf"
        document = Document(id=document_id, title=filename[:-4][:200], url="", source="prive", private=True,
                            local_path=str(path), status="downloaded")
        try:
            path.write_bytes(content)
            with store.db(write=True) as db:
                store.folder(db, folder_id, email, write=True)
                db.execute("INSERT INTO documents (id, folder, payload) VALUES (?, ?, ?)",
                           (document_id, folder_id, document.model_dump_json()))
        except Exception:
            shutil.rmtree(path.parent, ignore_errors=True)
            raise
        tasks.add_task(store.process, document_id)
        return {"id": document_id, "status": "en_attente"}

    @router.patch("/{folder_id}/documents/{document_id}")
    def select(folder_id: str, document_id: str, req: Selection, email: str = Depends(identity)):
        with store.db(write=True) as db:
            store.folder(db, folder_id, email, write=True)
            store.document(db, folder_id, document_id)
            db.execute("UPDATE documents SET selected = ? WHERE id = ?", (req.selected, document_id))
        return req

    @router.post("/{folder_id}/documents/{document_id}/reessayer", status_code=202)
    def retry(folder_id: str, document_id: str, tasks: BackgroundTasks, email: str = Depends(identity)):
        with store.db() as db:
            store.folder(db, folder_id, email, write=True)
            doc = store.document(db, folder_id, document_id)
            if doc["status"] == "pret":
                raise HTTPException(409, "Le document est déjà prêt")
        tasks.add_task(store.process, document_id)
        return {"id": document_id}

    @router.put("/{folder_id}/partages")
    def share(folder_id: str, req: Sharing, email: str = Depends(identity)):
        recipient = req.email.strip().casefold()
        if recipient == email or "@" not in recipient or any(c.isspace() for c in recipient):
            raise HTTPException(422, "Adresse de partage invalide")
        with store.db(write=True) as db:
            store.folder(db, folder_id, email, owner=True)
            if req.role:
                db.execute("""INSERT INTO shares VALUES (?, ?, ?)
                              ON CONFLICT(folder, email) DO UPDATE SET role=excluded.role""",
                           (folder_id, recipient, req.role))
            else:
                db.execute("DELETE FROM shares WHERE folder = ? AND email = ?", (folder_id, recipient))
        return {"email": recipient, "role": req.role}

    def selected_documents(folder_id, email):
        with store.db() as db:
            store.folder(db, folder_id, email)
            return store.list_documents(db, folder_id, selected=True)

    @router.get("/{folder_id}/corpus")
    def corpus(folder_id: str, texte: bool = True, email: str = Depends(identity)):
        documents = []
        for row in selected_documents(folder_id, email):
            if row["status"] != "pret":
                continue
            document = serialize(row)
            if texte:
                data = load_text(row["id"], store.settings(row["id"]).path("text", ".keep").parent)
                document["pages"] = [{"numero": i, "texte": page}
                                     for i, page in enumerate(data["pages"] if data else [], 1)]
            documents.append(document)
        return {"documents": documents}

    @router.get("/{folder_id}/export.zip")
    def download(folder_id: str, email: str = Depends(identity)):
        from tempfile import TemporaryDirectory

        rows = selected_documents(folder_id, email)
        if not rows or any(row["status"] != "pret" for row in rows):
            raise HTTPException(409, "Sélectionnez des documents prêts pour créer le ZIP")
        candidates = []
        for row in rows:
            doc = Document.model_validate_json(row["payload"])
            fiche = Fiche.model_validate_json(row["fiche"])
            candidates.append(Candidate(doc, fiche))
        originals = [item for item in candidates if item.document.kind != "video"]
        archive_paths = {}
        for number, item in enumerate(originals, 1):
            if item.document.local_path:
                archive_paths[item.document.id] = f"{number:02d}-{Path(item.document.local_path).name}"
        temp = TemporaryDirectory()
        try:
            path, = export(originals, "", Path(temp.name), formats=("zip",))
            with zipfile.ZipFile(path, "a", zipfile.ZIP_DEFLATED) as archive:
                for row in rows:
                    summary = serialize(row)
                    doc_id = row["id"]
                    summary["fichier_archive"] = archive_paths.get(doc_id)
                    archive.writestr(f"fiches/{doc_id}.json", json.dumps(summary, ensure_ascii=False, indent=2))
                    if summary["kind"] == "video" and not summary["metadata"].get("metadonnees_seules"):
                        data = load_text(doc_id, store.settings(doc_id).path("text", ".keep").parent)
                        if data:
                            archive.writestr(f"transcriptions/{doc_id}.txt", "\n\n".join(data["pages"]))
        except Exception:
            temp.cleanup()
            raise
        return FileResponse(path, media_type="application/zip", filename="corpus.zip",
                            headers={"Cache-Control": "private, no-store"},
                            background=BackgroundTask(temp.cleanup))

    from sourcia.api.dossier_corpus import add_corpus_routes   # corpus pédagogique du dossier (étape 3)

    add_corpus_routes(router, ctx, store, identity)
    return router
