"""M1 Collecte : magasin de documents, exploration d'un site (réseau simulé), dossiers, catalogues."""
from types import SimpleNamespace

from sourcia.collect.catalog import import_catalog
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
