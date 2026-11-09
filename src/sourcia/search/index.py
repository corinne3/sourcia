"""Recherche (M4) : index hybride au niveau des DOCUMENTS.

- chaque document est découpé en passages (titre + premières pages) ;
- deux recherches : par les mots (BM25, + synonymes du métier) et par le sens (embeddings) ;
- fusion par les rangs (RRF), puis score d'un document = son meilleur passage ;
- un document seulement listé (pas encore téléchargé) reste trouvable par son titre et ses mots-clés.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from sourcia.core.models import Chunk, Hit
from sourcia.core.text import normalize
from sourcia.extract.pdf import chunks as make_chunks
from sourcia.extract.pdf import load_text
from sourcia.observability.tracing import span
from sourcia.search.bm25 import BM25


@dataclass
class DocHit:
    doc_id: str
    score: float
    passage: str
    page: int
    ranks: dict


def load_synonyms(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [[str(w) for w in g] for g in data.get("groupes", [])]


def expand_query(query: str, groups: list[list[str]]) -> str:
    """Ajoute les synonymes connus (« fissurateur » → « décompacteur ») à la requête lexicale."""
    q = normalize(query)
    extra = []
    for g in groups:
        if any(normalize(w) in q for w in g):
            extra += [w for w in g if normalize(w) not in q]
    return query + (" " + " ".join(extra) if extra else "")


class SearchIndex:
    def __init__(self, settings, embedder=None, reranker=None):
        self.settings = settings
        self.embedder = embedder
        self.reranker = reranker
        e = settings.embedder                 # un index par modèle d'embeddings (vecteurs incompatibles entre eux)
        slug = f"hashing-{e.dim}" if e.kind == "hashing" else f"{e.kind}-{e.model}".replace("/", "_").replace(":", "_")
        self.dir = settings.path("index", slug, ".keep").parent
        self.chunks: list[Chunk] = []
        self.bm25: BM25 | None = None
        self.vectors: np.ndarray | None = None
        self.synonyms = load_synonyms(settings.resolve(settings.search.synonyms_file))

    # ------------------------------------------------------------------ construction
    def build(self, documents) -> dict:
        cfg = self.settings.extract
        text_dir = self.settings.path("text", ".keep").parent
        chunks: list[Chunk] = []
        for d in documents:
            head = " ".join(x for x in [d.title, " ".join(d.keywords)] if x).strip()
            if head:
                chunks.append(Chunk(id=f"{d.id}#t", doc_id=d.id, text=head, page=0))
            data = load_text(d.id, text_dir)
            if data:
                data = {**data, "pages": data["pages"][: cfg.index_pages]}
                for i, (page, piece) in enumerate(make_chunks(data, cfg.chunk_words, cfg.overlap_words)):
                    chunks.append(Chunk(id=f"{d.id}#{i}", doc_id=d.id, text=piece, page=page))
        with span("index.build", chunks=len(chunks)):
            self.chunks = chunks
            self.bm25 = BM25().fit([c.id for c in chunks], [c.text for c in chunks])
            self.vectors = (self.embedder.embed_documents([c.text for c in chunks]).astype(np.float32)
                            if self.embedder and chunks else None)
        self.save()
        return {"documents": len({c.doc_id for c in chunks}), "passages": len(chunks),
                "dense": self.vectors is not None}

    def save(self) -> None:
        (self.dir / "chunks.jsonl").write_text(
            "".join(json.dumps(c.__dict__, ensure_ascii=False) + "\n" for c in self.chunks), encoding="utf-8")
        if self.bm25:
            self.bm25.save(self.dir / "bm25.json")
        if self.vectors is not None:
            np.save(self.dir / "vectors.npy", self.vectors)

    def load(self) -> bool:
        p = self.dir / "chunks.jsonl"
        if not p.exists():
            return False
        self.chunks = [Chunk(**json.loads(l)) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.bm25 = BM25.load(self.dir / "bm25.json")
        v = self.dir / "vectors.npy"
        self.vectors = np.load(v) if v.exists() and self.embedder else None
        return True

    # ------------------------------------------------------------------ recherche
    def search(self, query: str, k: int | None = None, mode: str = "hybrid") -> list[DocHit]:
        """Renvoie les documents classés (meilleur passage de chacun)."""
        k = k or self.settings.search.k_candidates
        if not self.chunks:
            return []
        n = min(len(self.chunks), max(k * 4, 200))
        rankings: dict[str, list[str]] = {}
        dense_sim: dict[str, float] = {}
        with span("search", query=query, mode=mode):
            if mode in ("hybrid", "bm25"):
                rankings["bm25"] = [cid for cid, s in self.bm25.search(expand_query(query, self.synonyms), n) if s > 0]
            if mode in ("hybrid", "dense") and self.vectors is not None:
                qv = self.embedder.embed_query(query)
                sims = self.vectors @ qv
                top = [i for i in np.argsort(-sims)[:n] if sims[i] >= self.settings.search.min_dense_sim]
                rankings["dense"] = [self.chunks[i].id for i in top]
                dense_sim = {self.chunks[i].id: round(float(sims[i]), 3) for i in top}
            by_id = {c.id: c for c in self.chunks}
            margin = self.settings.search.dense_only_margin
            if margin is not None and dense_sim and mode == "hybrid":
                # un document trouvé SEULEMENT par le sens doit être presque aussi proche que le meilleur :
                # avec e5, toutes les similarités sont serrées (0,80 à 0,92), un seuil absolu ne sépare rien
                word_docs = {by_id[cid].doc_id for cid in rankings.get("bm25", [])}
                top_sim = max(dense_sim.values())
                rankings["dense"] = [cid for cid in rankings["dense"]
                                     if by_id[cid].doc_id in word_docs or dense_sim[cid] >= top_sim - margin]
            rrf: dict[str, float] = {}
            rank_of: dict[str, dict] = {}
            for name, ids in rankings.items():
                for r, cid in enumerate(ids):
                    rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (self.settings.search.rrf_k + r + 1)
                    rank_of.setdefault(cid, {})[name] = r + 1
            best: dict[str, tuple[float, Chunk]] = {}
            for cid, s in rrf.items():
                c = by_id[cid]
                if c.doc_id not in best or s > best[c.doc_id][0]:
                    best[c.doc_id] = (s, c)
            ordered = sorted(best.values(), key=lambda x: -x[0])[:k]
            if self.reranker is not None and ordered:
                top_n = self.settings.search.rerank_top
                hits = [Hit(chunk=c, score=s) for s, c in ordered[:top_n]]
                rer = self.reranker.rerank(query, hits, top_n)
                lo = [Hit(chunk=c, score=s) for s, c in ordered[top_n:]]
                ordered = [(h.score, h.chunk) for h in rer] + [(h.score, h.chunk) for h in lo]
        out = []
        for s, c in ordered:
            out.append(DocHit(doc_id=c.doc_id, score=float(s), passage=c.text, page=c.page, ranks=rank_of.get(c.id, {}) | ({"sim": dense_sim[c.id]} if c.id in dense_sim else {})))
        # score de pertinence normalisé dans [0, 1] (rang), utile pour la sélection
        n_out = len(out)
        for i, h in enumerate(out):
            h.score = 1.0 - i / max(1, n_out)
        return out
