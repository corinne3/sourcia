"""M1 Collecte : magasin de documents, exploration d'un site (réseau simulé), dossiers, catalogues."""
import json
from pathlib import Path
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


def test_page_title_decodes_html_entities():
    from sourcia.collect.web import _page_title

    assert _page_title("<title>Chambre d&#039;agriculture &amp; climat</title>") == "Chambre d'agriculture & climat"


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


def test_crawl_visits_matching_pages_first(settings):
    """Plan de site trié par ordre alphabétique : avec une limite de pages, la page « sorgho » passe d'abord."""
    site = {
        "https://ex.org/sitemap.xml": resp("<urlset>" + "".join(f"<url><loc>https://ex.org/{p}</loc></url>"
                                           for p in ("a-porc", "b-ble", "z-sorgho")) + "</urlset>", ctype="text/xml"),
        "https://ex.org/z-sorgho": resp('<a href="/docs/essai.pdf">Essai 2023</a>'),
    }
    visited = []

    def fetch(url):
        visited.append(url)
        return site.get(url, resp("<p>rien</p>"))

    settings.collect.max_pages_per_site = 1
    wc = WebCollector(settings, fetch=fetch)
    docs, rep = wc.crawl("https://ex.org/", include="sorgho|essai")
    pages = [u for u in visited if not u.endswith((".txt", ".xml"))]
    assert pages == ["https://ex.org/z-sorgho"] and rep.pages_visited == 1
    assert [d.url for d in docs] == ["https://ex.org/docs/essai.pdf"]


def test_crawl_judges_pdf_by_its_page(settings):
    """Cas réel (arvalis) : lien « Feuilleter la brochure » vers un PDF à l'adresse sans mot utile."""
    site = {
        "https://ex.org/": resp('<a href="/editions/atlas-du-mais-fourrage">Atlas</a><a href="/porcs">Porcs</a>'),
        "https://ex.org/editions/atlas-du-mais-fourrage": resp(
            '<title>Atlas du maïs fourrage | EX</title><a href="/files/3644_x.pdf">Feuilleter la brochure</a>'),
        "https://ex.org/porcs": resp('<title>Élevage porcin | EX</title><a href="/files/99_y.pdf">Télécharger</a>'),
    }
    wc = WebCollector(settings, fetch=lambda u: site.get(u, resp("", 404)))
    docs, _ = wc.crawl("https://ex.org/", include="fourrag")
    assert [d.url for d in docs] == ["https://ex.org/files/3644_x.pdf"]    # gardé grâce à sa page ; 99_y écarté
    d = docs[0]
    assert d.title == "Atlas du maïs fourrage"                              # titre de la page, sans le nom du site
    assert d.meta == {"page": "https://ex.org/editions/atlas-du-mais-fourrage",
                      "titre_page": "Atlas du maïs fourrage", "texte_lien": "Feuilleter la brochure"}


def test_crawl_exclude_skips_pages_and_pdfs(settings):
    """``exclure`` : ni visité ni listé (ex. les sommaires de brochures d'arvalis)."""
    site = {
        "https://ex.org/": resp('<a href="/files/edition_summary/1_s.pdf">Sommaire maïs</a>'
                                '<a href="/files/essai-mais.pdf">Essai maïs</a><a href="/edition_summary/p">p</a>'
                                '<a href="/panne">x</a><a href="/suite">s</a>'),
        "https://ex.org/suite": resp('<a href="/autre">a</a>'),          # liens trouvés APRÈS une page en erreur
    }
    visited = []

    def fetch(url):
        visited.append(url)
        if url.endswith("/panne"):
            raise requests.ConnectionError("injoignable")
        return site.get(url, resp("", 404))

    docs, _ = WebCollector(settings, fetch=fetch).crawl("https://ex.org/", include="mais|maïs", exclude="edition_summary")
    assert "https://ex.org/autre" in visited                                 # l'exploration continue après l'erreur
    assert [d.url for d in docs] == ["https://ex.org/files/essai-mais.pdf"]
    assert not any("edition_summary" in u for u in visited)


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


