"""Phase 1 : corpus pédagogique à partir d'un DOSSIER ENSEIGNANT (étape 2 → étape 3).

Parcours réel de l'API des dossiers (jetons, ajout depuis le catalogue, téléversement, traitement en tâche de
fond) puis construction du corpus. Le modèle est simulé (test_formation.responder). Les tâches de fond de
TestClient tournent avant le retour de l'appel : après un POST, le traitement est déjà fini."""
import json
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pymupdf = pytest.importorskip("pymupdf")

from fastapi.testclient import TestClient                               # noqa: E402

from sourcia.cli import main                                            # noqa: E402
from sourcia.core.models import Document, doc_id_for                    # noqa: E402
from sourcia.extract.pdf import load_text                               # noqa: E402
from sourcia.formation.corpus_pedagogique import CorpusPedagogique      # noqa: E402
from sourcia.llm.fake import FakeLLM                                    # noqa: E402

from conftest import ROOT, doc_by_file                                  # noqa: E402
from test_formation import responder                                    # noqa: E402
from test_illustrations import gradient                                 # noqa: E402

TOKEN1 = "jeton-prof-1-" + "a" * 32
TOKEN2 = "jeton-prof-2-" + "b" * 32
H1 = {"Authorization": f"Bearer {TOKEN1}"}
H2 = {"Authorization": f"Bearer {TOKEN2}"}
CATALOG_PDF_URL = "https://ex.org/essai_sorgho_illustre.pdf"


def make_pdf(path, lines, seed, caption):
    """PDF d'une page : du texte sur le sorgho, une figure (couleurs selon ``seed``) et sa légende."""
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    for i, line in enumerate(lines):
        page.insert_text((100, 100 + 14 * i), line, fontsize=9)
    page.insert_image(pymupdf.Rect(100, 170, 400, 370), pixmap=gradient(300, 200, seed=seed))
    page.insert_text((100, 392), caption, fontsize=10)
    pdf.save(str(path))
    pdf.close()
    return Path(path)


CATALOG_LINES = ["Le sorgho fourrager a produit 9,5 t MS/ha en année sèche dans l'essai des Grands Prés.",
                 "Le semis du sorgho se fait après le 15 mai dans un sol bien réchauffé et bien préparé.",
                 "En sol superficiel, le sorgho fourrager sécurise le stock fourrager de l'exploitation."]
UPLOAD_LINES = ["Au lycée, le sorgho multicoupe est semé après le méteil, vers le 20 mai, sur 4 hectares.",
                "Le sorgho multicoupe donne deux coupes d'ensilage pour les vaches laitières en été sec.",
                "La parcelle du lycée reçoit 60 unités d'azote au semis du sorgho multicoupe."]


@pytest.fixture
def app(demo_ctx, monkeypatch, tmp_path):
    """Application avec 2 enseignants, le catalogue d'exemple, un PDF du catalogue avec une adresse web."""
    from sourcia.api.app import create_app

    monkeypatch.setenv("SOURCIA_DOSSIER_ACCOUNTS", json.dumps({"prof1@lycee.fr": TOKEN1, "prof2@lycee.fr": TOKEN2}))
    demo_ctx.__dict__["llm"] = FakeLLM(responder=responder)          # le modèle simulé, à la place du défaut
    (tmp_path / "catalogue").mkdir()
    path = make_pdf(tmp_path / "catalogue" / "essai_sorgho_illustre.pdf", CATALOG_LINES, seed=1,
                    caption="Figure 1 : Rendement du sorgho en année sèche")
    pdf_doc = Document(id=doc_id_for(CATALOG_PDF_URL), url=CATALOG_PDF_URL, source="ex.org",
                       title="Essai sorgho illustré", local_path=str(path), kind="pdf", status="downloaded")
    demo_ctx.store.add(pdf_doc)
    client = TestClient(create_app(ctx=demo_ctx))
    client.ctx, client.pdf_id = demo_ctx, pdf_doc.id
    return client


def new_folder(client, title="Sorgho BTSA", headers=H1):
    r = client.post("/api/dossiers", json={"title": title}, headers=headers)
    assert r.status_code == 201
    return r.json()["id"]


def add_catalog(client, folder, catalog_id):
    r = client.post(f"/api/dossiers/{folder}/catalogue", json={"document_id": catalog_id}, headers=H1)
    assert r.status_code == 202, r.text
    return r.json()["id"]


def upload(client, folder, tmp_path, name="mon_cours_sorgho.pdf"):
    path = make_pdf(tmp_path / name, UPLOAD_LINES, seed=77, caption="Photo 1 : Parcelle de sorgho du lycée")
    r = client.post(f"/api/dossiers/{folder}/documents", headers=H1,
                    files={"file": (name, path.read_bytes(), "application/pdf")})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def statuses(client, folder):
    return {d["id"]: d["status"] for d in client.get(f"/api/dossiers/{folder}", headers=H1).json()["documents"]}


