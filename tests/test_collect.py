"""M1 Collecte : magasin de documents, exploration d'un site (réseau simulé), dossiers, catalogues."""
from types import SimpleNamespace

import pytest
import requests

from conftest import ROOT
from sourcia.collect.catalog import import_catalog
from sourcia.collect.sites import collect_sites, load_sites, select_sites
from sourcia.collect.store import DocumentStore
from sourcia.collect.web import WebCollector, parse_links, parse_sitemap
from sourcia.core.models import Document, doc_id_for


def resp(text="", status=200, ctype="text/html", content=None):
    return SimpleNamespace(text=text, status_code=status, headers={"content-type": ctype},
                           content=content if content is not None else text.encode())


SITE = {
    "https://ex.org/robots.txt": resp("User-agent: *\nDisallow: /prive/\n", ctype="text/plain"),
    "https://ex.org/sitemap.xml": resp("<urlset><url><loc>https://ex.org/pub</loc></url></urlset>", ctype="text/xml"),
    "https://ex.org/": resp('<a href="/pub">Publications</a><a href="/prive/x">x</a><a href="/img.png">i</a>'),
    "https://ex.org/pub": resp('<a href="/docs/sorgho-2023.pdf">Essai sorgho 2023</a>'
                               '<a href="/docs/porc.pdf">Porcs</a><a href="/prive/secret.pdf">S</a>'),
    "https://ex.org/docs/sorgho-2023.pdf": resp(ctype="application/pdf", content=b"%PDF-1.4 fake"),
}


def fake_fetch(url):
    return SITE.get(url, resp("", 404))


def test_parse_helpers():
    links = parse_links('<a href="a.pdf#p2">Titre  A</a><a href="mailto:x@y">m</a>', "https://ex.org/d/")
    assert links == [("https://ex.org/d/a.pdf", "Titre A")]
    pages, subs = parse_sitemap("<sitemapindex><sitemap><loc>https://ex.org/s1.xml</loc></sitemap></sitemapindex>")
    assert subs == ["https://ex.org/s1.xml"] and pages == []


def test_crawl_respects_robots_and_finds_pdfs(settings, tmp_path):
    settings.collect.delay_s = 0
    wc = WebCollector(settings, fetch=fake_fetch)
    docs, rep = wc.crawl("https://ex.org/")
    urls = {d.url for d in docs}
    assert "https://ex.org/docs/sorgho-2023.pdf" in urls
    assert any(d.title == "Essai sorgho 2023" for d in docs)          # le texte du lien sert de titre
    assert rep.blocked_by_robots >= 1                                 # /prive/ jamais visité
    docs, _ = wc.crawl("https://ex.org/", include="sorgho")
    assert [d.url for d in docs] == ["https://ex.org/docs/sorgho-2023.pdf"]
    d = wc.download(docs[0], tmp_path)
    assert d.status == "downloaded" and d.sha1


def test_crawl_notes_dead_links_and_skips_forbidden_pdfs(settings):
    site = dict(SITE)
    site["https://ex.org/"] = resp('<a href="/pub">Publications</a><a href="/vieux">v</a>')
    wc = WebCollector(settings, fetch=lambda u: site.get(u, resp("", 404)))
    docs, rep = wc.crawl("https://ex.org/")
    assert "https://ex.org/vieux : HTTP 404" in rep.errors                 # lien mort noté dans le rapport
    assert "https://ex.org/prive/secret.pdf" not in {d.url for d in docs}  # PDF interdit par robots.txt : pas listé
    assert rep.blocked_by_robots == 1

def test_download_rejects_non_pdf(settings, tmp_path):
    settings.collect.delay_s = 0
    wc = WebCollector(settings, fetch=lambda u: resp("<html>erreur</html>"))
    d = wc.download(Document(id="x", url="https://ex.org/a.pdf", source="ex"), tmp_path)
    assert d.status == "error" and "pas un PDF" in d.error


def test_store_merge_and_duplicates(tmp_path):
    st = DocumentStore(tmp_path / "documents.jsonl")
    a = Document(id=doc_id_for("u1"), url="u1", source="s1", sha1="abc")
    b = Document(id=doc_id_for("u2"), url="u2", source="s2", sha1="abc", title="Titre")
    assert st.add(a) and st.add(b) and not st.add(a)
    assert len(st.canonical()) == 1                                     # même contenu publié sur deux sites
    st.save()
    assert len(DocumentStore(tmp_path / "documents.jsonl")) == 2


