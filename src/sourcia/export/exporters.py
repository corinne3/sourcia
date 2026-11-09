"""Sorties (M6) : la sélection dans des formats utilisables par n'importe quel outil de génération.

- ``.md``   : liste lisible (titre, lien, justification, alertes) ;
- ``.csv``  : toutes les colonnes de la fiche, pour un tableur (et pour relecture par le métier) ;
- ``.txt``  : une adresse web publique par ligne (pour NotebookLM ou équivalent) ;
- ``.zip``  : les PDF téléchargés de la sélection (à déposer dans l'outil de génération).
"""
from __future__ import annotations

import csv
import json
import zipfile
from datetime import datetime
from pathlib import Path

from sourcia.core.models import Fiche

COLUMNS = ["rang", "id", "titre", "url", "source", "score", "justification", *Fiche.FIELDS, "alertes", "themes", "resume", "prive"]


# Jamais le chemin d'un document privé dans un export (tableur, NotebookLM, MCP).
def rows(selection) -> list[dict]:
    out = []
    for i, c in enumerate(selection, start=1):
        fi = c.fiche
        r = {"rang": i, "id": c.document.id, "titre": c.document.title, "url": "" if c.document.private else c.document.url,  "source": c.document.source,
             "score": round(c.score, 3), "justification": c.justification,
             "alertes": " ; ".join(fi.alertes) if fi else "", "themes": ", ".join(fi.themes) if fi else "",
             "resume": (fi.resume or "") if fi else "", "prive": c.document.private}
        for name in Fiche.FIELDS:
            v = fi.get(name) if fi else None
            r[name] = "" if v is None else v
        out.append(r)
    return out


def export(selection, demande: str, out_dir: Path, formats=("md", "csv", "txt", "json"),
           structured: dict | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"selection-{datetime.now():%Y%m%d-%H%M%S}"
    written = []
    data = rows(selection)
    if "json" in formats:
        p = stem.with_suffix(".json")
        p.write_text(json.dumps({"demande": demande, "demande_structuree": structured, "documents": data},
                                ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        written.append(p)
    if "csv" in formats:
        p = stem.with_suffix(".csv")
        with open(p, "w", newline="", encoding="utf-8-sig") as fh:          # utf-8-sig : accents corrects dans Excel
            w = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter=";")
            w.writeheader()
            w.writerows(data)
        written.append(p)
    if "md" in formats:
        p = stem.with_suffix(".md")
        lines = [f"# Sources pour : {demande}", "", f"{len(data)} documents, sélectionnés le {datetime.now():%d/%m/%Y}.", ""]
        for r in data:
            head = f"**{r['titre']}** (document privé)" if r["prive"] else f"**[{r['titre'] or r['url']}]({r['url']})** ({r['source']})"
            lines += [f"{r['rang']}. {head}", f"   {r['justification']}", ""]
        p.write_text("\n".join(lines), encoding="utf-8")
        written.append(p)
    if "txt" in formats:
        p = stem.with_suffix(".txt")
        web = [r["url"] for r in data if not r["prive"] and str(r["url"]).startswith(("http://", "https://"))]
        p.write_text("\n".join(web) + "\n", encoding="utf-8")         # seulement des adresses web publiques
        written.append(p)
    if "zip" in formats:
        p = stem.with_suffix(".zip")
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for i, c in enumerate(selection, start=1):
                lp = c.document.local_path
                if lp and Path(lp).exists():
                    z.write(lp, f"{i:02d}-{Path(lp).name}")
        written.append(p)
    return written
