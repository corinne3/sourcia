"""Fabrique du client LLM selon la configuration (local Ollama, cloud LiteLLM, factice pour les tests)."""
from __future__ import annotations

from sourcia.config import Settings


def build_llm(settings: Settings, cache: bool | None = None):
    cfg = settings.llm
    if cfg.provider == "fake":
        from sourcia.llm.fake import FakeLLM

        llm = FakeLLM(model="fake")
    elif cfg.provider == "litellm":
        from sourcia.llm.litellm_client import LiteLLMClient

        llm = LiteLLMClient(cfg.model, cfg.temperature, cfg.max_tokens, cfg.timeout_s)
    else:
        from sourcia.llm.ollama import OllamaClient

        llm = OllamaClient(cfg.model, cfg.base_url, cfg.temperature, cfg.num_ctx, cfg.max_tokens, cfg.timeout_s,
                           repeat_penalty=cfg.repeat_penalty)
    use_cache = cfg.cache if cache is None else cache
    if use_cache and cfg.provider != "fake":
        from sourcia.llm.cache import CachedLLM

        llm = CachedLLM(llm, settings.path("cache", "llm.sqlite"))
    return llm