def build(client, folder, headers=H1, **extra):
    body = {"demande": {"sujet": "sorgho fourrager en conditions sèches"}, "sequences": 2} | extra
    r = client.post(f"/api/dossiers/{folder}/corpus-pedagogique", json=body, headers=headers)
    assert r.status_code == 202, r.text
    cid = r.json()["id"]
    st = client.get(f"/api/dossiers/{folder}/corpus-pedagogique/{cid}", headers=headers).json()
    assert st["statut"] == "pret", st
    data = client.get(f"/api/dossiers/{folder}/corpus-pedagogique/{cid}/corpus.json", headers=headers)
    assert data.status_code == 200
    return cid, CorpusPedagogique.model_validate(data.json())


def references(cp):
    return [p.reference for s in cp.sequences for p in s.points] + \
        [x.reference for x in (cp.synthese.paragraphes if cp.synthese else [])]


def page_text(client, doc_id, page):
    """Texte d'une page d'un document du dossier, là où le traitement de Kalil l'a rangé."""
    data = load_text(doc_id, client.ctx.settings.data / "dossiers" / doc_id / "text")
    assert data and 1 <= page <= len(data["pages"])
    return " ".join(data["pages"][page - 1].split())


@pytest.fixture
def folder(app, tmp_path):
    """Dossier de prof1 : 3 documents du catalogue d'exemple (dont 1 décoché), le PDF du catalogue, 1 PDF téléversé."""
    fid = new_folder(app)
    ctx = app.ctx
    ids = {"essai": add_catalog(app, fid, doc_by_file(ctx, "essai_sorgho_2023.txt").id),
           "guide": add_catalog(app, fid, doc_by_file(ctx, "guide_sorgho_implantation.txt").id),
           "decoche": add_catalog(app, fid, doc_by_file(ctx, "temoignage_eleveur_sorgho_2024.txt").id),
           "pdf": add_catalog(app, fid, app.pdf_id),
           "upload": upload(app, fid, tmp_path)}
    assert set(statuses(app, fid).values()) == {"pret"}                       # traitement fini, sans erreur
    r = app.patch(f"/api/dossiers/{fid}/documents/{ids['decoche']}", json={"selected": False}, headers=H1)
    assert r.status_code == 200
    return fid, ids


# ---------------------------------------------------------------------- contenu du corpus
def test_corpus_uses_only_checked_ready_documents(app, folder):
    fid, ids = folder
    _, cp = build(app, fid)
    assert cp.dossier_id == fid
    assert set(cp.doc_ids) == {ids["essai"], ids["guide"], ids["pdf"], ids["upload"]}
    assert ids["decoche"] not in {r.doc_id for r in references(cp)}
    assert ids["decoche"] not in {b.doc_id for b in cp.bibliographie}


def test_references_are_verifiable(app, folder):
    fid, ids = folder
    _, cp = build(app, fid)
    assert references(cp)
    for r in references(cp):
        assert r.doc_id in cp.doc_ids
        assert r.extrait and r.extrait.removeprefix("… ").removesuffix(" …") in page_text(app, r.doc_id, r.page)


def test_links_catalogue_versus_uploaded(app, folder, tmp_path):
    fid, ids = folder
    _, cp = build(app, fid)
    assert {b.doc_id: b for b in cp.bibliographie}[ids["essai"]].catalog_id == \
        doc_by_file(app.ctx, "essai_sorgho_2023.txt").id
    # dossier à 2 documents (PDF du catalogue + PDF téléversé) : les deux sont cités, on vérifie chaque lien
    fid2 = new_folder(app, "Deux PDF")
    ids = {"pdf": add_catalog(app, fid2, app.pdf_id), "upload": upload(app, fid2, tmp_path, "cours2.pdf")}
    _, cp = build(app, fid2)
    biblio = {b.doc_id: b for b in cp.bibliographie}
    up, pdf = biblio[ids["upload"]], biblio[ids["pdf"]]
    assert up.fourni_par_formateur and up.url is None and up.catalog_id is None
    assert pdf.url == CATALOG_PDF_URL and pdf.catalog_id == app.pdf_id and not pdf.fourni_par_formateur
    cited = {r.doc_id for r in references(cp)}
    assert {ids["upload"], ids["pdf"]} <= cited                               # les deux cas sont bien vérifiés
    for r in references(cp):
        if r.doc_id == ids["upload"]:
            assert r.lien is None                                             # fourni par le formateur : sans lien
        elif r.doc_id == ids["pdf"]:
            assert r.lien == f"{CATALOG_PDF_URL}#page={r.page}"              # PDF du catalogue : page citée
        else:
            assert r.lien                                                     # autre document du catalogue


