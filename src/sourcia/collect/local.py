"""Documents locaux : un dossier de PDF ou de textes (essais non publiés, ancien support du formateur).

Les documents ``private=True`` ne sont JAMAIS envoyés à un modèle en ligne (voir qualify/llm.py)."""
from __future__ import annotations

from pathlib import Path

from sourcia.collect.media import EXT_KIND
from sourcia.collect.store import file_sha1
from sourcia.core.models import Document, doc_id_for

EXTENSIONS = set(EXT_KIND)          # PDF et textes, mais aussi données, photos, vidéos, audio


def scan_folder(folder: Path, source: str = "prive", private: bool = True) -> list[Document]:
    docs = []
    for p in sorted(folder.rglob("*")):
        if p.suffix.lower() in EXTENSIONS and p.is_file():
            url = p.resolve().as_uri()
            docs.append(Document(id=doc_id_for(url), url=url, source=source, title=p.stem.replace("_", " "),
                                 private=private, local_path=str(p.resolve()), sha1=file_sha1(p),
                                 kind=EXT_KIND[p.suffix.lower()], status="downloaded"))
    return docs
