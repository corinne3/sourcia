"""Configuration centralisée : un fichier YAML par environnement (local, cloud, tests).

Changer de modèle ou de fournisseur = changer de fichier, pas le code (architecture hexagonale).
Chaque mesure enregistre l'empreinte de sa configuration (reproductibilité).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]


class LLMSettings(BaseModel):
    provider: Literal["ollama", "litellm", "fake"] = "ollama"
    model: str = "qwen2.5:1.5b"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.0
    num_ctx: int = 4096
    max_tokens: int = 600
    timeout_s: float = 300.0
    repeat_penalty: float = 1.15          # Ollama : pénalise les répétitions (boucles des petits modèles)
    cache: bool = True


class EmbedderSettings(BaseModel):
    kind: Literal["hashing", "sentence-transformers", "ollama"] = "sentence-transformers"
    model: str = "intfloat/multilingual-e5-small"
    dim: int = 512
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "


class CollectSettings(BaseModel):
    user_agent: str = "SourcIA/0.1 (outil de recherche documentaire, hackathon SAED)"
    delay_s: float = 1.0                 # politesse : au moins 1 s entre deux requêtes vers un même site
    timeout_s: float = 30.0
    max_pages_per_site: int = 300        # pages HTML visitées pour trouver des PDF
    max_pdfs_per_site: int = 500
    max_pdf_mb: float = 30.0
    respect_robots: bool = True
    download_pdfs: bool = True           # False : on ne garde que les liens (indexation par titre seulement)


class ExtractSettings(BaseModel):
    first_pages: int = 3                 # la qualification lit d'abord les premières pages (frugalité)
    index_pages: int = 5                 # pages indexées pour la recherche (titre + début du document)
    max_pages: int = 40                  # au-delà, on n'extrait pas (gros rapports)
    chunk_words: int = 200
    overlap_words: int = 40


class QualifySettings(BaseModel):
    llm_pass: bool = True                # passe 2 : lecture courte par le modèle
    max_chars: int = 6000                # texte donné au modèle (≈ 1 500 mots)
    min_evidence_overlap: float = 0.6    # une preuve doit se retrouver dans le texte (garde-fou)
    recent_year: int = 2022              # avant : alerte « résultats antérieurs aux sécheresses récentes »
    old_regulation_terms: list[str] = Field(default_factory=lambda: ["glyphosate", "néonicotinoïde"])


class SearchSettings(BaseModel):
    k_candidates: int = 300              # passe 1 : candidats issus de la recherche
    rrf_k: int = 60
    dense_only_margin: float | None = None  # document trouvé par le sens seul : gardé si sim ≥ meilleure − marge
    min_dense_sim: float = 0.0           # seuil de similarité (sens) : en dessous, un passage n'est pas candidat.
                                         # Dépend du modèle d'embeddings : à calibrer avec « sourcia search » (colonne sim)
    reranker: Literal["none", "lexical", "cross-encoder"] = "lexical"
    reranker_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    rerank_top: int = 60
    rerank_max_length: int = 256
    synonyms_file: str = "config/synonymes.yaml"


class SelectSettings(BaseModel):
    n: int = 50                          # limite de sources d'un carnet NotebookLM gratuit
    max_per_source: int = 12             # diversité : pas plus de N documents d'un même organisme
    weight_relevance: float = 0.6
    weight_recency: float = 0.2
    weight_quality: float = 0.2


class ObservabilitySettings(BaseModel):
    traces: bool = True
    energy: Literal["estimate", "codecarbon", "off"] = "estimate"
    cpu_watts: float = 25.0
    grid_gco2_per_kwh: float = 50.0


class Settings(BaseModel):
    name: str = "local"
    data_dir: str = "data"
    models_dir: str = "models"
    referentiels: str = "config/referentiels"      # référentiels des diplômes (M8)
    formation_threshold: float = 0.65              # M7 : part des mots d'une phrase à retrouver dans sa source
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedder: EmbedderSettings = Field(default_factory=EmbedderSettings)
    collect: CollectSettings = Field(default_factory=CollectSettings)
    extract: ExtractSettings = Field(default_factory=ExtractSettings)
    qualify: QualifySettings = Field(default_factory=QualifySettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    select: SelectSettings = Field(default_factory=SelectSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)

    def resolve(self, p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else REPO_ROOT / p

    @property
    def data(self) -> Path:
        d = self.resolve(self.data_dir)
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def referentiels_dir(self) -> Path:
        return self.resolve(self.referentiels)

    def path(self, *parts: str) -> Path:
        p = self.data.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def model_path(self, name: str) -> str | None:
        local = self.resolve(self.models_dir) / name.replace("/", "__")
        return str(local) if local.exists() else None

    @property
    def fingerprint(self) -> str:
        raw = json.dumps(self.model_dump(exclude={"name", "data_dir", "models_dir", "referentiels"}), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


def load_settings(path: str | Path | None = None) -> Settings:
    path = path or os.environ.get("SOURCIA_CONFIG") or REPO_ROOT / "config" / "local.yaml"
    path = Path(path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    return Settings(**(data or {}))