def test_word_and_illustrations_downloadable(app, folder):
    fid, ids = folder
    cid, cp = build(app, fid)
    base = f"/api/dossiers/{fid}/corpus-pedagogique/{cid}"
    word = app.get(f"{base}/corpus_pedagogique.docx", headers=H1)
    assert word.status_code == 200 and word.content[:2] == b"PK"
    assert word.headers["cache-control"] == "private, no-store"
    pytest.importorskip("docx")
    from io import BytesIO

    from docx import Document as Docx

    text = "\n".join(p.text for p in Docx(BytesIO(word.content)).paragraphs)
    assert "Document fourni par le formateur." in text
    assert cp.illustrations                                                   # figures des pages citées
    for ill in cp.illustrations:
        img = app.get(f"{base}/{ill.chemin}", headers=H1)
        assert img.status_code == 200 and img.content


# ---------------------------------------------------------------------- documents privés et modèle en ligne
def test_private_document_excluded_online_then_included_with_consent(app, folder):
    fid, ids = folder
    app.ctx.settings.llm.provider = "litellm"                                 # modèle en ligne simulé
    titre = next(d["title"] for d in app.get(f"/api/dossiers/{fid}", headers=H1).json()["documents"]
                 if d["id"] == ids["upload"])
    cid, cp = build(app, fid)
    assert ids["upload"] not in cp.doc_ids and cp.exclus_prives == [titre]
    sent = " ".join(m.content for c in app.ctx.llm.calls for m in c["messages"])
    assert "lycée" not in sent                                                # rien du PDF privé n'est parti
    st = app.get(f"/api/dossiers/{fid}/corpus-pedagogique/{cid}", headers=H1).json()
    assert st["exclus_prives"] == [titre]
    _, cp2 = build(app, fid, autoriser_documents_prives=True)
    assert ids["upload"] in cp2.doc_ids and cp2.exclus_prives == []
    assert cp2.demande.autoriser_cloud_personnel


def test_uploaded_pdf_images_are_kept(app, tmp_path):
    """Images d'un PDF téléversé par le formateur : reprises (ce sont ses documents, dans son dossier)."""
    fid = new_folder(app, "Seulement mon cours")
    up = upload(app, fid, tmp_path, "cours_seul.pdf")
    _, cp = build(app, fid)
    assert any(ill.doc_id == up and ill.legende.startswith("Photo 1") for ill in cp.illustrations)


# ---------------------------------------------------------------------- droits et garde-fous
def test_access_requires_token_and_folder_rights(app, folder):
    fid, _ = folder
    cid, _ = build(app, fid)
    routes = [("post", f"/api/dossiers/{fid}/corpus-pedagogique"), ("get", f"/api/dossiers/{fid}/corpus-pedagogique"),
              ("get", f"/api/dossiers/{fid}/corpus-pedagogique/{cid}"),
              ("get", f"/api/dossiers/{fid}/corpus-pedagogique/{cid}/corpus.json")]
    body = {"demande": {"sujet": "sorgho"}}
    for method, url in routes:
        kw = {"json": body} if method == "post" else {}
        assert getattr(app, method)(url, **kw).status_code == 401                         # sans jeton
        # autre enseignant, dossier non partagé : 404, comme dans tout le routeur des dossiers (on ne révèle
        # même pas que le dossier existe)
        assert getattr(app, method)(url, headers=H2, **kw).status_code == 404
    r = app.put(f"/api/dossiers/{fid}/partages", json={"email": "prof2@lycee.fr", "role": "lecture"}, headers=H1)
    assert r.status_code == 200
    _, cp = build(app, fid, headers=H2)                                       # le droit de lecture suffit
    assert cp.doc_ids
    assert len(app.get(f"/api/dossiers/{fid}/corpus-pedagogique", headers=H2).json()) == 2


def test_list_and_no_ready_document(app, folder):
    fid, _ = folder
    cid, _ = build(app, fid)
    listing = app.get(f"/api/dossiers/{fid}/corpus-pedagogique", headers=H1).json()
    assert [c["id"] for c in listing] == [cid] and listing[0]["statut"] == "pret"
    assert listing[0]["demande_par"] == "prof1@lycee.fr" and listing[0]["documents"] == 4
    empty = new_folder(app, "Vide")
    r = app.post(f"/api/dossiers/{empty}/corpus-pedagogique", json={"demande": {"sujet": "sorgho"}}, headers=H1)
    assert r.status_code == 409 and "Aucun document coché et prêt" in r.json()["detail"]
    assert app.get(f"/api/dossiers/{empty}/corpus-pedagogique", headers=H1).json() == []


