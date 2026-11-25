"""Accès libre (prototype) : pas de jeton à saisir, un compte visiteur anonyme par navigateur, limité par jour."""
from __future__ import annotations

import pytest

from sourcia.comptes import COOKIE, Quotas, is_visitor

from conftest import ROOT

SECRET = "secret-de-test-" + "x" * 32


@pytest.fixture
def app_factory(demo_ctx, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sourcia.api.app import create_app

    monkeypatch.setenv("SOURCIA_DOSSIER_ACCOUNTS", "{}")
    monkeypatch.setenv("SOURCIA_SESSION_SECRET", SECRET)

    def make(**settings):
        for k, v in settings.items():
            setattr(demo_ctx.settings, k, v)
        app = create_app(ctx=demo_ctx)
        return lambda: TestClient(app)
    return make


def test_visitor_gets_an_account_without_any_token(app_factory):
    new_client = app_factory(acces_libre=True)
    a = new_client()
    r = a.get("/api/dossiers/session")
    assert r.status_code == 200 and r.json()["visiteur"] is True and is_visitor(r.json()["email"])
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(COOKIE + "=") and "HttpOnly" in cookie and "Path=/api;" in cookie and "Max-Age=2592000" in cookie
    assert a.get("/api/dossiers/session").json()["email"] == r.json()["email"]        # le même visiteur ensuite
    folder = a.post("/api/dossiers", json={"title": "Mon dossier"}).json()["id"]
    b = new_client()                                                                    # un autre navigateur
    assert b.get("/api/dossiers/session").json()["email"] != r.json()["email"]
    assert b.get("/api/dossiers").json() == []                                          # il ne voit pas le dossier
    assert b.get(f"/api/dossiers/{folder}").status_code in (403, 404)


def test_without_free_access_the_token_is_still_required(app_factory):
    c = app_factory(acces_libre=False)()
    assert c.get("/api/dossiers/session").status_code == 401
    assert "set-cookie" not in c.get("/api/dossiers").headers


def test_forged_visitor_cookie_is_refused(app_factory):
    c = app_factory(acces_libre=False)()
    import base64
    fake = base64.urlsafe_b64encode(b"visiteur-abc@visiteur.sourcia|9999999999|visiteur").decode().rstrip("=")
    c.cookies.set(COOKIE, fake + ".signature-inventee", path="/api")
    assert c.get("/api/dossiers/session").status_code == 401


def test_daily_quota_per_visitor(tmp_path):
    q = Quotas(tmp_path / "quotas.json", {"corpus": 2, "supports": 1})
    v, w = "visiteur-1@visiteur.sourcia", "visiteur-2@visiteur.sourcia"
    assert q.use(v, "corpus") == 1 and q.use(v, "corpus") == 0 and q.use(v, "corpus") is None
    assert q.use(w, "corpus") == 1                                                      # chacun son compteur
    q.refund(v, "corpus")
    assert q.use(v, "corpus") == 0                                                      # rendu, puis repris
    assert q.use("prof@lycee.fr", "supports") == 1 and q.use("prof@lycee.fr", "supports") == 1   # jeton : pas compté


def test_api_refuses_beyond_the_limit(app_factory):
    c = app_factory(acces_libre=True, serveur=True, limite_visiteur_corpus=0)()
    r = c.post("/api/formation", json={"demande": {"sujet": "sorgho"}, "doc_ids": ["x"]})
    assert r.status_code == 429 and "Limite de la démonstration" in r.json()["detail"]


def test_page_shows_visitor_mode_and_server_config_enables_it(monkeypatch):
    from sourcia.config import load_settings

    page = (ROOT / "src/sourcia/api/static/dossiers.html").read_text(encoding="utf-8")
    assert "Mode visiteur" in page and "session.visiteur" in page
    monkeypatch.delenv("SOURCIA_DATA_DIR", raising=False)
    s = load_settings(ROOT / "config/serveur.yaml")
    assert s.acces_libre and s.limite_visiteur_corpus == 3 and s.limite_visiteur_supports == 3