def test_document_link_field_is_optional_and_compatible():
    """Contrat documents.jsonl : une ligne écrite avant le champ « link » se lit toujours."""
    from sourcia.core.models import LinkCheck

    old_line = '{"id": "abc", "url": "https://ex.org/a.pdf", "source": "ex", "status": "downloaded"}'
    d = Document.model_validate_json(old_line)
    assert d.link is None and d.current_url == "https://ex.org/a.pdf"
    d.link = LinkCheck(state="moved", checked_at="2026-11-18", http_status=301, new_url="https://ex.org/b.pdf")
    again = Document.model_validate_json(d.model_dump_json())
    assert again.link == d.link and again.current_url == "https://ex.org/b.pdf" and again.url == "https://ex.org/a.pdf"
    again.link = LinkCheck(state="dead", checked_at="2026-11-18", http_status=404)
    assert again.current_url == "https://ex.org/a.pdf"                     # mort : pas de nouvelle adresse


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
                     ("sites:\n  - {nom: a, url: u, exclure: '[x'}\n", "exclure invalide"),
                     ("notes: []\n", "aucune entrée")]:
        with pytest.raises(ValueError, match=msg):
            load_sites(_sites(tmp_path, bad))


def test_select_sites(tmp_path):
    sites = load_sites(_sites(tmp_path))
    assert [s.nom for s in select_sites(sites, ["panne"])] == ["panne"]
    assert select_sites(sites, None) == sites
    with pytest.raises(ValueError, match="disponibles : ex, panne"):
        select_sites(sites, ["arvalis"])
    sites = load_sites(_sites(tmp_path, SITES_YAML.replace("url: https://panne.org/", "url: https://panne.org/\n    actif: false")))
    assert [s.nom for s in select_sites(sites, None)] == ["ex"]                # site mis de côté : pas collecté par défaut
    assert [s.nom for s in select_sites(sites, ["panne"])] == ["panne"]        # sauf si on le demande par son nom


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


def test_collect_site_flags_blocked_start_page(settings, tmp_path):
    """Cas réel (idele.fr) : page « Vérification de la connexion… JavaScript est nécessaire », un seul lien externe."""
    page = resp('<title>Vérification de la connexion...</title><p>JavaScript est nécessaire</p>'
                '<a href="https://d.cx/x">protégé</a>')
    wc = WebCollector(settings, fetch=lambda u: page)
    store = DocumentStore(tmp_path / "documents.jsonl")
    site = load_sites(_sites(tmp_path, "sites:\n  - {nom: bloque, url: 'https://bloque.org/'}\n"))[0]
    [rep] = collect_sites(wc, store, [site], tmp_path / "pdfs")
    assert rep["pages_visitees"] == 1 and not rep["ok"]                       # ✗ et non ✓ avec 0 PDF
    assert any("protection anti-robots" in e for e in rep["erreurs"])


def test_cli_collect_sites(tmp_path, capsys, monkeypatch):
    from sourcia.cli import main

    cfg = tmp_path / "t.yaml"
    cfg.write_text((ROOT / "config/test.yaml").read_text(encoding="utf-8").replace("data/test-run", str(tmp_path / "d")),
                   encoding="utf-8")
    monkeypatch.setattr(requests.Session, "get", lambda self, url, timeout=None: fake_fetch2(url))
    sites = _sites(tmp_path)
    main(["-c", str(cfg), "collect-sites", "--sites-file", str(sites), "--site", "ex", "--max-pages", "5"])
    out = capsys.readouterr().out
    assert "✓ ex : " in out and "2 nouveaux" in out and "Rapport :" in out
    report = json.loads((tmp_path / "d" / "collecte" / "dernier.json").read_text(encoding="utf-8"))
    assert report["options"]["max_pages"] == 5 and report["total"]["nouveaux"] == 2
    assert [s["site"] for s in report["sites"]] == ["ex"]
    assert len(list((tmp_path / "d" / "collecte").glob("rapport-*.json"))) == 1
    with pytest.raises(SystemExit) as exc:                                    # un site sans page lue → code 1
        main(["-c", str(cfg), "collect-sites", "--sites-file", str(sites), "--no-download"])
    assert exc.value.code == 1 and "panne" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="site inconnu"):
        main(["-c", str(cfg), "collect-sites", "--sites-file", str(sites), "--site", "inconnu"])