def test_one_build_at_a_time_per_folder(app, folder, monkeypatch):
    """Pendant qu'un corpus se construit, un second lancement sur le même dossier est refusé (409)."""
    import sourcia.api.dossier_corpus as routes

    fid, _ = folder
    started, release = threading.Event(), threading.Event()
    real = routes.build_dossier_corpus

    def slow(*a, **kw):
        started.set()
        release.wait(10)
        return real(*a, **kw)

    monkeypatch.setattr(routes, "build_dossier_corpus", slow)
    first = {}
    t = threading.Thread(target=lambda: first.update(r=app.post(
        f"/api/dossiers/{fid}/corpus-pedagogique", json={"demande": {"sujet": "sorgho"}}, headers=H1)))
    t.start()
    assert started.wait(10)
    second = app.post(f"/api/dossiers/{fid}/corpus-pedagogique", json={"demande": {"sujet": "sorgho"}}, headers=H1)
    running = app.get(f"/api/dossiers/{fid}/corpus-pedagogique", headers=H1).json()
    release.set()
    t.join(20)
    assert second.status_code == 409 and "déjà en construction" in second.json()["detail"]
    assert running[0]["statut"] == "en_cours"
    assert first["r"].status_code == 202
    assert app.get(f"/api/dossiers/{fid}/corpus-pedagogique", headers=H1).json()[0]["statut"] == "pret"


def test_interrupted_build_shown_as_error(app, folder):
    """Un corpus resté « en_cours » après un arrêt du serveur n'est pas bloqué : il apparaît en erreur."""
    from sourcia.formation.dossier_context import write_status

    fid, _ = folder
    stale = app.ctx.settings.data / "dossiers" / "corpus" / fid / "corpus-20260101-080000"
    stale.mkdir(parents=True)
    write_status(stale, id=stale.name, statut="en_cours")
    st = app.get(f"/api/dossiers/{fid}/corpus-pedagogique/{stale.name}", headers=H1).json()
    assert st["statut"] == "erreur" and "interrompue" in st["erreur"]
    cid, _ = build(app, fid)                                                  # on peut relancer
    assert cid != stale.name


def test_downloads_cannot_leave_the_corpus_folder(app, folder):
    fid, _ = folder
    cid, _ = build(app, fid)
    base = f"/api/dossiers/{fid}/corpus-pedagogique"
    # (« illustrations/.. » en clair est simplifié par le client HTTP lui-même : on envoie les points encodés)
    for url in [f"{base}/{cid}/statut.json", f"{base}/{cid}/demande.yaml.bak", f"{base}/{cid}/illustrations/%2E%2E",
                f"{base}/corpus-x/corpus.json", f"{base}/..%2F..%2Fdossiers.sqlite3/corpus.json",
                f"{base}/{cid}/illustrations/..%2Fcorpus.json", f"{base}/{cid}/illustrations/..%5Ccorpus.json",
                f"{base}/{cid}/illustrations/%2E%2E%5C%2E%2E%5Cstatut.json"]:
        assert app.get(url, headers=H1).status_code == 404, url
    assert app.get(f"{base}/{cid}/demande.yaml", headers=H1).status_code == 200


def test_existing_corpus_route_unchanged(app, folder):
    """La route de Kalil (documents cochés + texte) répond comme avant."""
    fid, ids = folder
    docs = app.get(f"/api/dossiers/{fid}/corpus", headers=H1).json()["documents"]
    assert {d["id"] for d in docs} == {ids["essai"], ids["guide"], ids["pdf"], ids["upload"]}
    assert all(d["pages"] for d in docs)


# ---------------------------------------------------------------------- ligne de commande
def test_cli_corpus_from_folder(app, folder, tmp_path, capsys):
    fid, ids = folder
    cfg = tmp_path / "t.yaml"
    cfg.write_text((ROOT / "config/test.yaml").read_text(encoding="utf-8")
                   .replace("data/test-run", str(app.ctx.settings.data).replace("\\", "/")), encoding="utf-8")
    main(["-c", str(cfg), "corpus", "--dossier", fid, "--sujet", "sorgho fourrager", "--sequences", "2"])
    out = capsys.readouterr().out
    assert "corpus.json" in out and "corpus_pedagogique.docx" in out
    listing = app.get(f"/api/dossiers/{fid}/corpus-pedagogique", headers=H1).json()   # visible dans l'API
    assert listing[0]["statut"] == "pret" and listing[0]["demande_par"] == "ligne de commande"
    with pytest.raises(SystemExit):
        main(["-c", str(cfg), "corpus", "--dossier", "inconnu", "--sujet", "sorgho"])
    with pytest.raises(SystemExit):
        main(["-c", str(cfg), "corpus", "--dossier", fid, "--documents", ids["essai"], "--sujet", "sorgho"])
