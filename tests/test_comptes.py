"""Comptes enseignants : fichier d'empreintes, sessions par cookie, lien de connexion, compte de démonstration."""
import json
import re

import pytest

from sourcia.cli import main
from sourcia.comptes import COOKIE, DEMO_EMAIL, Comptes, Sessions, fingerprint, parse_env

from conftest import ROOT

ENV_TOKEN = "jeton-variable-" + "v" * 32
STATIC = ROOT / "src" / "sourcia" / "api" / "static"


# ---------------------------------------------------------------------- comptes (fichier + variable)
def test_file_keeps_only_fingerprints(tmp_path):
    comptes = Comptes(tmp_path / "comptes.json", env="{}")
    token = comptes.ajouter("Prof.Un@Lycee.fr")
    assert len(token) == 43
    text = (tmp_path / "comptes.json").read_text(encoding="utf-8")
    assert token not in text and fingerprint(token) in text                  # jamais le jeton en clair
    assert comptes.identify(token) == "prof.un@lycee.fr"
    assert comptes.identify("mauvais") is None and comptes.identify("") is None


def test_add_replace_remove_and_list(tmp_path):
    comptes = Comptes(tmp_path / "comptes.json", env=json.dumps({"var@lycee.fr": ENV_TOKEN}))
    old = comptes.ajouter("a@lycee.fr")
    with pytest.raises(ValueError, match="existe déjà"):
        comptes.ajouter("a@lycee.fr")
    new = comptes.ajouter("a@lycee.fr", remplacer=True)
    assert comptes.identify(old) is None and comptes.identify(new) == "a@lycee.fr"
    assert comptes.identify(ENV_TOKEN) == "var@lycee.fr"                    # la variable marche toujours
    assert [(r["email"], r["source"]) for r in comptes.lister()] == [("a@lycee.fr", "fichier"),
                                                                     ("var@lycee.fr", "variable")]
    assert comptes.retirer("a@lycee.fr") and not comptes.retirer("a@lycee.fr")
    assert comptes.identify(new) is None
    with pytest.raises(ValueError, match="invalide"):
        comptes.ajouter("pas une adresse")


def test_file_changes_seen_without_restart(tmp_path):
    server = Comptes(tmp_path / "comptes.json", env="{}")                   # le serveur qui tourne
    token = Comptes(tmp_path / "comptes.json", env="{}").ajouter("b@lycee.fr")   # la commande, à côté
    assert server.identify(token) == "b@lycee.fr"


def test_env_variable_still_checked():
    with pytest.raises(ValueError, match="32 caractères"):
        parse_env(json.dumps({"a@lycee.fr": "court"}))
    with pytest.raises(ValueError, match="invalides ou en double"):
        parse_env(json.dumps({"pas-une-adresse": ENV_TOKEN}))


# ---------------------------------------------------------------------- sessions signées
def test_session_cookie_signed_and_bound_to_the_token(tmp_path, monkeypatch):
    comptes = Comptes(tmp_path / "comptes.json", env="{}")
    token = comptes.ajouter("c@lycee.fr")
    sessions = Sessions(comptes, secret="s" * 40)
    value = sessions.create("c@lycee.fr", token)
    assert sessions.verify(value) == "c@lycee.fr"
    data, _, sig = value.rpartition(".")
    assert sessions.verify(data + "." + "0" * len(sig)) is None                    # signature trafiquée
    assert Sessions(comptes, secret="t" * 40).verify(value) is None                # autre clé de serveur
    assert sessions.verify("n'importe quoi") is None and sessions.verify(None) is None
    import time
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 13 * 3600)                 # 13 h plus tard
    assert sessions.verify(value) is None
    monkeypatch.setattr(time, "time", real)
    comptes.ajouter("c@lycee.fr", remplacer=True)                                  # jeton remplacé
    assert sessions.verify(value) is None


