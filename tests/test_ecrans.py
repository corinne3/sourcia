"""Phase 3 : les écrans du parcours (Catalogue → Mon dossier → Mon corpus → Mes supports).

Les écrans eux-mêmes se vérifient dans le navigateur ; ici, on vérifie ce qui casserait sans bruit : la route du
script, la barre d'étapes, les éléments que le script cherche dans la page, les routes de l'API qu'il appelle, et ce
qu'il emprunte au script de dossiers.html (jeton, dossier, fonctions)."""
import re
import shutil
import subprocess

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient                               # noqa: E402

from conftest import ROOT                                               # noqa: E402

STATIC = ROOT / "src" / "sourcia" / "api" / "static"
JS = (STATIC / "parcours.js").read_text(encoding="utf-8")
DOSSIERS = (STATIC / "dossiers.html").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
STEPS = ["/", "/dossiers#dossier", "/dossiers#corpus", "/dossiers#supports"]


@pytest.fixture
def client(ctx, monkeypatch):
    from sourcia.api.app import create_app

    monkeypatch.setenv("SOURCIA_DOSSIER_ACCOUNTS", "{}")
    return TestClient(create_app(ctx=ctx))


def test_script_served(client):
    r = client.get("/assets/parcours.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "corpus-pedagogique" in r.text


def test_steps_bar_on_both_pages(client):
    for path in ("/", "/dossiers"):
        html = client.get(path).text
        nav = re.search(r'<nav class="steps".*?</nav>', html, re.S).group(0)
        assert re.findall(r'href="([^"]+)"', nav) == STEPS, path
    assert re.search(r'<a href="/" data-step="catalogue" aria-current="page">', INDEX)   # étape en cours au catalogue
    assert "aria-current" not in re.search(r'<nav class="steps".*?</nav>', DOSSIERS, re.S).group(0)  # posé par le script
    page = client.get("/dossiers").text
    assert 'id="step-corpus"' in page and 'id="step-supports"' in page
    assert page.index('<script src="/assets/parcours.js?v=') > page.index("</script>")   # après le script de Kalil


def test_every_element_used_by_the_script_exists():
    used = set(re.findall(r"byId\('([\w-]+)'\)", JS))
    declared = set(re.findall(r'id="([\w-]+)"', DOSSIERS))
    assert used and used <= declared, used - declared


def test_borrowed_names_still_declared_in_dossiers_page():
    """parcours.js emprunte ces noms au script de dossiers.html : s'ils changent, le parcours casse."""
    for pattern in (r"let token\b", r"let folder\b", r"const base\b", r"const byId\b", r"async function json\(",
                    r"async function request\(", r"function message\("):
        assert re.search(pattern, DOSSIERS), pattern


def test_api_routes_called_by_the_script_exist(client):
    routes = set(client.app.openapi()["paths"])          # toutes les routes, routeurs inclus
    for path in ("/api/referentiels", "/api/dossiers/{folder_id}", "/api/dossiers/{folder_id}/corpus-pedagogique",
                 "/api/dossiers/{folder_id}/corpus-pedagogique/{cid}/{name}",
                 "/api/dossiers/{folder_id}/corpus-pedagogique/{cid}/illustrations/{name}",
                 "/api/dossiers/{folder_id}/corpus-pedagogique/{cid}/supports",
                 "/api/dossiers/{folder_id}/corpus-pedagogique/{cid}/supports/{sid}/{name}"):
        assert path in routes, path
    for piece in ("'/api/referentiels'", "'/corpus-pedagogique'", "'/supports'", "'/corpus.json'",
                  "'/corpus_pedagogique.docx'"):
        assert piece in JS, piece


def test_file_labels_match_the_api():
    """Chaque fichier que l'API sait servir a un nom lisible dans l'écran Supports."""
    from sourcia.api.supports_api import FILES

    labels = set(re.findall(r"'([\w.]+\.(?:md|txt|csv|html|pptx|json))': '", JS))
    assert labels == set(FILES)


def test_no_html_injection_from_api_text():
    code = re.sub(r"//[^\n]*", "", JS)                    # sans les commentaires
    assert "innerHTML" not in code and "insertAdjacentHTML" not in code and "document.write" not in code


@pytest.mark.skipif(shutil.which("node") is None, reason="Node absent : syntaxe non vérifiée")
def test_script_syntax():
    r = subprocess.run(["node", "--check", str(STATIC / "parcours.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_every_static_file_is_packaged():
    """Une installation classique (pip install ., Docker) ne livre que les fichiers déclarés dans pyproject.toml :
    un fichier statique oublié (parcours.js) casserait les écrans en production, pas en développement."""
    import fnmatch
    import tomllib

    patterns = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]["sourcia"]
    for f in STATIC.rglob("*"):
        if f.is_dir():
            continue
        rel = "api/static/" + f.relative_to(STATIC).as_posix()
        assert any(fnmatch.fnmatch(rel, p) for p in patterns), f"{rel} n'est pas livré avec le paquet"


def test_fonts_served_from_the_app(client):
    """Polices hébergées par l'application : chaque @font-face de la feuille de style pointe sur un fichier servi."""
    css = (STATIC / "sourcia.css").read_text(encoding="utf-8")
    urls = re.findall(r'url\("(/assets/fonts/[^"]+)"\)', css)
    assert len(urls) == 4
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200 and r.headers["content-type"] == "font/woff2" and r.content[:4] == b"wOF2", url
    assert client.get("/assets/fonts/OFL-fredoka.txt").status_code == 404          # seulement les .woff2
    assert client.get("/assets/fonts/..%2Fsourcia.css").status_code == 404
    assert "fonts.googleapis.com" not in css and "fonts.gstatic.com" not in css      # rien chez Google
    for name in ("OFL-fredoka.txt", "OFL-atkinson-hyperlegible.txt"):              # licences livrées avec les polices
        assert "SIL Open Font License" in (STATIC / "fonts" / name).read_text(encoding="utf-8")


def test_plain_french_copy_in_the_screens():
    """Pas de « A · B · C » ni de « Bouton → » dans les textes des écrans : des phrases simples."""
    code = re.sub(r"//[^\n]*", "", JS)
    assert " · " not in code and "→'" not in code and "→ '" not in code