# ---------------------------------------------------------------------------- articles web (champ « articles »)
BODY = " ".join(["Essai sorgho fourrager conduit en 2023 sur trois sites avec quatre répétitions."] * 30)
ARTICLE_PAGE = f"""<html><head><title>Sorgho fourrager : résultats d&#039;essais | EX</title>
<meta property="og:article:published_time" content="2024-03-12T07:00:00" /></head><body>
<header><nav><a href="/">Accueil</a> Menu du site</nav></header>
<main><section class="hero">Fil d'Ariane Accueil Infos techniques</section>
  <article class="node node--view-mode-full"><h1>Sorgho fourrager : résultats d'essais</h1><p>{BODY}</p>
    <div class="sharer__content">Partager : Facebook</div>
    <div class="related-posts">Sur le même sujet
      <article class="card node--view-mode-teaser"><p>Autre article : la luzerne en 1998</p></article></div>
  </article>
  <aside class="sidebar"><article class="card-event">19 Nov 2026 Réunion technique</article></aside>
</main><footer>Mentions légales</footer></body></html>"""


def test_article_main_text_keeps_only_the_article():
    from sourcia.collect.article import main_text, published_date

    text = main_text(ARTICLE_PAGE)
    assert text.startswith("Sorgho fourrager : résultats d'essais") and "quatre répétitions" in text
    for noise in ("Autre article", "luzerne", "Réunion technique", "Partager", "Fil d'Ariane", "Menu", "Mentions"):
        assert noise not in text                                            # rien des autres articles ni du décor
    assert published_date(ARTICLE_PAGE) == "2024-03-12"
    assert published_date('<script type="application/ld+json">{"datePublished": "2019-05-02T09:00"}</script>') == "2019-05-02"
    assert published_date("<p>sans date</p>") is None
    assert main_text("<body><p>page sans balise article ni main</p></body>") == "page sans balise article ni main"


def test_article_french_dates_and_related_list_cut():
    """Cas réels : dates écrites en français (Terres Inovia, Chambres) ; « Dans le même thème… » (Chambres)."""
    from sourcia.collect.article import main_text, published_date

    assert published_date("<p>Publié le 25 mars 2019 | Mis à jour le 16 décembre 2025</p>") == "2019-03-25"
    assert published_date("<span>Publiée le</span> <b>1er août 2020</b>") == "2020-08-01"
    assert published_date("<dt>Date de publication</dt><dd>octobre 2022</dd>") == "2022"        # mois + année : AAAA
    assert published_date("<p>Dernière mise à jour le 24 juillet 2024</p>") is None            # mise à jour ≠ publication
    page = (f"<main><h1>Préserver les prairies</h1><p>{BODY}</p><h2>Dans le même thème...</h2>"
            "<div class='single'><h3>Base-SPIE, un système d'information</h3><p>En savoir plus</p></div></main>")
    text = main_text(page)
    assert "quatre répétitions" in text and "Dans le même thème" not in text and "Base-SPIE" not in text


ART_SITE = {
    "https://ex.org/": resp('<a href="/infos-techniques/sorgho-essais">Essais</a>'),
    "https://ex.org/sitemap.xml": resp("<urlset>" + "".join(f"<url><loc>https://ex.org/{p}</loc></url>" for p in (
        "editions/sorgho-brochure", "infos-techniques/liste-sorgho", "infos-techniques/sorgho-essais",
        "infos-techniques/porcs")) + "</urlset>", ctype="text/xml"),
    "https://ex.org/infos-techniques/sorgho-essais": resp(ARTICLE_PAGE),
    "https://ex.org/infos-techniques/liste-sorgho": resp("<title>Liste sorgho</title><main><p>trois liens</p></main>"),
    "https://ex.org/infos-techniques/porcs": resp(ARTICLE_PAGE.replace("Sorgho fourrager", "Porcs")
                                                  .replace("sorgho", "porc")),
}


