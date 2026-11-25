"""Prise en main : un seul chemin (le catalogue ajoute au dossier), un exemple prêt, des mots simples, la limite
visible à l'avance, les essais de supports qu'on peut supprimer."""
from __future__ import annotations

import json

import pytest

from sourcia.comptes import Quotas

from conftest import ROOT

STATIC = ROOT / "src" / "sourcia" / "api" / "static"
SECRET = "secret-de-test-" + "x" * 32


@pytest.fixture
def visitor(demo_ctx, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sourcia.api.app import create_app

    monkeypatch.setenv("SOURCIA_DOSSIER_ACCOUNTS", "{}")
    monkeypatch.setenv("SOURCIA_SESSION_SECRET", SECRET)
    demo_ctx.settings.acces_libre = True
    c = TestClient(create_app(ctx=demo_ctx))
    c.ctx = demo_ctx
    return c


def test_example_folder_is_ready_to_use(visitor):
    r = visitor.post("/api/dossiers/exemple")
    assert r.status_code == 201 and r.json()["documents"] >= 1
    folder = r.json()["id"]
    detail = visitor.get(f"/api/dossiers/{folder}").json()
    assert detail["title"].startswith("Exemple") and detail["documents"]
    assert all(d["selected"] for d in detail["documents"])                     # déjà cochés pour la suite
    assert not any(d["private"] for d in detail["documents"])                  # seulement des documents publics


def test_remaining_quota_is_shown_before_the_limit(visitor, tmp_path):
    s = visitor.get("/api/dossiers/session").json()
    assert s["visiteur"] and s["reste"] == {"corpus": 3, "supports": 3}
    q = Quotas(tmp_path / "q.json", {"corpus": 3, "supports": 3})
    q.use("visiteur-1@visiteur.sourcia", "corpus")
    assert q.remaining("visiteur-1@visiteur.sourcia") == {"corpus": 2, "supports": 3}
    assert q.remaining("prof@lycee.fr") is None                                # jeton : pas de limite


def test_command_line_production_is_listed_and_can_be_deleted(demo_ctx, tmp_path):
    from sourcia.api.supports_api import SupportsJobs

    corpus = tmp_path / "corpus-20261125-100000"
    folder = corpus / "supports" / "supports-20261125-120000"
    folder.mkdir(parents=True)
    (folder / "qcm_eleves.html").write_text("<html></html>", encoding="utf-8")
    (folder / "supports.json").write_text(json.dumps({"cree_le": "2026-11-25T12:00:00", "sequences": [1],
                                                      "supports": ["qcm"], "fichiers": ["qcm_eleves.html"],
                                                      "qcm": []}), encoding="utf-8")
    jobs = SupportsJobs(demo_ctx)
    [item] = jobs.list(corpus)
    assert item["statut"] == "pret" and item["cree_le"] and item["fichiers"] == ["qcm_eleves.html"]   # plus de « ? »
    assert jobs.file(corpus, item["id"], "qcm_eleves.html").status_code == 200   # nouvelle page servie
    jobs.delete(corpus, item["id"])
    assert jobs.list(corpus) == []


def test_catalogue_page_adds_to_a_folder_instead_of_a_second_path():
    page = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Ajouter à mon dossier" in page and 'id="dossier-cible"' in page and "/catalogue`" in page
    assert "Créer la formation" not in page and 'id="fpanel"' not in page     # l'ancien parcours a disparu
    options = page[page.index('<details class="search-options">'):page.index("</details>")]
    assert 'id="llm_top"' in options                                            # réglage technique rangé


def test_folder_page_guides_the_first_visit_in_plain_words():
    page = (STATIC / "dossiers.html").read_text(encoding="utf-8")
    js = (STATIC / "parcours.js").read_text(encoding="utf-8")
    assert 'id="bienvenue"' in page and 'id="exemple"' in page and "base + '/exemple'" in page
    assert ">Mon contenu<" in page and ">Mon corpus<" not in page and "Préparer le contenu" in page
    assert "il vous reste" in page and "refreshAccount" in js
    assert "Supprimer cette production" in js and "method: 'DELETE'" in js
    assert "sujet.value = (detail.title" in js                                  # sujet pré-rempli
