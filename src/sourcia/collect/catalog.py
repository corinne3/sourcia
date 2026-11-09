"""Import d'un catalogue existant (export CSV ou JSON) : RD Agri via le Lexicon, liste d'adresses…

Les noms de colonnes varient selon les sources : on reconnaît les plus courants, et on peut
préciser la correspondance (``--map titre=title,url=lien``). Le connecteur direct au MCP RD Agri
sera branché quand sa documentation sera publiée sur le forum.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from sourcia.collect.media import kind_of
from sourcia.core.models import Document, doc_id_for

GUESS = {
    "url": ["url", "lien", "link", "uri", "pdf_url", "document_url", "href"],
    "title": ["title", "titre", "name", "nom", "label", "libelle"],
    "date": ["date", "year", "annee", "année", "published", "publication_date", "created_at"],
    "keywords": ["keywords", "mots_cles", "mots-clés", "tags", "sujets", "themes"],
    "licence": ["licence", "license"],
    "kind": ["kind", "nature", "type_ressource", "format", "media", "type"],
    "description": ["description", "resume", "résumé", "abstract", "notes"],
}


def _pick(row: dict, field: str, mapping: dict[str, str]) -> str | None:
    if field in mapping:
        return row.get(mapping[field])
    lower = {k.lower().strip(): v for k, v in row.items()}
    for cand in GUESS[field]:
        if cand in lower and lower[cand] not in (None, ""):
            return lower[cand]
    return None


def read_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in (".json", ".jsonl"):
        if path.suffix.lower() == ".jsonl":
            return [json.loads(l) for l in text.splitlines() if l.strip()]
        data = json.loads(text)
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [data])
        return data
    if path.suffix.lower() == ".txt":
        return [{"url": l.strip()} for l in text.splitlines() if l.strip().startswith("http")]
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    return list(csv.DictReader(text.splitlines(), dialect=dialect))


def _title_from(url: str) -> str:
    """Titre provisoire tiré du nom du fichier (« LBM-essai-Sorgho.pdf » → « LBM essai Sorgho »)."""
    from urllib.parse import unquote

    name = unquote(url.rstrip("/").rsplit("/", 1)[-1]).rsplit(".", 1)[0]
    return re.sub(r"[_\-]+", " ", name).strip()


def import_catalog(path: Path, source: str, mapping: dict[str, str] | None = None) -> tuple[list[Document], int]:
    mapping = mapping or {}
    docs, skipped = [], 0
    for row in read_rows(path):
        url = _pick(row, "url", mapping)
        if not url or not str(url).startswith(("http://", "https://")):
            skipped += 1
            continue
        kw = _pick(row, "keywords", mapping)
        kws = [k.strip() for k in re.split(r"[;,|]", kw) if k.strip()] if isinstance(kw, str) else (kw or [])
        date = _pick(row, "date", mapping)
        desc = _pick(row, "description", mapping)
        given_title = str(_pick(row, "title", mapping) or "")
        docs.append(Document(id=doc_id_for(url), url=url, source=source,
                             title=str(_pick(row, "title", mapping) or "") or _title_from(url),
                             date=str(date)[:10] if date else None, keywords=kws,
                             licence=_pick(row, "licence", mapping),
                             kind=kind_of(str(url), _pick(row, "kind", mapping)),
                             meta={k: v for k, v in row.items() if isinstance(v, (str, int, float)) and len(str(v)) < 300}
                             | ({"description": str(desc)[:2000]} if desc else {})
                             | ({} if given_title else {"titre_provisoire": True})))
    return docs, skipped