def test_crawl_collects_articles_first(settings, tmp_path):
    visited = []

    def fetch(url):
        visited.append(url)
        return ART_SITE.get(url, resp("<p>rien</p>"))

    settings.collect.max_pages_per_site = 3
    docs, rep = WebCollector(settings, fetch=fetch).crawl(
        "https://ex.org/", include="sorgho", articles="^/infos-techniques/", pages_dir=tmp_path / "pages")
    pages = [u for u in visited if not u.endswith((".txt", ".xml"))]
    # les deux pages d'articles qui passent le filtre d'abord (avant /editions/ et la page d'accueil)
    assert pages[:2] == ["https://ex.org/infos-techniques/liste-sorgho", "https://ex.org/infos-techniques/sorgho-essais"]
    assert rep.articles_found == 1 and rep.pdfs_found == 0                 # page de liste trop courte, porcs hors filtre
    [d] = docs
    assert d.kind == "page" and d.date == "2024-03-12" and d.status == "downloaded" and d.sha1
    assert d.title == "Sorgho fourrager : résultats d'essais" and d.meta["mots"] >= 250
    saved = Path(d.local_path).read_text(encoding="utf-8")
    assert saved.startswith("Sorgho fourrager : résultats d'essais\n\n") and "Autre article" not in saved
    docs, _ = WebCollector(settings, fetch=fetch).crawl("https://ex.org/", include="sorgho", articles="^/infos-techniques/")
    assert docs[0].status == "listed" and docs[0].local_path is None        # sans dossier : listé seulement


def test_collect_site_articles_then_extract(settings, tmp_path):
    from sourcia.extract.pdf import extract

    settings.collect.max_pages_per_site = 5
    wc = WebCollector(settings, fetch=lambda u: ART_SITE.get(u, resp("<p>rien</p>")))
    store = DocumentStore(tmp_path / "documents.jsonl")
    site = load_sites(_sites(tmp_path, "sites:\n  - {nom: ex, url: 'https://ex.org/', filtre: sorgho,"
                                       " articles: '^/infos-techniques/', exclure: '/editions/'}\n"))[0]
    [rep] = collect_sites(wc, store, [site], tmp_path / "pdfs")
    assert rep["articles_trouves"] == 1 and rep["nouveaux"] == 1 and rep["ok"]
    [d] = list(store)
    assert Path(d.local_path).parent == tmp_path / "pages"
    out = extract(d, tmp_path / "text", 40)                                 # la suite du pipeline sait le lire
    assert "quatre répétitions" in out["pages"][0] and d.status == "extracted"
    [rep] = collect_sites(wc, store, [site], tmp_path / "pdfs")             # second passage : rien de nouveau
    assert rep["nouveaux"] == 0 and list(store)[0].status == "extracted"
    with pytest.raises(ValueError, match="articles invalide"):
        load_sites(_sites(tmp_path, "sites:\n  - {nom: a, url: u, articles: '(x'}\n"))


# ---------------------------------------------------------------------------- suivi des liens (check-links)
def hresp(status=200, ctype="application/pdf", location=None):
    headers = {"content-type": ctype} | ({"location": location} if location else {})
    return SimpleNamespace(status_code=status, headers=headers, text="", content=b"")


ROBOTS = resp("User-agent: *\nDisallow: /prive/\n", ctype="text/plain")
PROBES = {
    "https://ex.org/ok.pdf": hresp(),
    "https://ex.org/ancien.pdf": hresp(301, location="/nouveau.pdf"),
    "https://ex.org/nouveau.pdf": hresp(),
    "https://ex.org/supprime.pdf": hresp(404),
    "https://ex.org/vers-accueil.pdf": hresp(302, location="https://ex.org/"),
    "https://ex.org/": hresp(ctype="text/html; charset=utf-8"),
    "https://ex.org/article": hresp(ctype="text/html"),
    "https://ex.org/telecharger.pdf": hresp(302, location="https://cdn.ex.org/f.pdf?signature=abc&expire=1"),
    "https://cdn.ex.org/f.pdf?signature=abc&expire=1": hresp(),
}


