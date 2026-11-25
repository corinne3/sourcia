"""Export Word du corpus pédagogique : on relit le .docx produit et on vérifie les références vérifiables."""
import base64
import json
import sys

import pytest

pytest.importorskip("docx")

from docx import Document as Docx                                      # noqa: E402
from docx.opc.constants import RELATIONSHIP_TYPE as RT                  # noqa: E402

from sourcia.cli import main                                            # noqa: E402
from sourcia.core.demande import Demande                                # noqa: E402
from sourcia.formation.corpus_pedagogique import Illustration, build_corpus, load_corpus, write_corpus  # noqa: E402
from sourcia.formation.export_word import corpus_to_docx                # noqa: E402
from sourcia.llm.fake import FakeLLM                                    # noqa: E402

from conftest import ROOT, doc_by_file                                  # noqa: E402
from test_formation import ids, responder                               # noqa: E402

PNG_1PX = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def text_of(path) -> str:
    d = Docx(str(path))
    cells = [c.text for t in d.tables for row in t.rows for c in row.cells]
    return "\n".join([p.text for p in d.paragraphs] + cells)


def links_of(path) -> list[str]:
    return [r.target_ref for r in Docx(str(path)).part.rels.values() if r.reltype == RT.HYPERLINK]


@pytest.fixture
def cp(demo_ctx):
    d = Demande(sujet="sorgho fourrager en conditions sèches", diplomante=True, diplome="btsa-acsagri",
                capacites=["C4.2", "C4.4"], niveau="bts")
    return build_corpus(demo_ctx, d, ids(demo_ctx), llm=FakeLLM(responder=responder))


def test_word_has_sequences_points_extracts_and_references(cp, tmp_path):
    txt = text_of(corpus_to_docx(cp, tmp_path / "c.docx"))
    nums = {b.doc_id: b.numero for b in cp.bibliographie}
    assert cp.titre in txt and "Acquis visés" in txt and "C4.2" in txt and "C4.4" in txt
    points = [pt for s in cp.sequences for pt in s.points]
    assert points and cp.synthese
    for i, s in enumerate(cp.sequences, 1):
        assert f"Séquence {i} : {s.titre}" in txt and s.objectif in txt
    for item in points + cp.synthese.paragraphes:
        r = item.reference
        assert item.texte in txt and r.extrait in txt and f"[{nums[r.doc_id]}, p. {r.page}]" in txt
    assert "Annexe A : retiré par les contrôles" in txt and "Alaska" in txt     # les retraits restent visibles


def test_word_extract_shown_when_point_is_reworded(cp, tmp_path):
    pt = cp.sequences[0].points[0]
    copied = text_of(corpus_to_docx(cp, tmp_path / "a.docx"))
    assert f"« {pt.reference.extrait} »" not in copied                # recopié mot pour mot : pas de doublon
    pt.texte = "Reformulation du point par le modèle."
    reworded = text_of(corpus_to_docx(cp, tmp_path / "b.docx"))
    assert f"« {pt.reference.extrait} »" in reworded                  # reformulé : l'extrait exact est affiché


def test_word_links_open_the_cited_pdf_page(cp, tmp_path):
    ref = cp.sequences[0].points[0].reference
    ref.lien = "https://ex.org/essai.pdf#page=3"                       # un document PDF en ligne
    next(b for b in cp.bibliographie if b.doc_id == ref.doc_id).url = "https://ex.org/essai.pdf"
    path = corpus_to_docx(cp, tmp_path / "c.docx")
    links = links_of(path)
    assert "https://ex.org/essai.pdf#page=3" in links and "https://ex.org/essai.pdf" in links
    assert not any(x.startswith("file:") for x in links)              # pas de chemin local dans le document
    assert "file:" not in text_of(path)


def test_word_bibliography(cp, demo_ctx, tmp_path):
    txt = text_of(corpus_to_docx(cp, tmp_path / "c.docx"))
    assert "Bibliographie" in txt
    for b in cp.bibliographie:
        assert b.titre in txt
        if b.citee:
            assert f"{b.numero}. " in txt
    if any(not b.citee for b in cp.bibliographie):
        assert "Autres documents consultés (non cités)" in txt
    private = doc_by_file(demo_ctx, "ancien_support_formation.txt").title
    assert private in txt and "Document privé, non diffusé." in txt


def test_word_illustrations_inserted_or_reported(cp, tmp_path):
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "fig.png").write_bytes(PNG_1PX)
    did = cp.bibliographie[0].doc_id
    cp.illustrations = [Illustration(chemin="img/fig.png", legende="Essai au champ", doc_id=did, page=2),
                        Illustration(chemin="img/absente.png", legende="", doc_id=did, page=3)]
    path = corpus_to_docx(cp, tmp_path / "c.docx")
    assert len(Docx(str(path)).inline_shapes) == 1
    txt = text_of(path)
    assert f"Figure 1 : Essai au champ ({cp.bibliographie[0].numero}, p. 2)" in txt
    assert "illustration non insérée" in txt and "absente.png" in txt   # dit, sans planter


def test_word_rebuilt_from_edited_json(cp, tmp_path, capsys):
    folder = write_corpus(cp, tmp_path)[0].parent
    data = json.loads((folder / "corpus.json").read_text(encoding="utf-8"))
    data["titre"] = "Titre corrigé à la main"
    (folder / "corpus.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    main(["corpus-word", str(folder)])
    assert "Document Word écrit" in capsys.readouterr().out
    assert "Titre corrigé à la main" in text_of(folder / "corpus_pedagogique.docx")
    main(["corpus-word", str(folder / "corpus.json"), "--sortie", str(tmp_path / "autre.docx")])
    assert (tmp_path / "autre.docx").exists()
    with pytest.raises(SystemExit):
        main(["corpus-word", str(tmp_path / "rien")])


def test_cli_corpus_writes_word(tmp_path, capsys):
    cfg = tmp_path / "t.yaml"
    cfg.write_text((ROOT / "config/test.yaml").read_text(encoding="utf-8").replace("data/test-run", str(tmp_path / "d")),
                   encoding="utf-8")
    main(["-c", str(cfg), "demo"])
    main(["-c", str(cfg), "corpus", "--sequences", "2"])
    assert "corpus_pedagogique.docx" in capsys.readouterr().out
    folder = next((tmp_path / "d" / "corpus").glob("corpus-*"))
    assert load_corpus(folder).titre in text_of(folder / "corpus_pedagogique.docx")


def test_control_characters_from_pdf_do_not_break_word(cp, tmp_path):
    """Vu sur 1 texte réel sur 593 : caractères de contrôle (\\x00, \\x0c…) refusés par python-docx."""
    pt = cp.sequences[0].points[0]
    pt.texte = "Le sorgho\x0c résiste\x00 à la sécheresse."
    pt.reference.extrait = "Le sorgho\x10 résiste à la sécheresse."
    txt = text_of(corpus_to_docx(cp, tmp_path / "c.docx"))
    assert "Le sorgho résiste à la sécheresse." in txt
    assert "\x00" in pt.texte                                         # le corpus lui-même n'est pas modifié


def test_clear_message_without_python_docx(cp, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "docx", None)                    # comme si python-docx n'était pas installé
    with pytest.raises(ImportError, match="pip install"):
        corpus_to_docx(cp, tmp_path / "c.docx")