def test_import_catalog_guesses_columns(tmp_path):
    p = tmp_path / "cat.csv"
    p.write_text("Titre;Lien;Année;Mots-clés\nSorgho;https://x.org/a.pdf;2021;sorgho, sécheresse\nSans;;;\n",
                 encoding="utf-8")
    docs, skipped = import_catalog(p, "rdagri")
    assert skipped == 1 and docs[0].title == "Sorgho" and docs[0].date == "2021"
    assert docs[0].keywords == ["sorgho", "sécheresse"]


# ---------------------------------------------------------------------------- collect-sites (config/sites.yaml)
SITES_YAML = """sites:
  - nom: ex
    url: https://ex.org/
    filtre: "sorgho|porc"
  - nom: panne
    url: https://panne.org/
notes:
  - "une note"
"""

SITE2 = dict(SITE)
SITE2["https://ex.org/"] = resp('<a href="/pub">Publications</a><a href="/prive/x">x</a><a href="/vieux">v</a>')


def fake_fetch2(url):
    if "panne.org" in url:
        raise requests.ConnectionError("Max retries exceeded")
    return SITE2.get(url, resp("", 404))


def _sites(tmp_path, text=SITES_YAML):
    p = tmp_path / "sites.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_sites_validates(tmp_path):
    sites = load_sites(_sites(tmp_path))
    assert [s.nom for s in sites] == ["ex", "panne"] and sites[1].filtre is None
    assert len(load_sites(ROOT / "config" / "sites.yaml")) >= 4                # le vrai fichier est valide
    for bad, msg in [("sites:\n  - nom: a\n", "url"),
                     ("sites:\n  - {nom: a, url: u}\n  - {nom: a, url: v}\n", "deux fois"),
                     ("sites:\n  - {nom: a, url: u, filtre: '(sorgho'}\n", "filtre invalide"),
                     ("notes: []\n", "aucune entrée")]:
        with pytest.raises(ValueError, match=msg):
            load_sites(_sites(tmp_path, bad))


def test_select_sites(tmp_path):
    sites = load_sites(_sites(tmp_path))
    assert [s.nom for s in select_sites(sites, ["panne"])] == ["panne"]
    assert select_sites(sites, None) == sites
    with pytest.raises(ValueError, match="disponibles : ex, panne"):
        select_sites(sites, ["arvalis"])


def test_collect_sites_report_new_then_nothing_new(settings, tmp_path):
    wc = WebCollector(settings, fetch=fake_fetch2)
    store = DocumentStore(tmp_path / "documents.jsonl")
    sites = load_sites(_sites(tmp_path))
    seen = []
    ex, panne = collect_sites(wc, store, sites, tmp_path / "pdfs", progress=lambda s, r: seen.append((s.nom, r is None)))
    assert seen == [("ex", True), ("ex", False), ("panne", True), ("panne", False)]
    # site ex : 2 PDF retenus par le filtre (secret.pdf interdit par robots.txt n'est pas listé)
    assert ex["ok"] and ex["pdf_trouves"] == 2 and ex["nouveaux"] == 2
    assert ex["telecharges"] == 1 and ex["echecs_telechargement"] == 1       # porc.pdf : 404 au téléchargement
    assert ex["bloques_robots"] == 2                                          # /prive/x et /prive/secret.pdf
    assert any("/vieux : HTTP 404" in e for e in ex["erreurs"])               # lien mort sur une page
    assert any("porc.pdf" in e and "HTTP 404" in e for e in ex["erreurs"])
    assert {d.source for d in store} == {"ex"}                                # source = nom dans sites.yaml
    # site en panne : n'arrête pas la collecte, signalé
    assert not panne["ok"] and panne["pages_visitees"] == 0 and panne["erreurs"]
    # le catalogue est enregistré
    assert len(DocumentStore(tmp_path / "documents.jsonl")) == 2
    # second passage : rien de nouveau, rien à retélécharger
    ex2, _ = collect_sites(wc, store, sites, tmp_path / "pdfs")
    assert ex2["pdf_trouves"] == 2 and ex2["nouveaux"] == 0 and ex2["telecharges"] == 0


def test_collect_sites_no_download_then_download(settings, tmp_path):
    wc = WebCollector(settings, fetch=fake_fetch2)
    store = DocumentStore(tmp_path / "documents.jsonl")
    sites = select_sites(load_sites(_sites(tmp_path)), ["ex"])
    [rep] = collect_sites(wc, store, sites, tmp_path / "pdfs", download=False)
    assert rep["nouveaux"] == 2 and rep["telecharges"] == 0 and not (tmp_path / "pdfs").exists()
    assert {d.status for d in store} == {"listed"}
    [rep] = collect_sites(wc, store, sites, tmp_path / "pdfs")                # les PDF en attente sont téléchargés
    assert rep["nouveaux"] == 0 and rep["telecharges"] == 1