def link_collector(settings, down=(), no_head=()):
    def probe(url, method):
        if url in down:
            raise requests.ConnectionError("Max retries exceeded")
        if url in no_head and method == "HEAD":
            return hresp(405)
        return PROBES.get(url, hresp(404))
    return WebCollector(settings, fetch=lambda u: ROBOTS if u.endswith("robots.txt") else resp("", 404), probe=probe)


def doc(path, **kw):
    url = "https://ex.org/" + path
    return Document(id=doc_id_for(url), url=url, source="ex", **kw)


def test_check_document_rules(settings):
    from sourcia.collect.links import Blocked, check_document

    wc = link_collector(settings, no_head={"https://ex.org/ok.pdf"})
    assert check_document(wc, doc("ok.pdf"), "2026-11-18").state == "ok"           # HEAD refusé → GET
    moved = check_document(wc, doc("ancien.pdf"), "2026-11-18")
    assert moved.state == "moved" and moved.new_url == "https://ex.org/nouveau.pdf" and moved.detail == "redirection 301"
    temp = check_document(wc, doc("telecharger.pdf"), "2026-11-18")              # lien signé qui expire : on garde l'origine
    assert temp.state == "ok" and temp.new_url is None and "redirection temporaire" in temp.detail
    gone = check_document(wc, doc("supprime.pdf"), "2026-11-18")
    assert gone.state == "dead" and gone.http_status == 404 and gone.since == "2026-11-18"
    soft = check_document(wc, doc("vers-accueil.pdf"), "2026-11-18")             # cas réel arvalis : HTML au lieu du PDF
    assert soft.state == "dead" and "page HTML à la place du PDF" in soft.detail
    assert check_document(wc, doc("article", kind="page"), "2026-11-18").state == "ok"   # une page HTML, c'est normal
    assert check_document(wc, doc("x.pdf", private=True), "2026-11-18") is None
    with pytest.raises(Blocked):
        check_document(wc, doc("prive/x.pdf"), "2026-11-18")


def test_check_links_three_failures_then_back(settings, tmp_path):
    from sourcia.collect.links import check_links

    store = DocumentStore(tmp_path / "documents.jsonl")
    d = doc("ok.pdf")
    store.add(d)
    down = link_collector(settings, down={"https://ex.org/ok.pdf"})
    states = []
    for day in ("2026-11-18", "2026-11-19", "2026-11-20"):
        rep = check_links(down, store, [d], today=day)
        states.append((d.link.state, d.link.failures, rep["changements"][0]["changement"] if rep["changements"] else None))
    assert states == [("unreachable", 1, "injoignable"), ("unreachable", 2, None), ("dead", 3, "nouveau_mort")]
    assert d.link.since == "2026-11-18" and "3 vérifications de suite" in d.link.detail
    rep = check_links(link_collector(settings), store, [d], today="2026-11-21")   # le site remarche
    assert d.link.state == "ok" and d.link.failures == 0 and rep["changements"][0]["changement"] == "revenu"
    assert DocumentStore(tmp_path / "documents.jsonl").get(d.id).link.state == "ok"   # enregistré dans le catalogue


def test_check_links_report_and_moved_doc_followed(settings, tmp_path):
    from sourcia.collect.links import check_links

    store = DocumentStore(tmp_path / "documents.jsonl")
    docs = [doc("ok.pdf"), doc("ancien.pdf"), doc("supprime.pdf"), doc("prive/x.pdf"), doc("p.pdf", private=True)]
    for d in docs:
        store.add(d)
    wc = link_collector(settings)
    rep = check_links(wc, store, docs, today="2026-11-18")
    assert rep["etats"] == {"ok": 1, "moved": 1, "dead": 1, "unreachable": 0}
    assert rep["bloques_robots"] == 1 and rep["ignores_prives"] == 1 and rep["verifies"] == 3
    assert {c["changement"] for c in rep["changements"]} == {"nouveau_deplace", "nouveau_mort"}
    rep = check_links(wc, store, docs, today="2026-11-19")                        # rien n'a changé
    assert rep["changements"] == [] and docs[1].current_url == "https://ex.org/nouveau.pdf"
    PROBES_BACKUP = dict(PROBES)
    try:                                                                           # la nouvelle adresse meurt à son tour
        PROBES["https://ex.org/nouveau.pdf"] = hresp(404)
        rep = check_links(wc, store, [docs[1]], today="2026-11-20")
        assert docs[1].link.state == "dead" and docs[1].current_url == docs[1].url
    finally:
        PROBES.clear()
        PROBES.update(PROBES_BACKUP)


