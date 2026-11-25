"""Illustrations du corpus : un PDF fabriqué avec PyMuPDF contient une vraie figure (avec sa légende), une figure
sans légende, un logo répété, un bandeau et un aplat décoratif ; seules les vraies figures doivent être reprises."""
import pytest

pymupdf = pytest.importorskip("pymupdf")

from sourcia.cli import build_parser                                    # noqa: E402
from sourcia.core.demande import Demande                                # noqa: E402
from sourcia.core.models import Document, doc_id_for                    # noqa: E402
from sourcia.extract.pdf import extract                                 # noqa: E402
from sourcia.formation import illustrations                             # noqa: E402
from sourcia.formation.corpus_pedagogique import (CorpusPedagogique, ParagrapheSynthese, PointCle,  # noqa: E402
                                                  Reference, SequenceCorpus, SyntheseCorpus, build_corpus,
                                                  load_corpus, write_corpus)
from sourcia.formation.illustrations import extract_illustrations      # noqa: E402
from sourcia.llm.fake import FakeLLM                                    # noqa: E402

from test_formation import responder                                    # noqa: E402

CAPTION = "Figure 1 : Rendement du sorgho en année sèche"
PAGE1 = ["Le sorgho fourrager a produit 9,5 t MS/ha en année sèche dans l'essai des Grands Prés.",
         "Le semis du sorgho se fait après le 15 mai dans un sol bien réchauffé et bien préparé.",
         "En sol superficiel, le sorgho fourrager sécurise le stock fourrager de l'exploitation."]
PAGE2 = ["L'implantation du sorgho demande un lit de semences fin et une densité de 25 grains par m2.",
         "Le désherbage du sorgho est délicat au stade jeune car la culture couvre lentement le sol.",
         "La récolte du sorgho en ensilage se fait quand le grain est au stade pâteux dur."]


