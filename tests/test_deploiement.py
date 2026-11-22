"""Mise en ligne (phase 4) : configuration du serveur."""
from __future__ import annotations

from sourcia.config import load_settings

from conftest import ROOT


def test_server_config_is_light_and_uses_the_volume(monkeypatch):
    monkeypatch.delenv("SOURCIA_DATA_DIR", raising=False)
    s = load_settings(ROOT / "config/serveur.yaml")
    assert s.llm.provider == "litellm" and s.llm.model.startswith("gemini/")
    assert s.embedder.kind == "hashing"                      # pas de PyTorch dans l'image
    assert s.data_dir == "/data" and not s.qualify.llm_pass
    text = (ROOT / "config/serveur.yaml").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY" in text and "AIza" not in text   # la clé est nommée, jamais écrite


def test_data_dir_can_be_given_by_the_host(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCIA_DATA_DIR", str(tmp_path / "volume"))
    assert load_settings(ROOT / "config/serveur.yaml").data == tmp_path / "volume"
    assert load_settings(ROOT / "config/test.yaml").data == tmp_path / "volume"
