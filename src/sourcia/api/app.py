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
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from sourcia import BUILD
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


def create_app(config: str | None = None, ctx=None) -> FastAPI:
    from sourcia.config import load_settings
    from sourcia.container import Context
    from sourcia.export.exporters import export, rows
    from sourcia.referentiel.models import ReferentielStore
    from sourcia.select.funnel import select_demande

    ctx = ctx or Context(load_settings(config))
    app = FastAPI(title="SourcIA", version=BUILD)
    export_dir = ctx.settings.path("exports", ".keep").parent
    form_dir = ctx.settings.path("formations", ".keep").parent
    refs = ReferentielStore(ctx.settings.referentiels_dir)

    def safe(base: Path, *parts: str) -> Path:
        p = base.joinpath(*parts).resolve()
        if base.resolve() not in p.parents or not p.exists():
            raise HTTPException(404, "fichier introuvable")
        return p

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
    def selection(req: SelectionRequest):
        if not req.demande.sujet.strip():
            raise HTTPException(400, "sujet vide")
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
    def formation(req: FormationRequest):
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
    def valider(dossier: str, req: ValidationRequest):
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

    return app
