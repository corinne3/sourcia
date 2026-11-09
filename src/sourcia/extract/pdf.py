"""Extraction du texte (M2) : PDF, texte, HTML. D'abord les premières pages (frugalité).

Sortie : ``data/text/<id>.json`` = {"pages": [...], "n_pages": N, "meta": {...}}.
Un PDF scanné (sans texte) est signalé : il faudrait de l'OCR, non activé par défaut.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from sourcia.core.models import Document
from sourcia.observability.tracing import span


def clean(text: str) -> str:
    text = text.replace("­", "")                        # tirets conditionnels
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)              # mots coupés en fin de ligne
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf_pages(path: Path, max_pages: int) -> tuple[list[str], int, dict]:
    try:
        import pymupdf as fitz  # PyMuPDF : plus rapide et plus fidèle (nom actuel du module)
    except ImportError:
        try:
            import fitz  # anciennes versions de PyMuPDF
        except ImportError:
            fitz = None
    if fitz is not None:
        with fitz.open(path) as pdf:
            n = pdf.page_count
            pages = [clean(pdf[i].get_text("text")) for i in range(min(n, max_pages))]
            meta = {k: v for k, v in (pdf.metadata or {}).items() if v}
        return pages, n, meta
    from pypdf import PdfReader  # repli : pur Python

    r = PdfReader(str(path))
    n = len(r.pages)
    pages = [clean(r.pages[i].extract_text() or "") for i in range(min(n, max_pages))]
    meta = {k.lstrip("/").lower() if k != "/CreationDate" else "creationDate": str(v)
            for k, v in (r.metadata or {}).items() if v}
    return pages, n, meta


def _html_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return clean(html.unescape(raw))


def metadata_text(doc: Document) -> str:
    """Texte construit à partir des métadonnées (vidéo, photo, données sans fichier lisible)."""
    m = doc.meta or {}
    parts = [doc.title, m.get("description", ""), f"Page d'origine : {m['titre_page']}" if m.get("titre_page") else "",
             f"Mots-clés : {', '.join(doc.keywords)}" if doc.keywords else "", f"Date : {doc.date}" if doc.date else ""]
    return "\n".join(p for p in parts if p)


def extract(doc: Document, out_dir: Path, max_pages: int) -> dict:
    """Extrait le texte d'un document téléchargé ou local. Met à jour le statut du document.

    Ressources non textuelles : données → description des colonnes ; audio/vidéo locale → transcription si
    faster-whisper est installé ; sinon (photo, vidéo en ligne…) → MÉTADONNÉES seules (signalé)."""
    from sourcia.collect.media import describe_table, transcribe

    if doc.kind in ("donnees", "image", "video", "audio") or not doc.local_path:
        if not doc.local_path and doc.kind == "pdf":
            raise ValueError("document non téléchargé")
        text, only_meta = metadata_text(doc), True
        p = Path(doc.local_path) if doc.local_path else None
        if p and p.exists() and doc.kind == "donnees":
            text, only_meta = text + "\n" + describe_table(p), False
        elif p and p.exists() and doc.kind in ("audio", "video"):
            tr = transcribe(p)
            if tr:
                text, only_meta = text + "\nTranscription : " + tr, False
        result = {"pages": [clean(text)], "n_pages": 1, "meta": {"metadonnees_seules": only_meta, "kind": doc.kind},
                  "scanned": False}
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{doc.id}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        doc.meta["metadonnees_seules"] = only_meta
        doc.status = "extracted"
        return result
    path = Path(doc.local_path)
    with span("extract", doc=doc.id):
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            pages, n, meta = _pdf_pages(path, max_pages)
        else:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            text = _html_text(raw) if suffix in (".html", ".htm") else clean(raw)
            pages = [p for p in re.split(r"\n\s*\f\s*\n|\f", text) if p.strip()] or [text]
            n, meta = len(pages), {}
        result = {"pages": pages, "n_pages": n, "meta": meta,
                  "scanned": suffix == ".pdf" and sum(len(p) for p in pages[:3]) < 200}   # une note courte n'est pas un scan
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{doc.id}.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    if (not doc.title or doc.meta.get("titre_provisoire")) and len(str(meta.get("title", "")).strip()) >= 8:
        doc.title = str(meta["title"]).strip()
        doc.meta.pop("titre_provisoire", None)
    elif doc.meta.get("titre_provisoire") and pages:
        # titre tiré du nom de fichier (« 1608792721 20rap01p… ») : on prend la première ligne parlante du document
        line = next((l.strip() for l in pages[0].splitlines()
                     if 15 <= len(l.strip()) <= 140 and sum(c.isalpha() for c in l) > 10), None)
        if line:
            doc.title = line
            doc.meta.pop("titre_provisoire", None)
    if not doc.date:
        m = re.match(r"D:(\d{4})", meta.get("creationDate", "") or "")
        if m:
            doc.meta["annee_fichier"] = int(m.group(1))       # indice faible : date de création du fichier
    doc.status = "extracted"
    return result


def load_text(doc_id: str, out_dir: Path) -> dict | None:
    p = out_dir / f"{doc_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def first_pages_text(text: dict, n: int) -> str:
    return "\n\n".join(text["pages"][:n])


def chunks(text: dict, words: int, overlap: int) -> list[tuple[int, str]]:
    """Découpe page par page en morceaux de ``words`` mots (avec chevauchement)."""
    out = []
    step = max(1, words - overlap)
    for i, page in enumerate(text["pages"], start=1):
        toks = page.split()
        for start in range(0, max(1, len(toks)), step):
            piece = " ".join(toks[start:start + words])
            if len(piece.split()) >= 15:
                out.append((i, piece))
            if start + words >= len(toks):
                break
    return out
