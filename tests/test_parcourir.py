"""Parcourir le catalogue depuis un dossier : une liste filtrable au lieu d'une case de recherche vide."""
from __future__ import annotations

import pytest

from conftest import ROOT


# ---------------------------------------------------------------------- thèmes des fiches
def test_themes_ignore_the_word_mais_and_word_pieces():
    """Vu le 23/11 : 121 documents classés « maïs » à cause de la conjonction « mais », « foin » dans « sainfoin »."""
    from sourcia.qualify.pipeline import THEMES_VOCAB
    from sourcia.qualify.rules import themes_of

    assert themes_of("Les modèles s'améliorent mais gardent une part d'incertitude. Le sainfoin pousse.",
                     [], THEMES_VOCAB) == []
    assert themes_of("Le MAÏS ensilage et la production fourragère ; les foins de prairies.", [], THEMES_VOCAB) == \
        ["ensilage", "foin", "fourrage", "maïs", "prairie"]
    assert themes_of("Texte sans thème.", ["sorgho"], THEMES_VOCAB) == ["sorgho"]       # mots-clés de la source gardés


def test_themes_can_be_recomputed_without_the_model(demo_ctx, capsys, monkeypatch):
    from sourcia.cli import main

    doc = next(d for d in demo_ctx.store.canonical() if demo_ctx.qualifier.get(d.id))
    fiche = demo_ctx.qualifier.get(doc.id)
    fiche.themes = ["maïs", "thème faux"]
    organisme = fiche.organisme.value
    demo_ctx.qualifier.save()
    demo_ctx.store.save()                                                    # la commande relit les fichiers
    cfg = demo_ctx.settings
    path = ROOT / "config" / "test.yaml"
    monkeypatch.setenv("SOURCIA_DATA_DIR", str(cfg.data))
    main(["-c", str(path), "qualify", "--themes"])
    assert "Thèmes recalculés" in capsys.readouterr().out
    from sourcia.container import Context
    again = Context(cfg).qualifier.get(doc.id)
    assert "thème faux" not in again.themes and again.organisme.value == organisme     # le reste de la fiche gardé


# ---------------------------------------------------------------------- la route
@pytest.fixture
def client(demo_ctx, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sourcia.api.app import create_app
    from sourcia.comptes import Comptes

    monkeypatch.setenv("SOURCIA_DOSSIER_ACCOUNTS", "{}")
    c = TestClient(create_app(ctx=demo_ctx))
    token = Comptes(demo_ctx.settings.path("comptes.json")).ajouter("prof@lycee.fr")
    c.headers["Authorization"] = f"Bearer {token}"
    c.folder = c.post("/api/dossiers", json={"title": "Sorgho"}).json()["id"]
    c.ctx = demo_ctx
    return c


def browse(client, **params):
    r = client.get(f"/api/dossiers/{client.folder}/parcourir-catalogue", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_list_without_typing_anything(client):
    data = browse(client)
    public = [d for d in client.ctx.store.canonical() if not d.private and d.status != "error"]
    assert data["total"] == len(public) > 0 and len(data["documents"]) == min(20, len(public))
    years = [d["annee"] or "" for d in data["documents"]]
    assert years == sorted(years, reverse=True)                              # les plus récents d'abord
    assert data["themes"] and data["sources"] and all(t["n"] > 0 for t in data["themes"])
    first = data["documents"][0]
    assert {"id", "titre", "source_nom", "annee", "themes", "deja_ajoute"} <= set(first)


def test_private_documents_are_never_listed(client):
    private = {d.id for d in client.ctx.store if d.private}
    assert private                                                           # l'exemple en a
    assert not private & {d["id"] for d in browse(client, par_page=50)["documents"]}


def test_filters_theme_source_words_and_pages(client):
    data = browse(client)
    theme = data["themes"][0]["nom"]
    by_theme = browse(client, theme=theme, par_page=50)
    assert by_theme["total"] == data["themes"][0]["n"] and all(theme in d["themes"] for d in by_theme["documents"])
    titles = [theme in d["titre"].lower() for d in by_theme["documents"]]
    assert titles == sorted(titles, reverse=True)                            # le thème dans le titre d'abord
    source = data["sources"][0]["id"]
    assert all(d["source"] == source for d in browse(client, source=source)["documents"])
    words = browse(client, q="sorgho")
    assert words["total"] >= 1 and "sorgho" in (words["documents"][0]["titre"] + " ".join(
        words["documents"][0]["themes"])).lower()
    one = browse(client, par_page=1, page=2)
    assert len(one["documents"]) == 1 and one["documents"][0]["id"] == data["documents"][1]["id"]
    assert browse(client, page=99)["documents"] == []


def test_document_already_in_the_folder_is_marked(client):
    doc = browse(client)["documents"][0]
    assert not doc["deja_ajoute"]
    assert client.post(f"/api/dossiers/{client.folder}/catalogue", json={"document_id": doc["id"]}).status_code == 202
    assert next(d for d in browse(client)["documents"] if d["id"] == doc["id"])["deja_ajoute"]


def test_only_the_folder_owner_can_browse(client):
    del client.headers["Authorization"]
    assert client.get(f"/api/dossiers/{client.folder}/parcourir-catalogue").status_code == 401