# ---------------------------------------------------------------------- API
@pytest.fixture
def client(ctx, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sourcia.api.app import create_app

    monkeypatch.setenv("SOURCIA_DOSSIER_ACCOUNTS", json.dumps({"var@lycee.fr": ENV_TOKEN}))
    monkeypatch.setenv("SOURCIA_SESSION_SECRET", "secret-de-test-" + "x" * 32)
    c = TestClient(create_app(ctx=ctx))
    c.comptes = Comptes(ctx.settings.path("comptes.json"))
    return c


def test_login_sets_protected_cookie_then_works_without_token(client):
    token = client.comptes.ajouter("d@lycee.fr")
    bad = client.post("/api/dossiers/session", json={"jeton": "faux"})
    assert bad.status_code == 401 and "set-cookie" not in bad.headers and "pas reconnu" in bad.json()["detail"]
    r = client.post("/api/dossiers/session", json={"jeton": token})
    assert r.status_code == 200 and r.json()["email"] == "d@lycee.fr"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(COOKIE + "=") and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Path=/api;" in cookie and "Secure" not in cookie and token not in cookie   # sert aussi au catalogue
    assert client.post("/api/dossiers", json={"title": "Avec cookie"}).status_code == 201   # sans en-tête
    assert [f["title"] for f in client.get("/api/dossiers").json()] == ["Avec cookie"]
    assert client.get("/api/dossiers/session").json() == {"email": "d@lycee.fr", "visiteur": False}
    assert client.delete("/api/dossiers/session").status_code == 204                 # se déconnecter
    client.cookies.clear()                                                           # (le navigateur l'efface)
    assert client.get("/api/dossiers").status_code == 401


def test_logout_response_clears_the_cookie(client):
    r = client.delete("/api/dossiers/session")
    assert COOKIE in r.headers["set-cookie"] and ("Max-Age=0" in r.headers["set-cookie"]
                                                   or "expires=" in r.headers["set-cookie"].lower())


def test_cookie_secure_behind_https(client):
    token = client.comptes.ajouter("e@lycee.fr")
    r = client.post("/api/dossiers/session", json={"jeton": token}, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in r.headers["set-cookie"]


def test_removed_account_loses_its_session(client):
    token = client.comptes.ajouter("f@lycee.fr")
    client.post("/api/dossiers/session", json={"jeton": token})
    assert client.get("/api/dossiers").status_code == 200
    client.comptes.retirer("f@lycee.fr")                                             # « sourcia comptes retirer »
    assert client.get("/api/dossiers").status_code == 401


def test_bearer_token_still_accepted_and_session_route_is_not_a_folder(client):
    h = {"Authorization": f"Bearer {ENV_TOKEN}"}
    assert client.get("/api/dossiers", headers=h).status_code == 200
    assert client.get("/api/dossiers/session", headers=h).json() == {"email": "var@lycee.fr", "visiteur": False}
    assert client.get("/api/dossiers/session").status_code == 401


# ---------------------------------------------------------------------- page
def test_page_uses_session_and_connection_link():
    html = (STATIC / "dossiers.html").read_text(encoding="utf-8")
    assert "base + '/session'" in html and "#jeton=" in html and "history.replaceState" in html
    # lien collé dans l'onglet déjà ouvert : seul le # change, sans rechargement (défaut vu dans le navigateur)
    assert "window.addEventListener('hashchange', () => { useLink(); })" in html
    assert "token ? {Authorization: 'Bearer ' + token} : {}" in html                 # sinon : le cookie
    assert re.search(r"let account\b", html) and 'id="account"' in html
    assert "localStorage" not in html and "sessionStorage" not in html               # jeton jamais enregistré
    assert "Boolean(account || token)" in (STATIC / "parcours.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------------- commande
def test_cli_accounts_and_demo(tmp_path, capsys, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.delenv("SOURCIA_DOSSIER_ACCOUNTS", raising=False)
    cfg = tmp_path / "t.yaml"
    cfg.write_text((ROOT / "config/test.yaml").read_text(encoding="utf-8").replace("data/test-run", str(tmp_path / "d")),
                   encoding="utf-8")
    run = lambda *a: main(["-c", str(cfg), "comptes", *a])                          # noqa: E731
    run("ajouter", "prof@lycee.fr", "--url", "https://sourcia.exemple.fr/")
    out = capsys.readouterr().out
    token = re.search(r"Jeton de prof@lycee.fr.*\n  (\S+)", out).group(1)
    assert f"https://sourcia.exemple.fr/dossiers#jeton={token}" in out
    assert token not in (tmp_path / "d" / "comptes.json").read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        run("ajouter", "prof@lycee.fr")                                              # existe déjà
    run("lister")
    assert "prof@lycee.fr" in capsys.readouterr().out
    run("retirer", "prof@lycee.fr")
    with pytest.raises(SystemExit):
        run("retirer", "prof@lycee.fr")
    capsys.readouterr()
    main(["-c", str(cfg), "demo"])                                                   # un catalogue d'exemple
    capsys.readouterr()
    run("demo", "--documents", "2")
    out = capsys.readouterr().out
    assert "Dossier « Démo : sorgho fourrager » prêt (2/2 documents traités)" in out
    demo_token = re.search(r"Jeton de demo@sourcia.local.*\n  (\S+)", out).group(1)
    from sourcia.config import load_settings
    assert Comptes(load_settings(cfg).path("comptes.json"), env="{}").identify(demo_token) == DEMO_EMAIL
