"""Étape 3 : corpus pédagogique. Le modèle est simulé (test_formation.responder : il recopie les passages et
ajoute UNE invention par contenu) ; on teste que tout vient des documents cochés, avec des références vérifiables."""
import json
from types import SimpleNamespace

import pytest

from sourcia.cli import build_parser, main
from sourcia.core.demande import Demande
from sourcia.core.models import Document
from sourcia.extract.pdf import load_text
from sourcia.formation.corpus_pedagogique import (MAX_EXTRACT, build_corpus, load_corpus, page_link, shorten,
                                                  source_url, write_corpus)
from sourcia.llm.fake import FakeLLM

from conftest import ROOT, doc_by_file
from test_formation import ids, responder

SORGHO = ("essai_sorgho_2023.txt", "guide_sorgho_implantation.txt", "temoignage_eleveur_sorgho_2024.txt")


def schemas(llm):
    return [(c["schema"] or {}).get("title") for c in llm.calls]


def references(cp):
    return [p.reference for s in cp.sequences for p in s.points] + \
        [x.reference for x in (cp.synthese.paragraphes if cp.synthese else [])]


def sent_to_model(llm):
    return " ".join(m.content for c in llm.calls for m in c["messages"])


def test_only_checked_documents(demo_ctx):
    checked = [doc_by_file(demo_ctx, n).id for n in SORGHO]
    llm = FakeLLM(responder=responder)
    cp = build_corpus(demo_ctx, "sorgho fourrager", checked, llm=llm)
    assert set(cp.doc_ids) == set(checked)
    assert references(cp) and {r.doc_id for r in references(cp)} <= set(checked)
    assert {b.doc_id for b in cp.bibliographie} == set(checked)
    other = doc_by_file(demo_ctx, "luzerne_secheresse_2021.txt")
    assert other.title not in sent_to_model(llm)                       # un document non coché n'est jamais envoyé


def test_no_quiz_and_inventions_removed(demo_ctx):
    d = Demande(sujet="sorgho fourrager", sorties=["plan", "quiz"])    # même si la demande prévoit un QCM
    llm = FakeLLM(responder=responder)
    cp = build_corpus(demo_ctx, d, ids(demo_ctx), llm=llm)
    assert "Quiz" not in schemas(llm) and schemas(llm).count("Synthese") == 1
    assert [s.titre for s in cp.sequences] == ["Sorgho en conditions sèches", "Implanter le sorgho"]
    points = [p.texte for s in cp.sequences for p in s.points]
    assert points and not any("Alaska" in p for p in points)
    assert cp.synthese and not any("revenu" in x.texte for x in cp.synthese.paragraphes)
    removed = " ".join(r for s in cp.sequences for r in s.retires) + " ".join(cp.retires)
    assert "Alaska" in removed and "revenu" in removed
    assert cp.demande.sorties == ["plan", "quiz"]                      # la demande est gardée telle quelle


def test_extracts_are_exact_sentences_of_the_cited_page(demo_ctx):
    cp = build_corpus(demo_ctx, "sorgho fourrager", ids(demo_ctx), llm=FakeLLM(responder=responder))
    assert references(cp)
    for r in references(cp):
        page = " ".join(load_text(r.doc_id, demo_ctx.text_dir)["pages"][r.page - 1].split())
        assert r.extrait and r.extrait.removeprefix("… ").removesuffix(" …") in page


def test_long_sentence_shortened_around_the_point():
    """Un tableau extrait d'un PDF peut former une « phrase » de 1 000 caractères (vu le 20/11 sur Arvalis)."""
    from sourcia.core.text import tokenize

    filler = " ".join(f"colonne{i} RGI Alternatif T. incarnat" for i in range(40))
    sentence = f"{filler} le sorgho multicoupe résiste à la sécheresse estivale {filler}"
    out = shorten(sentence, set(tokenize("Le sorgho multicoupe résiste à la sécheresse.")))
    assert len(out) <= MAX_EXTRACT + 4 and out.startswith("… ") and out.endswith(" …")
    assert "sorgho multicoupe résiste à la sécheresse" in out
    assert out.removeprefix("… ").removesuffix(" …") in sentence             # toujours recopié mot pour mot
    assert shorten("Phrase courte.", set()) == "Phrase courte."


def test_diplomante_sequences_attached_to_capacities(demo_ctx):
    d = Demande(sujet="sorgho fourrager en conditions sèches", diplomante=True, diplome="btsa-acsagri",
                capacites=["C4.2", "C4.4"], niveau="bts")
    cp = build_corpus(demo_ctx, d, ids(demo_ctx), llm=FakeLLM(responder=responder))
    assert cp.referentiel["id"] == "btsa-acsagri"
    assert [c["code"] for c in cp.capacites_visees] == ["C4.2", "C4.4"]
    assert cp.sequences[0].capacite == "C4.2" and cp.sequences[0].capacite_statut == "propose_ia"
    assert cp.sequences[1].capacite is None                            # C9.9 n'existe pas : retiré
    assert cp.sequences[-1].capacite == "C4.4" and cp.sequences[-1].capacite_statut == "ajoute_couverture"
    assert all(c["sequences"] for c in cp.couverture)


