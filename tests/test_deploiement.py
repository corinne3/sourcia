"""Mise en ligne (phase 4) : configuration du serveur, mode serveur (connexion obligatoire), image Docker."""
from __future__ import annotations

import pytest

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


# ---------------------------------------------------------------------- mode serveur
SECRET = "secret-de-test-" + "x" * 32


@pytest.fixture
def server(demo_ctx, monkeypatch):
    """L'app comme en ligne : mode serveur, un compte enseignant, le catalogue d'exemple."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sourcia.api.app import create_app
    from sourcia.comptes import Comptes

    monkeypatch.setenv("SOURCIA_DOSSIER_ACCOUNTS", "{}")
    monkeypatch.setenv("SOURCIA_SESSION_SECRET", SECRET)
    demo_ctx.settings.serveur = True
    client = TestClient(create_app(ctx=demo_ctx))
    client.token = Comptes(demo_ctx.settings.path("comptes.json")).ajouter("prof@lycee.fr")
    return client


def demande(**kw):
    from sourcia.core.demande import Demande

    return Demande(sujet="sorgho fourrager", **kw).model_dump(mode="json")


def test_visitor_can_search_but_not_call_the_model(server):
    r = server.post("/api/selection", json={"demande": demande(), "formats": ["md", "csv"]})
    assert r.status_code == 200 and r.json()["documents"] and r.json()["exports"] == []   # rien d'écrit
    assert server.post("/api/selection", json={"demande": demande(), "llm_top": 5}).status_code == 401
    r = server.post("/api/formation", json={"demande": demande(), "doc_ids": ["x"]})
    assert r.status_code == 401 and "Connectez-vous" in r.json()["detail"]
    assert server.post("/api/supports", json={"corpus_id": "corpus-20261120-100000"}).status_code == 401
    assert server.post("/api/formation/x/rattachements", json={"valideur": "v", "decisions": []}).status_code == 401
    assert server.get("/api/recherche", params={"q": "sorgho"}).status_code == 200
    assert server.get("/api/etat").status_code == 200 and server.get("/").status_code == 200


def test_logged_teacher_passes_with_the_session_cookie(server):
    r = server.post("/api/dossiers/session", json={"jeton": server.token})
    assert r.status_code == 200 and "Path=/api;" in r.headers["set-cookie"]
    # la connexion passe : on arrive aux contrôles suivants (aucun document, corpus inconnu)
    assert server.post("/api/formation", json={"demande": demande(), "doc_ids": []}).status_code == 400
    assert server.post("/api/supports", json={"corpus_id": "corpus-20261120-100000"}).status_code == 404
    r = server.post("/api/selection", json={"demande": demande(), "formats": ["md"]})
    assert r.status_code == 200 and r.json()["exports"]                              # exports pour l'enseignant
    server.cookies.clear()
    headers = {"Authorization": f"Bearer {server.token}"}                            # ou par le jeton
    assert server.post("/api/formation", json={"demande": demande(), "doc_ids": []}, headers=headers).status_code == 400


def test_server_refuses_to_start_without_session_secret(demo_ctx, monkeypatch):
    from sourcia.api.app import create_app

    demo_ctx.settings.serveur = True
    monkeypatch.delenv("SOURCIA_SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SOURCIA_SESSION_SECRET"):
        create_app(ctx=demo_ctx)
    monkeypatch.setenv("SOURCIA_SESSION_SECRET", "trop-court")
    with pytest.raises(RuntimeError, match="32 caractères"):
        create_app(ctx=demo_ctx)


def test_on_a_pc_nothing_changes(demo_ctx, monkeypatch):
    """Sans le mode serveur (sur son PC), pas de connexion demandée ni de secret obligatoire."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sourcia.api.app import create_app

    monkeypatch.delenv("SOURCIA_SESSION_SECRET", raising=False)
    client = TestClient(create_app(ctx=demo_ctx))
    assert client.post("/api/formation", json={"demande": demande(), "doc_ids": []}).status_code == 400
    assert client.post("/api/selection", json={"demande": demande(), "formats": ["md"]}).json()["exports"]


