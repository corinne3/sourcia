"""Le catalogue des documents (``documents.jsonl``) : ajout, mise à jour, doublons."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sourcia.core.models import Document


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


class DocumentStore:
    def __init__(self, path: Path):
        self.path = path
        self.docs: dict[str, Document] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    d = Document.model_validate_json(line)
                    self.docs[d.id] = d

    def __len__(self) -> int:
        return len(self.docs)

    def __iter__(self):
        return iter(list(self.docs.values()))

    def get(self, doc_id: str) -> Document | None:
        return self.docs.get(doc_id)

    def add(self, doc: Document) -> bool:
        """Ajoute un document. Renvoie False si l'URL est déjà connue (les infos existantes sont complétées)."""
        old = self.docs.get(doc.id)
        if old is None:
            self.docs[doc.id] = doc
            return True
        for k in ("title", "date", "licence"):
            if not getattr(old, k) and getattr(doc, k):
                setattr(old, k, getattr(doc, k))
        old.keywords = sorted(set(old.keywords) | set(doc.keywords))
        return False

    def duplicates(self) -> dict[str, list[str]]:
        """Documents au contenu identique (même empreinte) publiés à plusieurs adresses."""
        by_hash: dict[str, list[str]] = {}
        for d in self.docs.values():
            if d.sha1:
                by_hash.setdefault(d.sha1, []).append(d.id)
        return {h: ids for h, ids in by_hash.items() if len(ids) > 1}

    def canonical(self) -> list[Document]:
        """Un seul document par contenu : on garde le premier vu, les autres sont des doublons."""
        seen, out = set(), []
        for d in self.docs.values():
            if d.sha1 and d.sha1 in seen:
                continue
            if d.sha1:
                seen.add(d.sha1)
            out.append(d)
        return out

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(d.model_dump_json() + "\n" for d in self.docs.values()), encoding="utf-8")
        tmp.replace(self.path)

    def stats(self) -> dict:
        by_source: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for d in self.docs.values():
            by_source[d.source] = by_source.get(d.source, 0) + 1
            by_status[d.status] = by_status.get(d.status, 0) + 1
        return {"documents": len(self.docs), "par_source": by_source, "par_statut": by_status,
                "doublons": sum(len(v) - 1 for v in self.duplicates().values())}


def dump_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