def test_diplomante_without_model_one_sequence_per_capacity(demo_ctx):
    d = Demande(sujet="sorgho", diplomante=True, diplome="btsa-acsagri", capacites=["C4"])
    cp = build_corpus(demo_ctx, d, ids(demo_ctx), llm=FakeLLM(script=["x"] * 50))
    assert [s.capacite for s in cp.sequences] == ["C4.1", "C4.2", "C4.3", "C4.4"]
    assert any("synthèse non produite" in r for r in cp.remarques)     # l'échec est dit, pas caché


def test_bibliography(demo_ctx):
    cp = build_corpus(demo_ctx, "sorgho fourrager", ids(demo_ctx), llm=FakeLLM(responder=responder))
    cited = [b for b in cp.bibliographie if b.citee]
    assert [b.numero for b in cited] == [f"S{i}" for i in range(1, len(cited) + 1)]
    first = list(dict.fromkeys(r.doc_id for r in references(cp)))
    assert [b.doc_id for b in cited] == first                          # ordre de première citation
    for b in cited:
        assert set(b.pages_citees) == {r.page for r in references(cp) if r.doc_id == b.doc_id}
        fi = demo_ctx.qualifier.get(b.doc_id)
        assert b.organisme == (fi.get("organisme") or None)
    assert all(b.numero == "" for b in cp.bibliographie if not b.citee)
    private = doc_by_file(demo_ctx, "ancien_support_formation.txt").id
    assert all(b.url is None for b in cp.bibliographie if b.doc_id == private)
    assert all(r.lien is None for r in references(cp) if r.doc_id == private)
    public = next(b for b in cited if b.doc_id != private)
    assert public.url and public.titre


def test_page_link_for_pdf_only():
    pdf = Document(id="a", url="https://ex.org/essai.pdf", source="ex.org", kind="pdf")
    assert page_link(pdf, 3) == "https://ex.org/essai.pdf#page=3"
    assert page_link(pdf.model_copy(update={"url": "https://ex.org/essai.pdf#page=1"}), 4) == "https://ex.org/essai.pdf#page=4"
    article = Document(id="b", url="https://ex.org/article", source="ex.org", kind="page")
    assert page_link(article, 2) == "https://ex.org/article"
    assert page_link(pdf.model_copy(update={"private": True}), 3) is None
    moved = SimpleNamespace(private=False, url="https://old.org/a.pdf", current_url="https://new.org/a.pdf", kind="pdf")
    assert source_url(moved) == "https://new.org/a.pdf" and page_link(moved, 2) == "https://new.org/a.pdf#page=2"


def test_personal_content_not_in_corpus(demo_ctx):
    d = Demande(sujet="sorgho fourrager", notes_personnelles="Dans notre lycée, le sorgho est semé vers le 20 mai.")
    llm = FakeLLM(responder=responder)
    cp = build_corpus(demo_ctx, d, ids(demo_ctx), llm=llm)
    assert "notre lycée" not in sent_to_model(llm)
    assert set(cp.doc_ids) <= set(ids(demo_ctx))
    assert any("contenu personnel non repris" in r for r in cp.remarques)


def test_write_and_reload(demo_ctx, tmp_path):
    cp = build_corpus(demo_ctx, "sorgho fourrager", ids(demo_ctx), llm=FakeLLM(responder=responder))
    paths = write_corpus(cp, tmp_path)
    folder = paths[0].parent
    assert folder.name.startswith("corpus-") and {p.name for p in paths} == {"corpus.json", "demande.yaml"}
    data = json.loads((folder / "corpus.json").read_text(encoding="utf-8"))
    assert data["illustrations"] == [] and data["demande"]["sujet"] == "sorgho fourrager"
    assert load_corpus(folder) == cp and load_corpus(paths[0]) == cp
    again = write_corpus(cp, tmp_path)[0].parent                       # même seconde : pas d'écrasement
    assert again != folder and (folder / "corpus.json").exists()


def test_cli_corpus(tmp_path, capsys):
    cfg = tmp_path / "t.yaml"
    cfg.write_text((ROOT / "config/test.yaml").read_text(encoding="utf-8").replace("data/test-run", str(tmp_path / "d")),
                   encoding="utf-8")
    main(["-c", str(cfg), "demo"])                                     # exporte une sélection
    capsys.readouterr()
    main(["-c", str(cfg), "corpus", "--sequences", "2"])               # la dernière sélection
    out = capsys.readouterr().out
    assert "Sélection lue" in out and "corpus.json" in out
    sel = json.loads(next((tmp_path / "d" / "exports").glob("selection-*.json")).read_text(encoding="utf-8"))
    sel_ids = [r["id"] for r in sel["documents"]]
    folders = sorted((tmp_path / "d" / "corpus").glob("corpus-*"))
    assert len(folders) == 1 and set(load_corpus(folders[0]).doc_ids) <= set(sel_ids)
    main(["-c", str(cfg), "corpus", "--documents", ",".join(sel_ids[:2]), "--sujet", "sorgho fourrager"])
    capsys.readouterr()
    last = sorted((tmp_path / "d" / "corpus").glob("corpus-*"), key=lambda p: p.stat().st_mtime)[-1]
    assert load_corpus(last).doc_ids == sel_ids[:2]                    # seulement les documents cochés
    with pytest.raises(SystemExit):
        main(["-c", str(cfg), "corpus", "--documents", "inconnu", "--sujet", "sorgho"])


def test_parser_has_corpus():
    a = build_parser().parse_args(["corpus", "--documents", "a,b", "--capacites", "C4.2", "--sequences", "3"])
    assert a.documents == "a,b" and a.capacites == "C4.2" and a.sequences == 3
