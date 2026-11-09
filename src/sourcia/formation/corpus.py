"""Le mini-corpus de la formation : SEULEMENT les documents sélectionnés, découpés en passages.

On y cherche les passages utiles à chaque séquence ; ce sont eux, numérotés [1], [2]…, que le
modèle reçoit et doit citer. Avec un modèle en ligne, les documents privés sont exclus."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sourcia.extract.pdf import chunks as make_chunks
from sourcia.extract.pdf import load_text
from sourcia.search.bm25 import BM25


@dataclass
class Passage:
    doc_id: str
    page: int
    text: str
    n: int = 0                   # numéro dans le prompt ([n])


class SelectionCorpus:
    def __init__(self, ctx, doc_ids: list[str], cloud: bool = False, allow_private: tuple[str, ...] = ()):
        """``allow_private`` : documents privés autorisés quand même vers le modèle en ligne (accord explicite)."""
        self.ctx = ctx
        s = ctx.settings
        self.docs = [d for d in (ctx.store.get(i) for i in dict.fromkeys(doc_ids)) if d is not None]
        blocked = [d for d in self.docs if d.private and cloud and d.id not in allow_private]
        self.excluded_private = blocked
        self.docs = [d for d in self.docs if d not in blocked]
        self.passages: list[Passage] = []
        for d in self.docs:
            data = load_text(d.id, ctx.text_dir)
            if data:
                for page, piece in make_chunks(data, s.extract.chunk_words, s.extract.overlap_words):
                    self.passages.append(Passage(d.id, page, piece))
        self.bm25 = BM25().fit([str(i) for i in range(len(self.passages))], [p.text for p in self.passages]) \
            if self.passages else None
        self.vectors = None
        try:
            if self.passages and ctx.embedder is not None:
                self.vectors = ctx.embedder.embed_documents([p.text for p in self.passages]).astype(np.float32)
        except Exception:                      # embeddings indisponibles : mots seuls
            self.vectors = None

    def search(self, query: str, k: int = 6, per_doc: int = 2) -> list[Passage]:
        """Passages les plus utiles (mots + sens, fusion RRF), au plus ``per_doc`` par document (diversité)."""
        if not self.passages:
            return []
        score: dict[int, float] = {}
        for r, (i, s) in enumerate(self.bm25.search(query, 50)):
            if s > 0:
                score[int(i)] = score.get(int(i), 0) + 1 / (60 + r + 1)
        if self.vectors is not None:
            sims = self.vectors @ self.ctx.embedder.embed_query(query)
            for r, i in enumerate(np.argsort(-sims)[:50]):
                if sims[i] >= self.ctx.settings.search.min_dense_sim:
                    score[int(i)] = score.get(int(i), 0) + 1 / (60 + r + 1)
        out, per = [], {}
        for i in sorted(score, key=lambda j: -score[j]):
            p = self.passages[i]
            if per.get(p.doc_id, 0) >= per_doc:
                continue
            per[p.doc_id] = per.get(p.doc_id, 0) + 1
            out.append(Passage(p.doc_id, p.page, p.text, n=len(out) + 1))
            if len(out) >= k:
                break
        return out

    def title(self, doc_id: str) -> str:
        d = self.ctx.store.get(doc_id)
        return d.title if d else doc_id


def prompt_block(passages: list[Passage], corpus: SelectionCorpus) -> str:
    return "\n\n".join(f"[{p.n}] ({corpus.title(p.doc_id)}, p. {p.page})\n{p.text}" for p in passages)
