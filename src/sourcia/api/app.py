"""API et page web du formateur (M6).

- ``GET  /``                              : la page (formulaire des 7 critères, sources justifiées, formation)
- ``GET  /api/etat``                      : documents, fiches, configuration
- ``GET  /api/referentiels``              : diplômes disponibles et leurs capacités (M8)
- ``POST /api/selection``                 : sélection pilotée par la demande structurée (M0 → M5)
- ``GET  /api/recherche``                 : recherche simple (M4)
- ``GET  /api/fiche/{id}``                : fiche de qualification avec preuves (M3)
- ``GET  /api/export/{fichier}``          : télécharger un export
- ``POST /api/formation``                 : créer le support de formation (M7)
- ``GET  /api/formation/{dossier}/{f}``   : télécharger un fichier de la formation
- ``POST /api/formation/{dossier}/rattachements`` : l'enseignant valide les rattachements (M8)
- ``POST /api/supports``                  : supports (étape 4) d'un corpus du catalogue, en tâche de fond
- ``GET  /api/supports/{corpus}[/{sid}[/{f}]]`` : liste, statut, fichiers des supports

Mode serveur (``serveur: true``, config/serveur.yaml) : ce qui appelle le modèle ou écrit sur le disque demande un
enseignant connecté (cookie de session ou jeton) ; chercher dans le catalogue reste ouvert à tous, sans export ni
passe du modèle. Le serveur ne démarre pas sans SOURCIA_SESSION_SECRET.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

from sourcia import BUILD
# au niveau du module : FastAPI lit les annotations (texte, à cause de « annotations ») dans ce module
from sourcia.api.dossier_corpus import CID_RE
from sourcia.api.dossiers import bearer, create_dossiers_router
from sourcia.api.supports_api import CatalogueSupportsRequest, SupportsJobs
from sourcia.core.demande import Demande
from sourcia.core.models import Fiche

STATIC = Path(__file__).parent / "static"


class SelectionRequest(BaseModel):
    demande: Demande
    llm_top: int = 0
    formats: list[str] = ["md", "csv", "txt", "json"]


class FormationRequest(BaseModel):
    demande: Demande
    doc_ids: list[str]
    sequences: int = 4
    quiz: int = 4


class Decision(BaseModel):
    n: int
    valide: bool
    code_corrige: str = ""
    commentaire: str = ""


class ValidationRequest(BaseModel):
    valideur: str
    decisions: list[Decision]


SECRET_MIN = 32
LOGIN_MESSAGE = ("Connectez-vous d'abord (page « Mes dossiers », avec le lien reçu) : en ligne, lancer une "
                 "formation ou des supports est réservé aux enseignants qui ont un compte.")


def check_server(settings) -> None:
    """Mode serveur : refuse de démarrer sans secret de session (sinon chaque redémarrage déconnecte tout le monde)."""
    if not settings.serveur:
        return
    if len(os.environ.get("SOURCIA_SESSION_SECRET", "")) < SECRET_MIN:
        raise RuntimeError(
            f"Mode serveur : la variable SOURCIA_SESSION_SECRET doit contenir au moins {SECRET_MIN} caractères "
            "aléatoires. Pour en créer une : python -c \"import secrets; print(secrets.token_urlsafe(48))\" "
            "(voir docs/DEPLOIEMENT.md).")
    if settings.llm.provider == "litellm" and not os.environ.get("GEMINI_API_KEY"):
        print("⚠️  GEMINI_API_KEY absente : les corpus et les supports « avec modèle » échoueront.", file=sys.stderr)


def create_app(config: str | None = None, ctx=None) -> FastAPI:
    from sourcia.config import load_settings
    from sourcia.container import Context
    from sourcia.export.exporters import export, rows
    from sourcia.referentiel.models import ReferentielStore
    from sourcia.select.funnel import select_demande

    ctx = ctx or Context(load_settings(config))
    check_server(ctx.settings)
    app = FastAPI(title="SourcIA", version=BUILD)
    dossiers = create_dossiers_router(ctx)

    def teacher(request: Request, response: Response,
                credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str | None:
        """Enseignant connecté, ou None. Hors mode serveur (sur son PC), personne n'a à se connecter."""
        try:
            return dossiers.identity(request, response, credentials)
        except HTTPException:
            return None

    def required(email: str | None = Depends(teacher)) -> str | None:
        if ctx.settings.serveur and not email:
            raise HTTPException(401, LOGIN_MESSAGE, headers={"WWW-Authenticate": "Bearer"})
        return email
    export_dir = ctx.settings.path("exports", ".keep").parent
    form_dir = ctx.settings.path("formations", ".keep").parent
    refs = ReferentielStore(ctx.settings.referentiels_dir)

    def safe(base: Path, *parts: str) -> Path:
        p = base.joinpath(*parts).resolve()
        if base.resolve() not in p.parents or not p.exists():
            raise HTTPException(404, "fichier introuvable")
        return p

    @app.get("/assets/sourcia.css", include_in_schema=False)
    def stylesheet():
        return FileResponse(STATIC / "sourcia.css", media_type="text/css")

    fonts = {p.name for p in (STATIC / "fonts").glob("*.woff2")}   # liste fermée : rien d'autre n'est servi

    @app.get("/assets/fonts/{name}", include_in_schema=False)
    def font(name: str):
        """Polices hébergées ici (licence OFL) : rien n'est demandé à Google, et la page marche hors ligne."""
        if name not in fonts:
            raise HTTPException(404, "police introuvable")
        return FileResponse(STATIC / "fonts" / name, media_type="font/woff2",
                            headers={"Cache-Control": "public, max-age=604800"})

    @app.get("/assets/parcours.js", include_in_schema=False)
    def parcours_script():
        """Écrans « Mon corpus » et « Mes supports » de la page des dossiers."""
        return FileResponse(STATIC / "parcours.js", media_type="text/javascript")

    @app.get("/", response_class=HTMLResponse)
    def home():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/etat")
    def etat():
        return {"build": BUILD, "configuration": ctx.settings.name, "modele": ctx.settings.llm.model,
                "documents": ctx.store.stats(), "fiches": len(ctx.qualifier.fiches),
                "index": bool(ctx.index.chunks), "sources": sorted({d.source for d in ctx.store})}

    @app.get("/api/referentiels")
    def referentiels():
        return [{"id": r.id, "nom": r.nom, "niveau": r.niveau, "version": r.version, "statut": r.statut,
                 "capacites": [{"code": c.code, "libelle": c.libelle, "parent": c.parent} for c in r.capacites]}
                for r in refs.all()]

    @app.get("/api/recherche")
    def recherche(q: str, k: int = 20):
        out = []
        for h in ctx.index.search(q, k=k):
            d = ctx.store.get(h.doc_id)
            if d:
                out.append({"id": d.id, "titre": d.title, "url": d.url, "source": d.source, "page": h.page,
                            "passage": h.passage[:400]})
        return out

    @app.post("/api/selection")
    def selection(req: SelectionRequest, email: str | None = Depends(teacher)):
        if not req.demande.sujet.strip():
            raise HTTPException(400, "sujet vide")
        if ctx.settings.serveur and not email:           # visiteur : chercher oui, modèle et fichiers d'export non
            if req.llm_top:
                raise HTTPException(401, LOGIN_MESSAGE, headers={"WWW-Authenticate": "Bearer"})
            req.formats = []
        sel = select_demande(ctx.selector, req.demande, llm_top=req.llm_top)
        ctx.qualifier.save()
        ctx.store.save()
        files = export(sel, req.demande.sujet, export_dir, req.formats, structured=req.demande.model_dump()) if req.formats else []
        data = rows(sel)
        for r, c in zip(data, sel):
            r["composantes"] = c.components
            r["nature"] = c.document.kind
        return {"demande": req.demande.sujet, "documents": data, "exports": [p.name for p in files]}

    @app.get("/api/fiche/{doc_id}")
    def fiche(doc_id: str):
        d, fi = ctx.store.get(doc_id), ctx.qualifier.get(doc_id)
        if not d or not fi:
            raise HTTPException(404, "fiche introuvable")
        return {"document": d.model_dump(exclude={"local_path"}),
                "champs": {n: getattr(fi, n).model_dump() for n in Fiche.FIELDS},
                "themes": fi.themes, "alertes": fi.alertes, "resume": fi.resume, "passes": fi.passes}

    @app.get("/api/export/{name}")
    def download(name: str):
        return FileResponse(safe(export_dir, name), filename=name)

    @app.post("/api/formation")
    def formation(req: FormationRequest, _: str | None = Depends(required)):
        from sourcia.formation.builder import FormationBuilder
        from sourcia.formation.render import write

        if not req.doc_ids:
            raise HTTPException(400, "aucun document : faire d'abord une sélection")
        form = FormationBuilder(ctx).build(req.demande, req.doc_ids, n_seq=req.sequences, n_quiz=req.quiz)
        paths = write(form, ctx, form_dir)
        return {"dossier": paths[0].parent.name, "fichiers": [p.name for p in paths],
                "support": paths[0].read_text(encoding="utf-8"), "appels_modele": form.appels_modele,
                "duree_s": form.duree_s, "rattachements": [
                    {"n": i, "sequence": s.titre, "capacite": s.capacite, "libelle": s.capacite_libelle, "statut": s.capacite_statut}
                    for i, s in enumerate(form.sequences, 1)] if form.referentiel else []}

    @app.get("/api/formation/{dossier}/{name}")
    def formation_file(dossier: str, name: str):
        return FileResponse(safe(form_dir, dossier, name), filename=name)

    @app.post("/api/formation/{dossier}/rattachements")
    def valider(dossier: str, req: ValidationRequest, _: str | None = Depends(required)):
        import csv

        from sourcia.formation.render import load, write
        from sourcia.referentiel.validation import Rattachements, import_rattachements_csv

        folder = safe(form_dir, dossier)
        form = load(folder)
        if not form.referentiel:
            raise HTTPException(400, "formation non rattachée à un référentiel")
        tmp = folder / "rattachements_page.csv"
        with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["n", "valide (oui/non)", "code_corrige", "commentaire"])
            for dcs in req.decisions:
                w.writerow([dcs.n, "oui" if dcs.valide else "non", dcs.code_corrige, dcs.commentaire])
        stats = import_rattachements_csv(form, tmp, Rattachements(ctx.settings.path("rattachements_valides.jsonl")),
                                         refs.get(form.referentiel["id"]), req.valideur)
        write(form, ctx, form_dir, reprendre=folder)
        return stats

    # --- supports (étape 4) d'un corpus du catalogue (data/corpus/corpus-<date>), sans jeton comme /api/formation
    jobs = SupportsJobs(ctx)
    corpus_dir = ctx.settings.path("corpus", ".keep").parent

    def catalog_corpus(corpus_id: str) -> Path:
        folder = corpus_dir / corpus_id
        if not CID_RE.match(corpus_id) or not (folder / "corpus.json").is_file():
            raise HTTPException(404, "Corpus introuvable")
        return folder

    @app.post("/api/supports", status_code=202)
    def supports_start(req: CatalogueSupportsRequest, tasks: BackgroundTasks, email: str | None = Depends(required)):
        return jobs.start(catalog_corpus(req.corpus_id), req, tasks, email or "page web")

    @app.get("/api/supports/{corpus_id}")
    def supports_list(corpus_id: str):
        return jobs.list(catalog_corpus(corpus_id))

    @app.get("/api/supports/{corpus_id}/{sid}")
    def supports_status(corpus_id: str, sid: str):
        return jobs.status(catalog_corpus(corpus_id), sid)

    @app.get("/api/supports/{corpus_id}/{sid}/{name}")
    def supports_file(corpus_id: str, sid: str, name: str):
        return jobs.file(catalog_corpus(corpus_id), sid, name)

    app.include_router(dossiers)

    @app.get("/dossiers", response_class=HTMLResponse)
    def teacher_folders():
        return (STATIC / "dossiers.html").read_text(encoding="utf-8")

    return app
