"""Collecte quotidienne des sites prioritaires (M1) : ``config/sites.yaml`` → catalogue + rapport.

Pour chaque site de la liste :
1. exploration avec ``WebCollector.crawl`` (plans de site, pages HTML, robots.txt, politesse) ;
2. ajout des PDF trouvés au catalogue (``documents.jsonl``), en comptant les nouveaux ;
3. téléchargement des PDF du site encore « listés » (les nouveaux, et ceux laissés en attente
   par un lancement ``--no-download``) ;
4. un rapport : pages visitées, PDF trouvés, nouveaux, téléchargés, erreurs, bloqués par robots.txt.

Un site en panne n'arrête pas les autres. Le catalogue est enregistré après chaque site.
Le rapport de chaque lancement est gardé (``data/collecte/``) : l'historique servira à repérer
les liens déplacés ou morts.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from sourcia.collect.store import DocumentStore
from sourcia.collect.web import CrawlReport, WebCollector, _short_error


class SiteConfig(BaseModel):
    """Un site de ``config/sites.yaml``. Les champs inconnus sont acceptés (ajouts futurs)."""

    model_config = ConfigDict(extra="allow")

    nom: str                      # nom court, sert aussi de « source » des documents
    url: str                      # adresse de départ de l'exploration
    filtre: str | None = None     # expression régulière sur l'adresse ou le texte du lien des PDF


def load_sites(path: Path) -> list[SiteConfig]:
    """Lit et vérifie la liste des sites. Lève ``ValueError`` avec un message lisible."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f"fichier des sites introuvable : {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("sites") if isinstance(data, dict) else None
    if not raw:
        raise ValueError(f"{path} : aucune entrée sous « sites: »")
    sites, names = [], set()
    for i, entry in enumerate(raw, 1):
        try:
            site = SiteConfig.model_validate(entry)
        except ValidationError as exc:
            champs = ", ".join(str(e["loc"][0]) for e in exc.errors() if e.get("loc"))
            raise ValueError(f"{path} : site n° {i} incomplet ou invalide ({champs or exc})") from None
        if site.nom in names:
            raise ValueError(f"{path} : le nom « {site.nom} » apparaît deux fois")
        if site.filtre:
            try:
                re.compile(site.filtre)
            except re.error as exc:
                raise ValueError(f"{path} : filtre invalide pour « {site.nom} » ({exc})") from None
        names.add(site.nom)
        sites.append(site)
    return sites


def select_sites(sites: list[SiteConfig], names: list[str] | None) -> list[SiteConfig]:
    """Ne garde que les sites demandés (``--site``). Un nom inconnu lève ``ValueError``."""
    if not names:
        return sites
    known = {s.nom for s in sites}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise ValueError(f"site inconnu : {', '.join(unknown)} (sites disponibles : {', '.join(sorted(known))})")
    return [s for s in sites if s.nom in names]


def collect_site(wc: WebCollector, store: DocumentStore, site: SiteConfig, pdf_dir: Path,
                 download: bool = True) -> dict:
    """Explore un site, met à jour le catalogue, télécharge les PDF en attente. Renvoie le rapport du site."""
    t0 = time.monotonic()
    rep = CrawlReport(site=site.nom)
    failed_downloads = 0
    try:
        docs, rep = wc.crawl(site.url, source=site.nom, include=site.filtre)
        rep.pdfs_new = sum(store.add(d) for d in docs)
        store.save()
        if download:
            todo = [d for d in store if d.source == site.nom and d.kind == "pdf" and d.status == "listed"]
            for d in todo:
                if not wc.allowed(d.url):
                    rep.blocked_by_robots += 1
                    continue
                wc.download(d, pdf_dir)
                if d.status == "downloaded":
                    rep.downloaded += 1
                else:
                    failed_downloads += 1
                    rep.errors.append(f"{d.url} : {d.error}")
            store.save()
    except Exception as exc:                       # un site en panne n'arrête pas la collecte
        rep.errors.append(f"{site.url} : {_short_error(exc)}")
        store.save()
    return {
        "site": site.nom,
        "url": site.url,
        "filtre": site.filtre,
        "pages_visitees": rep.pages_visited,
        "pdf_trouves": rep.pdfs_found,
        "nouveaux": rep.pdfs_new,
        "telecharges": rep.downloaded,
        "echecs_telechargement": failed_downloads,
        "bloques_robots": rep.blocked_by_robots,
        "erreurs": rep.errors,
        "duree_s": round(time.monotonic() - t0, 1),
        # échec : aucune page lue (site injoignable, adresse à revoir) ou page de départ sans lien (site bloqué)
        "ok": rep.pages_visited > 0 and not rep.start_page_empty,
    }


def collect_sites(wc: WebCollector, store: DocumentStore, sites: list[SiteConfig], pdf_dir: Path,
                  download: bool = True,
                  progress: Callable[[SiteConfig, dict | None], None] | None = None) -> list[dict]:
    """Collecte tous les sites, l'un après l'autre. ``progress(site, None)`` avant, ``progress(site, rapport)`` après."""
    reports = []
    for site in sites:
        if progress:
            progress(site, None)
        rep = collect_site(wc, store, site, pdf_dir, download)
        reports.append(rep)
        if progress:
            progress(site, rep)
    return reports


def run_report(reports: list[dict], options: dict, started: datetime) -> dict:
    """Le rapport complet d'un lancement (ce qui est écrit en JSON)."""
    keys = ("pages_visitees", "pdf_trouves", "nouveaux", "telecharges", "echecs_telechargement", "bloques_robots")
    total = {k: sum(r[k] for r in reports) for k in keys}
    total["erreurs"] = sum(len(r["erreurs"]) for r in reports)
    total["sites_en_echec"] = [r["site"] for r in reports if not r["ok"]]
    return {"date": started.isoformat(timespec="seconds"), "options": options, "total": total, "sites": reports}


def write_report(report: dict, directory: Path) -> Path:
    """Écrit ``rapport-AAAA-MM-JJ_HHMMSS.json`` (historique) et ``dernier.json`` (le plus récent)."""
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(report["date"]).strftime("%Y-%m-%d_%H%M%S")
    text = json.dumps(report, ensure_ascii=False, indent=1)
    path = directory / f"rapport-{stamp}.json"
    path.write_text(text, encoding="utf-8")
    (directory / "dernier.json").write_text(text, encoding="utf-8")
    return path


def format_site(rep: dict, max_errors: int = 5) -> str:
    """Une ligne lisible par site (et ses premières erreurs)."""
    mark = "✓" if rep["ok"] else "✗"
    line = (f"  {mark} {rep['site']} : {rep['pages_visitees']} pages · {rep['pdf_trouves']} PDF trouvés"
            f" · {rep['nouveaux']} nouveaux · {rep['telecharges']} téléchargés"
            f" · {rep['bloques_robots']} bloqués (robots.txt) · {len(rep['erreurs'])} erreurs · {rep['duree_s']} s")
    lines = [line] + [f"      ⚠ {e[:150]}" for e in rep["erreurs"][:max_errors]]
    if len(rep["erreurs"]) > max_errors:
        lines.append(f"      … et {len(rep['erreurs']) - max_errors} autres (voir le rapport JSON)")
    return "\n".join(lines)


def format_total(report: dict) -> str:
    t = report["total"]
    line = (f"Total : {len(report['sites'])} sites · {t['pages_visitees']} pages · {t['pdf_trouves']} PDF trouvés"
            f" · {t['nouveaux']} nouveaux · {t['telecharges']} téléchargés · {t['bloques_robots']} bloqués"
            f" · {t['erreurs']} erreurs")
    if t["sites_en_echec"]:
        line += f"\nSites en échec (injoignables ou bloqués) : {', '.join(t['sites_en_echec'])}"
    return line
