"""Connecteur chlorofil.fr : télécharger les référentiels, extraire les capacités, détecter une nouvelle version.

- ``fetch_and_build`` : télécharge les PDF du catalogue (ou prend des fichiers locaux), extrait, écrit le YAML ;
- ``check_versions`` : (1) un fichier connu a-t-il changé (empreinte) ? (2) existe-t-il le même nom avec une
  année plus récente (…-2024.pdf → …-2025.pdf) ? (3) si la page du diplôme est renseignée, on l'explore
  avec le collecteur de M1 (robots.txt respecté) et on garde les PDF qui suivent le « motif ».
Une nouvelle version ne remplace jamais l'ancienne d'office : elle est extraite à côté, statut « a_revoir ».
"""
from __future__ import annotations

import re
from pathlib import Path
import yaml

from sourcia.collect.store import file_sha1
from sourcia.referentiel.extract import build
from sourcia.referentiel.models import Referentiel


def load_catalogue(folder: Path) -> list[dict]:
    p = Path(folder) / "catalogue.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")).get("referentiels", []) if p.exists() else []


def entry(folder: Path, rid: str) -> dict:
    e = next((x for x in load_catalogue(folder) if x["id"] == rid), None)
    if e is None:
        raise KeyError(f"référentiel inconnu : {rid} (voir config/referentiels/catalogue.yaml)")
    return e


def _collector(settings, fetch=None):
    from sourcia.collect.web import WebCollector

    return WebCollector(settings, fetch=fetch)


def download(settings, url: str, out_dir: Path, fetch=None) -> Path | None:
    """Télécharge un PDF (politesse et robots.txt du collecteur M1). None si absent ou pas un PDF."""
    wc = _collector(settings, fetch)
    try:
        if not wc.allowed(url):
            return None
        r = wc.get(url)
    except Exception as exc:                                  # réseau coupé, site indisponible
        print(f"  ⚠️ {url} : {type(exc).__name__}")
        return None
    if r is None or getattr(r, "status_code", 0) != 200 or not r.content[:5].startswith(b"%PDF"):
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / Path(url).name
    p.write_bytes(r.content)
    return p


def fetch_and_build(settings, folder: Path, rid: str, files: list[Path] | None = None, fetch=None) -> Referentiel:
    """Construit ``config/referentiels/<rid>.yaml`` à partir des fichiers locaux, sinon en téléchargeant."""
    e = entry(folder, rid)
    urls = {Path(u).name: u for u in e.get("fichiers", [])}
    if not files:
        out = settings.path("referentiels", rid, ".keep").parent
        files = [p for u in urls.values() if (p := download(settings, u, out, fetch))]
        if not files:
            raise RuntimeError("aucun PDF téléchargé : vérifier la connexion ou donner les fichiers (--fichiers)")
    ref = build(rid, e["nom"], e["type"], files, version=str(e.get("version", "")), niveau=e.get("niveau"), urls=urls)
    old = Path(folder) / f"{rid}.yaml"
    if old.exists():
        prev = Referentiel.load(old)
        kept = {c.code: c for c in prev.capacites if c.statut == "valide"}
        for c in ref.capacites:                              # une capacité déjà validée, au libellé identique, le reste
            k = kept.get(c.code)
            if k and k.libelle == c.libelle:
                c.statut, c.commentaire = "valide", k.commentaire
        if prev.version != ref.version:
            ref.statut = "a_revoir"
    ref.save(old)
    return ref


def _next_year_urls(url: str) -> list[str]:
    m = re.search(r"(20\d\d)(?=[^/]*\.pdf$)", url)
    if not m:
        return []
    y = int(m.group(1))
    return [url[: m.start()] + str(y + k) + url[m.end():] for k in (1, 2)]


def check_versions(settings, folder: Path, rid: str, fetch=None) -> dict:
    e = entry(folder, rid)
    ref = Referentiel.load(Path(folder) / f"{rid}.yaml") if (Path(folder) / f"{rid}.yaml").exists() else None
    known = {s.get("fichier"): s.get("sha1") for s in (ref.sources if ref else [])}
    tmp = settings.path("referentiels", rid, "verif", ".keep").parent
    report = {"id": rid, "modifies": [], "nouveaux": [], "inchanges": [], "injoignables": []}
    for url in e.get("fichiers", []):
        p = download(settings, url, tmp, fetch)
        if p is None:
            report["injoignables"].append(url)
            continue
        (report["inchanges"] if known.get(p.name) == file_sha1(p) else report["modifies"]).append(url)
        for cand in _next_year_urls(url):
            if download(settings, cand, tmp, fetch):
                report["nouveaux"].append(cand)
    if e.get("page"):
        wc = _collector(settings, fetch)
        docs, _ = wc.crawl(e["page"], include=e.get("motif"))
        report["nouveaux"] += [d.url for d in docs if d.url not in e.get("fichiers", []) and d.url not in report["nouveaux"]]
    return report
