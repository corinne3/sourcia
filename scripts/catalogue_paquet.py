"""Paquet du catalogue pour un serveur : sans PDF, sans comptes ni dossiers, sans chemin de son ordinateur.

Le catalogue (data/) n'est jamais dans git ni dans l'image Docker : ce sont des contenus de tiers. On l'emballe sur
son PC, puis on l'importe une fois dans le volume du serveur.

Sur son PC :
    python scripts/catalogue_paquet.py creer                      → catalogue-AAAAMMJJ.tar.gz (≈ 25 Mo)
Sur le serveur (dans le conteneur) :
    python scripts/catalogue_paquet.py importer /tmp/catalogue-AAAAMMJJ.tar.gz

Ce qui part : documents.jsonl, fiches.jsonl, textes extraits (text/), pages web (pages/), index de recherche (index/).
Ce qui reste : PDF (retéléchargés depuis leur site quand un enseignant ajoute le document à un dossier), comptes,
dossiers, corpus, traces, exports. Les chemins de son PC (« C:\\Users\\… ») sont retirés des fiches des documents.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
from datetime import date
from pathlib import Path

PARTS = ["documents.jsonl", "fiches.jsonl", "text", "pages", "index"]
REQUIRED = ["documents.jsonl", "fiches.jsonl"]
SERVER_INDEX = "index/hashing-256"               # index de config/serveur.yaml (recherche légère)
LOCAL = "pages"                                  # seuls fichiers locaux emportés : les pages web enregistrées


def portable(doc: dict, data: Path) -> dict:
    """Chemin local rendu relatif (« pages/x.txt ») s'il est emporté, sinon retiré (le PDF sera retéléchargé)."""
    path = doc.get("local_path")
    if path:
        p = Path(path.replace("\\", "/"))
        doc["local_path"] = f"{LOCAL}/{p.name}" if p.parent.name == LOCAL and (data / LOCAL / p.name).is_file() else None
    return doc


def create(data: Path, out: Path) -> dict:
    missing = [p for p in REQUIRED if not (data / p).is_file()]
    if missing:
        raise SystemExit(f"❌ Pas de catalogue dans {data} (manque : {', '.join(missing)}).")
    docs = [portable(json.loads(line), data)
            for line in (data / "documents.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = "\n".join(json.dumps(d, ensure_ascii=False) for d in docs).encode("utf-8") + b"\n"
    with tarfile.open(out, "w:gz") as tar:
        info = tarfile.TarInfo("documents.jsonl")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
        for part in PARTS[1:]:
            if (data / part).exists():
                tar.add(data / part, arcname=part)
    pdfs = sum(1 for d in docs if d.get("kind") == "pdf")
    return {"documents": len(docs), "pdf_a_retelecharger": pdfs, "taille_mo": round(out.stat().st_size / 1e6, 1),
            "index_serveur": (data / SERVER_INDEX).is_dir()}


def safe_members(tar: tarfile.TarFile):
    """Refuse tout chemin qui sortirait du dossier des données (« ../ », chemin absolu, lien)."""
    for m in tar.getmembers():
        name = Path(m.name)
        if name.is_absolute() or ".." in name.parts or not (m.isfile() or m.isdir()):
            raise SystemExit(f"❌ Paquet refusé : entrée suspecte « {m.name} ».")
        if name.parts[0] not in PARTS:
            raise SystemExit(f"❌ Paquet refusé : « {m.name} » n'est pas une partie du catalogue.")
        yield m


def import_(archive: Path, data: Path, replace: bool = False) -> dict:
    if (data / "documents.jsonl").exists() and not replace:
        raise SystemExit(f"❌ {data} a déjà un catalogue. Ajoutez --remplacer pour l'écraser "
                         "(les comptes et les dossiers ne sont jamais touchés).")
    data.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        members = list(safe_members(tar))
        extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}   # contrôle de Python en plus
        tar.extractall(data, members=members, **extra)
    lines = (data / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    docs = []
    for line in lines:
        if line.strip():
            d = json.loads(line)
            if d.get("local_path"):                      # « pages/x.txt » → chemin complet sur ce serveur
                d["local_path"] = str((data / d["local_path"]).resolve())
            docs.append(d)
    (data / "documents.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n" for d in docs),
                                          encoding="utf-8")
    return {"documents": len(docs), "index_serveur": (data / SERVER_INDEX).is_dir()}


def main(argv: list[str] | None = None) -> None:
    default_data = os.environ.get("SOURCIA_DATA_DIR", "data")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    c = sub.add_parser("creer", help="emballer le catalogue de son PC")
    c.add_argument("--data", default=default_data, help=f"dossier des données (défaut : {default_data})")
    c.add_argument("--sortie", default=f"catalogue-{date.today():%Y%m%d}.tar.gz")
    i = sub.add_parser("importer", help="importer un paquet dans le dossier des données du serveur")
    i.add_argument("paquet")
    i.add_argument("--data", default=default_data, help=f"dossier des données (défaut : {default_data})")
    i.add_argument("--remplacer", action="store_true", help="écraser le catalogue déjà présent")
    args = parser.parse_args(argv)
    if args.action == "creer":
        r = create(Path(args.data), Path(args.sortie))
        print(f"✅ {args.sortie} : {r['documents']} documents, {r['taille_mo']} Mo "
              f"({r['pdf_a_retelecharger']} PDF non emportés, retéléchargés au besoin).")
    else:
        r = import_(Path(args.paquet), Path(args.data), args.remplacer)
        print(f"✅ Catalogue importé dans {args.data} : {r['documents']} documents.")
    if not r["index_serveur"]:
        print("⚠️  Pas d'index « recherche légère » (index/hashing-256) : sur le serveur, lancez "
              "« sourcia index » pour le construire.", file=sys.stderr)


if __name__ == "__main__":
    main()