# ---------------------------------------------------------------------- image Docker
def test_docker_image_has_no_secret_and_no_data():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert {".env", "data/", ".venv/", ".git/"} <= set(ignore) and "!.env.example" in ignore
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER sourcia" in docker and "SOURCIA_CONFIG=config/serveur.yaml" in docker   # pas administrateur
    assert "HEALTHCHECK" in docker and "/api/etat" in docker and "${PORT:-8000}" in docker
    assert "GEMINI_API_KEY=" not in docker and "COPY .env" not in docker and "COPY data" not in docker
    assert "sentence-transformers" not in docker and "[api,cloud,pptx,word]" in docker  # image légère
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "sourcia-data:/data" in compose and "required: false" in compose
    assert "SOURCIA_SESSION_SECRET=" in (ROOT / ".env.example").read_text(encoding="utf-8")


def test_session_secret_can_come_from_dot_env(tmp_path, monkeypatch):
    from sourcia.cli import _load_cloud_keys

    monkeypatch.setenv("SOURCIA_SESSION_SECRET", "x")              # pour que monkeypatch remette tout à la fin
    monkeypatch.delenv("SOURCIA_SESSION_SECRET")
    (tmp_path / ".env").write_text("SOURCIA_SESSION_SECRET=abc\nAUTRE=non\n", encoding="utf-8")
    _load_cloud_keys(tmp_path / ".env")
    import os
    assert os.environ["SOURCIA_SESSION_SECRET"] == "abc" and "AUTRE" not in os.environ


# ---------------------------------------------------------------------- paquet du catalogue
def paquet_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("catalogue_paquet", ROOT / "scripts/catalogue_paquet.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_catalogue_package_has_no_pdf_and_no_pc_path(tmp_path):
    import json
    import tarfile

    cp = paquet_module()
    data = tmp_path / "data"
    (data / "pages").mkdir(parents=True)
    (data / "pdfs").mkdir()
    (data / "dossiers").mkdir()
    (data / "pages" / "p1.txt").write_text("Le sorgho fourrager.", encoding="utf-8")
    (data / "pdfs" / "d2.pdf").write_bytes(b"%PDF-1.4")
    (data / "comptes.json").write_text("{}", encoding="utf-8")
    docs = [{"id": "p1", "kind": "page", "local_path": r"C:\Users\Prof\saed\data\pages\p1.txt"},
            {"id": "d2", "kind": "pdf", "local_path": r"C:\Users\Prof\saed\data\pdfs\d2.pdf"}]
    (data / "documents.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs), encoding="utf-8")
    (data / "fiches.jsonl").write_text("", encoding="utf-8")
    out = tmp_path / "catalogue.tar.gz"
    r = cp.create(data, out)
    assert r["documents"] == 2 and r["pdf_a_retelecharger"] == 1
    with tarfile.open(out) as tar:
        names = tar.getnames()
        packed = tar.extractfile("documents.jsonl").read().decode()
    assert "pages/p1.txt" in names and not any(n.endswith(".pdf") or "comptes" in n or "dossiers" in n for n in names)
    assert "Users" not in packed and "Prof" not in packed                    # rien de son ordinateur

    vol = tmp_path / "volume"
    assert cp.import_(out, vol)["documents"] == 2
    got = {d["id"]: d["local_path"] for d in map(json.loads, (vol / "documents.jsonl").read_text("utf-8").splitlines())}
    assert got["p1"] == str((vol / "pages" / "p1.txt").resolve()) and got["d2"] is None   # PDF retéléchargé
    with pytest.raises(SystemExit, match="déjà un catalogue"):
        cp.import_(out, vol)                                                 # pas d'écrasement par erreur
    cp.import_(out, vol, replace=True)


def test_suspicious_package_is_refused(tmp_path):
    import io
    import tarfile

    cp = paquet_module()
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../comptes.json")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(SystemExit, match="suspecte"):
        cp.import_(evil, tmp_path / "volume")
    assert not (tmp_path / "comptes.json").exists()


def test_empty_catalogue_is_announced_on_the_page():
    page = (ROOT / "src/sourcia/api/static/index.html").read_text(encoding="utf-8")
    assert "Le catalogue est vide" in page
