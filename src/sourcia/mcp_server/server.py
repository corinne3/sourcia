"""Serveur MCP de SourcIA : d'autres outils (l'agent de l'équipe, un client compatible MCP)
appellent la recherche et la sélection sans connaître notre code.

Outils exposés :
- ``chercher_sources``   : recherche simple (M4), documents classés + passage ;
- ``selectionner_sources`` : l'entonnoir complet (M5) → ≈ 50 documents justifiés ;
- ``fiche_document``     : la fiche de qualification d'un document, avec les preuves (M3) ;
- ``lister_referentiels`` : les diplômes et leurs capacités (M8) ;
- ``creer_formation``    : le support de formation complet, piloté par la demande structurée (M0, M7).

Lancement (stdio) : ``sourcia mcp`` ou ``python -m sourcia.mcp_server.server``.
⚠️ En stdio, rien sur stdout (réservé au protocole) : les messages vont sur stderr.
"""
from __future__ import annotations

import argparse
import sys

from sourcia.core.models import Fiche


def build_server(ctx):
    try:                                   # SDK MCP 2.x
        from mcp.server.mcpserver import MCPServer as _Server
    except ImportError:                    # SDK MCP 1.x
        from mcp.server.fastmcp import FastMCP as _Server
    from sourcia.export.exporters import rows
    from sourcia.select.funnel import Filters

    server = _Server(name="sourcia", instructions="Recherche et qualification de documents de R&D agricole "
                     "(fourrages, prairies, changement climatique) pour préparer une formation.")

    @server.tool()
    def chercher_sources(requete: str, nombre: int = 10) -> list[dict]:
        """Cherche des documents de R&D. requete : la recherche en français ; nombre : 1 à 50."""
        out = []
        for h in ctx.index.search(requete, k=max(1, min(nombre, 50))):
            d = ctx.store.get(h.doc_id)
            if d:
                out.append({"id": d.id, "titre": d.title, "url": "" if d.private else d.url, "source": d.source,
                            "page": h.page, "passage": h.passage[:400]})
        return out

    @server.tool()
    def selectionner_sources(demande: str, nombre: int = 50, annee_min: int = 0, types: str = "",
                             region: str = "") -> list[dict]:
        """Sélectionne les documents les plus utiles pour une demande de formateur, avec une justification.

        types : liste séparée par des virgules (experimentation, retour_experience, synthese, guide_technique)
        region : région du formateur (alerte si le contexte est éloigné)"""
        f = Filters(annee_min=annee_min or None, types=[t for t in types.split(",") if t], region=region or None)
        sel = ctx.selector.select(demande, f, n=max(1, min(nombre, 100)))
        ctx.qualifier.save()
        data = rows(sel)
        for r in data:
            if r["prive"]:
                r["url"] = ""                  # on ne divulgue pas le chemin d'un document privé
        return data

    @server.tool()
    def fiche_document(document_id: str) -> dict:
        """La fiche de qualification d'un document : chaque valeur avec sa preuve et sa confiance."""
        fi = ctx.qualifier.get(document_id)
        if fi is None:
            return {"erreur": f"pas de fiche pour {document_id}"}
        return {name: getattr(fi, name).model_dump() for name in Fiche.FIELDS} | {
            "themes": fi.themes, "alertes": fi.alertes, "resume": fi.resume}

    @server.tool()
    def lister_referentiels() -> list[dict]:
        """Les diplômes disponibles (référentiels officiels) et leurs capacités (codes et libellés)."""
        from sourcia.referentiel.models import ReferentielStore

        return [{"id": r.id, "nom": r.nom, "niveau": r.niveau, "version": r.version,
                 "capacites": [f"{c.code} : {c.libelle}" for c in r.capacites]}
                for r in ReferentielStore(ctx.settings.referentiels_dir).all()]

    @server.tool()
    def creer_formation(sujet: str, profil: str = "formateur", apprenants: str = "etudiants", niveau: str = "bts",
                        diplome: str = "", capacites: str = "", sorties: str = "plan,points_cles,quiz,glossaire",
                        modalite: str = "presentiel", duree_min: int = 120, nombre_sources: int = 20) -> str:
        """Crée un support de formation à partir des sources sélectionnées pour le sujet. Renvoie le Markdown.
        Peut prendre plusieurs minutes.

        profil : enseignant, formateur, conseiller, intervenant_exterieur ; apprenants : eleves, apprentis, etudiants,
        salaries, chefs_entreprise ; niveau : cap, bac_pro, bts, licence… ; diplome + capacites (ex. btsa-acsagri, C4.2)
        pour une formation diplômante ; sorties : plan, points_cles, quiz, fiche_technique, synthese, cas_concret,
        glossaire, podcast, deroule_oral"""
        from sourcia.core.demande import Demande
        from sourcia.formation.builder import FormationBuilder
        from sourcia.formation.render import write
        from sourcia.select.funnel import select_demande

        d = Demande(sujet=sujet, profil=profil, apprenants=apprenants, niveau=niveau, diplomante=bool(diplome),
                    diplome=diplome or None, capacites=[c for c in capacites.split(",") if c],
                    sorties=[x for x in sorties.split(",") if x], modalite=modalite, duree_min=duree_min,
                    nombre_sources=nombre_sources)
        sel = select_demande(ctx.selector, d)
        form = FormationBuilder(ctx).build(d, [c.document.id for c in sel])
        paths = write(form, ctx, ctx.settings.path("formations", ".keep").parent)
        return paths[0].read_text(encoding="utf-8")

    return server


def run(config: str | None = None) -> None:
    from sourcia.config import load_settings
    from sourcia.container import Context

    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ctx = Context(load_settings(config))
    if not ctx.index.chunks:
        print("⚠️ index vide : lancer d'abord « sourcia index »", file=sys.stderr)
    build_server(ctx).run()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Serveur MCP SourcIA (stdio)")
    ap.add_argument("--config", default=None)
    run(ap.parse_args(argv).config)


if __name__ == "__main__":
    main()
