"""Assemblage des modules (construction paresseuse : rien n'est chargé tant qu'on n'en a pas besoin)."""
from __future__ import annotations

from functools import cached_property

from sourcia.collect.store import DocumentStore
from sourcia.config import Settings, load_settings
from sourcia.observability.tracing import configure_tracer


class Context:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or load_settings()
        configure_tracer(self.settings.path("traces", "traces.jsonl") if self.settings.observability.traces else None,
                         self.settings.observability.traces)

    @cached_property
    def store(self) -> DocumentStore:
        return DocumentStore(self.settings.path("documents.jsonl"))

    @cached_property
    def llm(self):
        from sourcia.llm.factory import build_llm

        return build_llm(self.settings)

    @cached_property
    def embedder(self):
        from sourcia.search.embedders import build_embedder

        return build_embedder(self.settings)

    @cached_property
    def reranker(self):
        kind = self.settings.search.reranker
        if kind == "none":
            return None
        from sourcia.search.rerank import CrossEncoderReranker, LexicalReranker

        if kind == "lexical":
            return LexicalReranker()
        s = self.settings.search
        return CrossEncoderReranker(s.reranker_model, path=self.settings.model_path(s.reranker_model),
                                    max_length=s.rerank_max_length)

    @cached_property
    def index(self):
        from sourcia.search.index import SearchIndex

        idx = SearchIndex(self.settings, self.embedder, self.reranker)
        idx.load()
        return idx

    @cached_property
    def qualifier(self):
        from sourcia.qualify.pipeline import Qualifier

        return Qualifier(self.settings, self.llm if self.settings.qualify.llm_pass else None)

    @cached_property
    def selector(self):
        from sourcia.select.funnel import Selector

        return Selector(self.settings, self.store, self.index, self.qualifier)

    @property
    def text_dir(self):
        return self.settings.path("text", ".keep").parent

    @property
    def pdf_dir(self):
        return self.settings.path("pdfs", ".keep").parent