def gradient(w, h, seed=0):
    """Image « photo » : beaucoup de couleurs et de contraste."""
    data = bytearray()
    for y in range(h):
        for x in range(w):
            data += bytes(((x * 255 // w + seed) % 256, (y * 255 // h + seed) % 256, (x * y + seed * 7) % 256))
    return pymupdf.Pixmap(pymupdf.csRGB, w, h, bytes(data), False)


def make_pdf(path):
    pdf = pymupdf.open()
    p1 = pdf.new_page(width=595, height=842)
    logo = p1.insert_image(pymupdf.Rect(20, 20, 80, 80), pixmap=gradient(200, 200, seed=3))   # logo d'en-tête
    for i, line in enumerate(PAGE1):
        p1.insert_text((100, 100 + 14 * i), line, fontsize=9)
    p1.insert_image(pymupdf.Rect(100, 170, 400, 370), pixmap=gradient(300, 200))               # vraie figure
    p1.insert_text((100, 392), CAPTION, fontsize=10)
    p2 = pdf.new_page(width=595, height=842)
    p2.insert_image(pymupdf.Rect(20, 20, 80, 80), xref=logo)                                   # même logo
    for i, line in enumerate(PAGE2):
        p2.insert_text((100, 100 + 14 * i), line, fontsize=9)
    p2.insert_image(pymupdf.Rect(100, 170, 400, 370), pixmap=gradient(300, 200, seed=90))      # figure sans légende
    p2.insert_image(pymupdf.Rect(50, 420, 550, 470), pixmap=gradient(1600, 160, seed=5))       # bandeau
    flat = pymupdf.Pixmap(pymupdf.csRGB, 300, 300, bytes([200, 200, 200]) * 90000, False)
    p2.insert_image(pymupdf.Rect(100, 500, 300, 700), pixmap=flat)                             # aplat décoratif
    pdf.save(str(path))
    pdf.close()


def add_doc(ctx, path, private=False, title="Essai sorgho illustré", kind="pdf", url=None):
    d = Document(id=doc_id_for(path.as_uri()), url=url or f"https://ex.org/{path.name}", source="ex.org", title=title,
                 private=private, local_path=str(path), kind=kind, status="downloaded")
    ctx.store.add(d)
    d = ctx.store.get(d.id)
    if kind == "pdf":
        extract(d, ctx.text_dir, 40)
        ctx.qualifier.qualify(d)
    return d


@pytest.fixture
def pdf_doc(ctx, tmp_path):
    path = tmp_path / "src" / "essai_sorgho_illustre.pdf"
    path.parent.mkdir()
    make_pdf(path)
    return add_doc(ctx, path)


def corpus_citing(doc_id, seq_pages=(1,), synth_pages=(2,)):
    """Corpus minimal : la séquence 1 cite ``seq_pages``, la synthèse cite ``synth_pages``."""
    pts = [PointCle(texte="x", reference=Reference(doc_id=doc_id, page=p)) for p in seq_pages]
    syn = SyntheseCorpus(paragraphes=[ParagrapheSynthese(texte="y", reference=Reference(doc_id=doc_id, page=p))
                                      for p in synth_pages])
    return CorpusPedagogique(demande=Demande(sujet="sorgho"), titre="t", doc_ids=[doc_id],
                             sequences=[SequenceCorpus(titre="S1", objectif="o", duree_min=30, points=pts)], synthese=syn)


def test_real_figure_kept_with_its_caption(ctx, pdf_doc, tmp_path):
    cp = corpus_citing(pdf_doc.id)
    found = extract_illustrations(cp, ctx, tmp_path / "corpus")
    fig = found[0]
    assert fig.legende == CAPTION and fig.page == 1 and fig.sequence == 1 and fig.doc_id == pdf_doc.id
    assert fig.chemin.startswith("illustrations/") and (tmp_path / "corpus" / fig.chemin).exists()
    saved = pymupdf.Pixmap(str(tmp_path / "corpus" / fig.chemin))
    assert (saved.width, saved.height) == (300, 200)                            # taille d'origine, pas réduite


def test_logos_banners_and_decor_skipped(ctx, pdf_doc, tmp_path):
    cp = corpus_citing(pdf_doc.id)
    found = extract_illustrations(cp, ctx, tmp_path / "corpus")
    assert [(x.page, x.sequence) for x in found] == [(1, 1), (2, None)]          # les deux vraies figures
    note = next(r for r in cp.remarques if r.startswith("illustrations :"))
    assert "2 retenue(s)" in note and "2 logos" in note and "1 bandeaux" in note and "1 décors" in note
    assert len(list((tmp_path / "corpus" / "illustrations").iterdir())) == 2     # rien d'autre copié


def test_default_caption_never_invented(ctx, pdf_doc, tmp_path):
    cp = corpus_citing(pdf_doc.id)
    p2 = extract_illustrations(cp, ctx, tmp_path / "corpus")[1]
    assert p2.legende == "Illustration tirée de « Essai sorgho illustré »" and p2.page == 2


def test_uncited_pages_give_no_image(ctx, pdf_doc, tmp_path):
    cp = corpus_citing(pdf_doc.id, seq_pages=(2,), synth_pages=())
    assert [x.page for x in extract_illustrations(cp, ctx, tmp_path / "corpus")] == [2]


def test_limit(ctx, pdf_doc, tmp_path):
    cp = corpus_citing(pdf_doc.id)
    assert len(extract_illustrations(cp, ctx, tmp_path / "corpus", max_total=1)) == 1
    assert any("au-delà de la limite" in r for r in cp.remarques)


def test_private_document_gives_no_image(ctx, tmp_path):
    path = tmp_path / "prive.pdf"
    make_pdf(path)
    doc = add_doc(ctx, path, private=True, title="Support privé")
    cp = corpus_citing(doc.id)
    assert extract_illustrations(cp, ctx, tmp_path / "corpus") == []
    assert any("documents privés non reprises" in r and "Support privé" in r for r in cp.remarques)


def test_checked_photo_is_copied(ctx, pdf_doc, tmp_path):
    photo = tmp_path / "src" / "parcelle.png"
    gradient(300, 200, seed=40).save(str(photo))
    pdoc = add_doc(ctx, photo, title="Parcelle de sorgho en août", kind="image")
    cp = corpus_citing(pdf_doc.id)
    cp.doc_ids.append(pdoc.id)
    found = extract_illustrations(cp, ctx, tmp_path / "corpus")
    last = found[-1]
    assert last.doc_id == pdoc.id and last.legende == "Parcelle de sorgho en août" and last.sequence is None
    assert (tmp_path / "corpus" / last.chemin).read_bytes() == photo.read_bytes()


def test_without_pymupdf_nothing_breaks(ctx, pdf_doc, tmp_path, monkeypatch):
    monkeypatch.setattr(illustrations, "_pymupdf", lambda: None)
    cp = corpus_citing(pdf_doc.id)
    assert extract_illustrations(cp, ctx, tmp_path / "corpus") == []
    assert any("PyMuPDF manque" in r for r in cp.remarques)


def test_corpus_folder_and_word(ctx, pdf_doc, tmp_path):
    pytest.importorskip("docx")
    from docx import Document as Docx

    from sourcia.formation.export_word import corpus_to_docx

    cp = build_corpus(ctx, "sorgho fourrager", [pdf_doc.id], llm=FakeLLM(responder=responder))
    folder = write_corpus(cp, tmp_path / "corpus", ctx=ctx)[0].parent
    again = load_corpus(folder)
    assert again.illustrations and all((folder / x.chemin).exists() for x in again.illustrations)
    assert any(x.legende == CAPTION for x in again.illustrations)
    word = Docx(str(corpus_to_docx(again, folder / "corpus_pedagogique.docx")))
    assert len(word.inline_shapes) == len(again.illustrations)
    text = "\n".join(p.text for p in word.paragraphs)
    assert f"{CAPTION} (S1, p. 1)" in text
    if any(x.sequence == 1 for x in again.illustrations):                     # rangée dans sa séquence
        assert text.index("Séquence 1 :") < text.index("Figure 1") < text.index("Bibliographie")


def test_adobe_cmyk_jpeg_made_readable_by_word(ctx, tmp_path):
    """Vu sur les fiches Arvalis : JPEG en CMJN sans en-tête JFIF, refusé par python-docx → ré-encodé."""
    pytest.importorskip("docx")
    from docx.image.image import Image

    jpeg = pymupdf.Pixmap(pymupdf.csCMYK, gradient(300, 200, seed=12)).tobytes("jpg")
    with pytest.raises(Exception):
        Image.from_blob(jpeg)                                               # le cas réel est bien reproduit
    path = tmp_path / "cmjn.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    for i, line in enumerate(PAGE1):
        page.insert_text((100, 100 + 14 * i), line, fontsize=9)
    page.insert_image(pymupdf.Rect(100, 170, 400, 370), stream=jpeg)
    pdf.save(str(path))
    pdf.close()
    doc = add_doc(ctx, path, title="Fiche en CMJN")
    found = extract_illustrations(corpus_citing(doc.id, synth_pages=()), ctx, tmp_path / "corpus")
    assert len(found) == 1 and found[0].chemin.endswith(".jpg")
    Image.from_file(str(tmp_path / "corpus" / found[0].chemin))            # lisible par python-docx (et Word)


def test_write_without_ctx_keeps_no_images(ctx, pdf_doc, tmp_path):
    cp = corpus_citing(pdf_doc.id)
    folder = write_corpus(cp, tmp_path / "corpus")[0].parent
    assert load_corpus(folder).illustrations == [] and not (folder / "illustrations").exists()


def test_cli_options():
    a = build_parser().parse_args(["corpus", "--sans-illustrations", "--max-illustrations", "5"])
    assert a.sans_illustrations and a.max_illustrations == 5


def test_caption_label_not_doubled():
    """La légende trouvée dans le PDF commence souvent par « Figure 1 : » : on ne rajoute pas « Figure n : »."""
    from sourcia.formation.illustrations import caption_label

    assert caption_label(2, "Figure 1 : Rendement du sorgho") == "Figure 1 : Rendement du sorgho"
    assert caption_label(2, "Tableau 3 - Doses") == "Tableau 3 - Doses"
    assert caption_label(2, "Illustration tirée de « Essai »").startswith("Illustration tirée")
    assert caption_label(2, "Parcelle en août") == "Figure 2 : Parcelle en août"
    assert caption_label(4, "") == "Figure 4"