def test_cli_check_links(tmp_path, capsys, monkeypatch):
    from sourcia.cli import main

    cfg = tmp_path / "t.yaml"
    cfg.write_text((ROOT / "config/test.yaml").read_text(encoding="utf-8").replace("data/test-run", str(tmp_path / "d")),
                   encoding="utf-8")
    store = DocumentStore(tmp_path / "d" / "documents.jsonl")
    for d in (doc("ok.pdf"), doc("ancien.pdf"), doc("supprime.pdf")):
        store.add(d)
    store.save()
    monkeypatch.setattr(requests.Session, "get", lambda self, url, timeout=None: resp("", 404))      # robots.txt absent
    monkeypatch.setattr(requests.Session, "request",
                        lambda self, method, url, **kw: PROBES.get(url, hresp(404)))
    main(["-c", str(cfg), "check-links"])
    out = capsys.readouterr().out
    assert "1 ok · 1 déplacés · 1 morts" in out and "✗ mort" in out and "→ https://ex.org/nouveau.pdf" in out
    report = json.loads((tmp_path / "d" / "liens" / "dernier.json").read_text(encoding="utf-8"))
    assert report["etats"]["dead"] == 1 and len(report["changements"]) == 2
    main(["-c", str(cfg), "check-links", "--etat", "dead"])                       # revérifier seulement les morts
    out = capsys.readouterr().out
    assert "Vérification de 1 liens" in out and "Aucun changement" in out
    links = {d.url.rsplit("/", 1)[1]: d.link.state for d in DocumentStore(tmp_path / "d" / "documents.jsonl")}
    assert links == {"ok.pdf": "ok", "ancien.pdf": "moved", "supprime.pdf": "dead"}


def test_collect_site_relinks_dead_doc_by_content(settings, tmp_path):
    """Un PDF mort (404) réapparaît, identique, à une autre adresse : l'ancien document devient « déplacé »."""
    import hashlib

    from sourcia.collect.sites import format_site
    from sourcia.core.models import LinkCheck

    store = DocumentStore(tmp_path / "documents.jsonl")
    old = doc("vieux-dossier/sorgho-2023.pdf", sha1=hashlib.sha1(b"%PDF-1.4 fake").hexdigest(), status="extracted",
              link=LinkCheck(state="dead", checked_at="2026-11-17", http_status=404, detail="HTTP 404"))
    other_dead = doc("autre.pdf", sha1="0" * 40, link=LinkCheck(state="dead", checked_at="2026-11-17"))
    store.add(old)
    store.add(other_dead)
    wc = WebCollector(settings, fetch=fake_fetch2)
    site = load_sites(_sites(tmp_path, "sites:\n  - {nom: ex, url: 'https://ex.org/', filtre: sorgho}\n"))[0]
    [rep] = collect_sites(wc, store, [site], tmp_path / "pdfs")
    assert rep["deplaces_retrouves"] == [{"id": old.id, "ancienne_url": old.url,
                                          "nouvelle_url": "https://ex.org/docs/sorgho-2023.pdf"}]
    assert old.link.state == "moved" and old.current_url == "https://ex.org/docs/sorgho-2023.pdf"
    assert "même contenu" in old.link.detail and old.status == "extracted"     # fiche et texte gardés
    assert other_dead.link.state == "dead"                                      # contenu jamais retrouvé
    assert "↪ déplacé (même contenu)" in format_site(rep)
    assert DocumentStore(tmp_path / "documents.jsonl").get(old.id).link.state == "moved"
