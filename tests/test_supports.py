"""Phase 2 : supports (étape 4) à partir d'un corpus.json SEULEMENT.

Le corpus d'exemple figé (tests/fixtures/corpus-exemple, fabriqué à partir de data/samples avec le faux modèle)
a 3 séquences (la 3e sans point), 4 points, 1 illustration (séquence 1) et une source privée (S1).
Chaque test travaille sur une COPIE de ce dossier."""
import csv
import json
import re
import shutil
from pathlib import Path

import pytest

from sourcia.cli import main
from sourcia.formation.corpus_pedagogique import load_corpus
from sourcia.formation.supports import (AVEC_MODELE, SANS_MODELE, SUPPORTS, build_supports, expected_slides,
                                        load_supports, write_supports)
from sourcia.llm.fake import FakeLLM

from conftest import ROOT
from test_formation import responder

FIXTURE = ROOT / "tests" / "fixtures" / "corpus-exemple"
REF_RE = re.compile(r"\[S\d+, p\. \d+\]")
CHIP_RE = re.compile(r"S\d+, page \d+")          # référence en étiquette (infographie, cartes, diapos)
NUM_RE = re.compile(r"\d+(?:[,.]\d+)?")
PRIVATE_TEXT = "Support de cours (document privé du formateur"


@pytest.fixture
def corpus_dir(tmp_path):
    folder = tmp_path / "corpus-20261120-100000"
    shutil.copytree(FIXTURE, folder)
    return folder


@pytest.fixture
def model_ctx(ctx):
    ctx.__dict__["llm"] = FakeLLM(responder=responder)              # modèle simulé (recopie + 1 invention)
    return ctx


def corpus_sentences(cp) -> set[str]:
    return {p.texte for s in cp.sequences for p in s.points} | \
        {p.reference.extrait for s in cp.sequences for p in s.points}


def visible_text(html_text: str) -> str:
    body = re.sub(r"<style.*?</style>", " ", html_text, flags=re.S)
    return re.sub(r"<[^>]+>", " ", body)


# ---------------------------------------------------------------------- production
def test_every_support_is_produced(corpus_dir, model_ctx):
    pytest.importorskip("pptx")
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, SUPPORTS, ctx=model_ctx)
    paths = write_supports(sup, cp, corpus_dir)
    folder = paths[0].parent
    assert folder.parent == corpus_dir / "supports" and folder.name.startswith("supports-")
    assert {p.name for p in paths} == {"supports.json", "qcm_apprenants.md", "qcm_corrige.md", "qcm_moodle.gift.txt",
                                       "cartes_anki.csv", "cartes.html", "infographie.html", "presentation.pptx",
                                       "fiche_technique.md", "glossaire.md", "podcast_script.md"}
    again = load_supports(folder)
    assert again.fichiers == sup.fichiers and again.qcm == sup.qcm
    assert sup.sequences == [1, 2, 3]


def test_subset_of_sequences_only(corpus_dir, model_ctx):
    pytest.importorskip("pptx")
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, [1], SANS_MODELE)
    paths = write_supports(sup, cp, corpus_dir)
    folder = paths[0].parent
    assert sup.sequences == [1]
    assert sup.qcm and all(q.sequence == 1 for q in sup.qcm)
    assert sup.cartes and all(c.sequence == 1 for c in sup.cartes)
    assert all(c.sequence == 1 for c in sup.chiffres)
    for name in ("qcm_corrige.md", "cartes.html", "infographie.html"):
        text = (folder / name).read_text(encoding="utf-8")
        assert cp.sequences[1].titre not in text and "Séquence 2" not in text, name
    from pptx import Presentation

    prs = Presentation(str(folder / "presentation.pptx"))
    texts = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    assert cp.sequences[0].titre in texts and cp.sequences[1].titre not in texts


# ---------------------------------------------------------------------- traçabilité
def test_questions_reuse_supported_sentences_with_reference(corpus_dir):
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, ["qcm"])
    sentences = corpus_sentences(cp)
    biblio = {b.doc_id for b in cp.bibliographie}
    assert sup.qcm
    for q in sup.qcm:
        assert q.explication in sentences                            # une phrase du corpus, contrôlée
        assert REF_RE.fullmatch(q.reference.label()) and q.reference.doc_id in biblio
        stem = re.search(r"« (.*) »", q.enonce, re.S).group(1)
        assert stem.replace("……", q.choix[q.bonne_reponse]) == q.explication   # juste par construction
        assert len(q.choix) == 4 and len({c.lower() for c in q.choix}) == 4
    folder = write_supports(sup, cp, corpus_dir)[0].parent
    corrige = (folder / "qcm_corrige.md").read_text(encoding="utf-8")
    apprenant = (folder / "qcm_apprenants.md").read_text(encoding="utf-8")
    assert len(REF_RE.findall(corrige)) >= len(sup.qcm) and "Réponse" in corrige
    assert "Réponse" not in apprenant and not REF_RE.search(apprenant)     # la version élève n'a pas le corrigé
    gift = (folder / "qcm_moodle.gift.txt").read_text(encoding="utf-8")
    assert "::Q1::" in gift and "####" in gift and r"[S" in gift


def test_cards_traceable_and_csv_has_three_columns(corpus_dir):
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, ["cartes"])
    sentences = {p.texte for s in cp.sequences for p in s.points}
    assert len(sup.cartes) == sum(len(s.points) for s in cp.sequences)       # une carte par point
    for c in sup.cartes:
        assert any(s in c.verso for s in sentences) and REF_RE.fullmatch(c.reference.label())
    folder = write_supports(sup, cp, corpus_dir)[0].parent
    lines = (folder / "cartes_anki.csv").read_text(encoding="utf-8").splitlines()
    assert lines[:3] == ["#separator:Semicolon", "#html:false", "#columns:Recto;Verso;Source"]
    rows = list(csv.reader([x for x in lines if not x.startswith("#")], delimiter=";"))
    assert len(rows) == len(sup.cartes) and all(len(r) == 3 for r in rows)
    assert all(REF_RE.fullmatch(r[2]) for r in rows)


def test_infographic_has_no_number_absent_from_corpus(corpus_dir):
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, ["infographie"])
    folder = write_supports(sup, cp, corpus_dir)[0].parent
    text = visible_text((folder / "infographie.html").read_text(encoding="utf-8"))
    corpus_numbers = set(NUM_RE.findall((corpus_dir / "corpus.json").read_text(encoding="utf-8")))
    shown = set(NUM_RE.findall(text))
    assert shown and shown <= corpus_numbers, shown - corpus_numbers
    raw = (folder / "infographie.html").read_text("utf-8")
    assert "9,5 t MS/ha" in text and CHIP_RE.search(text) and "@page" in raw
    assert "data:font/woff2;base64," in raw and "fonts.googleapis" not in raw      # polices dans le fichier


def test_presentation_slides_notes_and_pictures(corpus_dir):
    pytest.importorskip("pptx")
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, ["presentation"])
    folder = write_supports(sup, cp, corpus_dir)[0].parent
    prs = Presentation(str(folder / "presentation.pptx"))
    slides = list(prs.slides)
    # titre, 3 séquences, 1 illustration, les chiffres clés, les sources
    assert len(slides) == expected_slides(sup, cp, corpus_dir) == 1 + 3 + 1 + 1 + 1
    first = " ".join(sh.text_frame.text for sh in slides[0].shapes if sh.has_text_frame)
    assert cp.titre in first and cp.referentiel["nom"] in first and "C4.2" in first
    assert all(s.background.fill.fore_color.rgb == RGBColor.from_string("F7F8F3") for s in slides)   # fond craie
    titre = next(sh for sh in slides[0].shapes if sh.has_text_frame and sh.text_frame.text == cp.titre)
    assert titre.text_frame.paragraphs[0].runs[0].font.name == "Century Gothic"
    seq1 = " ".join(sh.text_frame.text for sh in slides[1].shapes if sh.has_text_frame)
    assert "Objectif" in seq1 and CHIP_RE.search(seq1)                            # étiquette de référence
    seq1_notes = slides[1].notes_slide.notes_text_frame.text
    assert REF_RE.search(seq1_notes) and "Extrait" in seq1_notes             # références dans les notes
    pictures = [sh for s in slides for sh in s.shapes if sh.shape_type == MSO_SHAPE_TYPE.PICTURE]
    assert len(pictures) == len(cp.illustrations) == 1
    texts = " ".join(sh.text_frame.text for s in slides for sh in s.shapes if sh.has_text_frame)
    assert "Figure 1 : Rendement du sorgho en année sèche (S2, page 1)" in texts
    assert "Figure 1 : Figure 1" not in texts                                # légende du document pas doublée
    chiffres = " ".join(sh.text_frame.text for sh in slides[-2].shapes if sh.has_text_frame)
    assert "Les chiffres clés" in chiffres and "9,5 t MS/ha" in chiffres
    assert "Sources" in [sh.text_frame.text for sh in slides[-1].shapes if sh.has_text_frame]


# ---------------------------------------------------------------------- supports avec modèle
def test_model_supports_keep_only_supported_content(corpus_dir, model_ctx):
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, list(AVEC_MODELE) + ["qcm"], ctx=model_ctx, avec_modele=True)
    fiche = sup.fiche_technique
    assert fiche and not any("janvier" in x["texte"] for x in fiche["recommandations"])
    assert sup.glossaire and not any("quantique" in x["terme"] for x in sup.glossaire)
    assert sup.podcast and not any("guérit" in r["texte"] for r in sup.podcast["repliques"])
    assert not any("capitale" in q.enonce for q in sup.qcm)
    assert any(q.origine == "modele" for q in sup.qcm)                       # le modèle a bien complété
    retires = " ".join(sup.retires)
    assert "janvier" in retires and "quantique" in retires and "guérit" in retires and "capitale" in retires
    for x in fiche["recommandations"] + sup.glossaire:
        assert REF_RE.fullmatch(x["ref"])
    assert sup.appels_modele > 0


def test_private_extracts_not_sent_to_online_model_without_consent(corpus_dir, model_ctx):
    cp = load_corpus(corpus_dir)
    model_ctx.settings.llm.provider = "litellm"                              # modèle en ligne simulé
    sup = build_supports(cp, None, ["fiche", "qcm"], ctx=model_ctx, avec_modele=True)
    sent = " ".join(m.content for c in model_ctx.llm.calls for m in c["messages"])
    assert sent and PRIVATE_TEXT not in sent
    assert any("privé" in r and "non envoyé" in r for r in sup.remarques)
    cp.demande.autoriser_cloud_personnel = True                              # accord dans la demande du corpus
    model_ctx.llm.calls.clear()
    build_supports(cp, None, ["fiche"], ctx=model_ctx)
    assert PRIVATE_TEXT in " ".join(m.content for c in model_ctx.llm.calls for m in c["messages"])


def test_model_supports_without_model_are_reported(corpus_dir):
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, ["qcm", "fiche"], ctx=None)
    assert sup.qcm and sup.fiche_technique is None
    assert any("fiche" in r and "modèle" in r for r in sup.remarques)


def test_without_python_pptx_other_files_still_written(corpus_dir, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pptx", None)                       # comme si python-pptx manquait
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, ["qcm", "presentation"])
    names = {p.name for p in write_supports(sup, cp, corpus_dir)}
    assert "qcm_corrige.md" in names and "presentation.pptx" not in names
    assert any("python-pptx manque" in r for r in sup.remarques)


def test_bad_sequence_or_support_refused(corpus_dir):
    cp = load_corpus(corpus_dir)
    with pytest.raises(ValueError, match="inexistante"):
        build_supports(cp, [4], ["qcm"])
    with pytest.raises(ValueError, match="inconnu"):
        build_supports(cp, None, ["video"])


# ---------------------------------------------------------------------- ligne de commande
def test_cli_supports(corpus_dir, capsys):
    main(["-c", str(ROOT / "config/test.yaml"), "supports", str(corpus_dir), "--sequences", "1",
          "--supports", "qcm,cartes"])
    out = capsys.readouterr().out
    assert "qcm_corrige.md" in out and "cartes_anki.csv" in out and "presentation.pptx" not in out
    with pytest.raises(SystemExit):
        main(["-c", str(ROOT / "config/test.yaml"), "supports", str(corpus_dir), "--sequences", "9"])
    with pytest.raises(SystemExit):
        main(["-c", str(ROOT / "config/test.yaml"), "supports", str(corpus_dir / "rien")])


# ---------------------------------------------------------------------- API : corpus du catalogue
@pytest.fixture
def catalog_client(model_ctx, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from sourcia.api.app import create_app

    monkeypatch.setenv("SOURCIA_DOSSIER_ACCOUNTS", "{}")
    target = model_ctx.settings.path("corpus", ".keep").parent / "corpus-20261120-100000"
    shutil.copytree(FIXTURE, target)
    client = TestClient(create_app(ctx=model_ctx))
    client.corpus_dir = target
    return client


def test_api_catalog_supports(catalog_client):
    pytest.importorskip("pptx")
    c = catalog_client
    r = c.post("/api/supports", json={"corpus_id": "corpus-20261120-100000", "sequences": [1],
                                      "supports": ["qcm", "presentation"]})
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    st = c.get(f"/api/supports/corpus-20261120-100000/{sid}").json()
    assert st["statut"] == "pret" and st["sequences"] == [1] and "presentation.pptx" in st["fichiers"]
    assert [x["id"] for x in c.get("/api/supports/corpus-20261120-100000").json()] == [sid]
    pptx_file = c.get(f"/api/supports/corpus-20261120-100000/{sid}/presentation.pptx")
    assert pptx_file.status_code == 200 and pptx_file.content[:2] == b"PK"
    assert c.get(f"/api/supports/corpus-20261120-100000/{sid}/qcm_corrige.md").status_code == 200


def test_api_catalog_refusals(catalog_client):
    c = catalog_client
    base = {"corpus_id": "corpus-20261120-100000"}
    assert c.post("/api/supports", json=base | {"sequences": [7]}).status_code == 422          # séquence absente
    assert c.post("/api/supports", json=base | {"supports": ["video"]}).status_code == 422     # support inconnu
    assert c.post("/api/supports", json={"corpus_id": "../corpus"}).status_code == 404
    sid = c.post("/api/supports", json=base | {"supports": ["qcm"]}).json()["id"]
    for url in [f"/api/supports/corpus-20261120-100000/{sid}/statut.json",
                f"/api/supports/corpus-20261120-100000/{sid}/%2E%2E%5Ccorpus.json",
                "/api/supports/corpus-20261120-100000/supports-x/qcm_corrige.md",
                f"/api/supports/corpus-x/{sid}/qcm_corrige.md"]:
        assert c.get(url).status_code == 404, url
    (c.corpus_dir / "statut.json").write_text(json.dumps({"statut": "en_cours"}), encoding="utf-8")
    r = c.post("/api/supports", json=base)
    assert r.status_code == 409 and "pas prêt" in r.json()["detail"]


# ---------------------------------------------------------------------- API : corpus d'un dossier enseignant
def test_api_folder_supports_same_rights(monkeypatch, demo_ctx, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("pymupdf")
    import test_dossier_corpus as tdc

    client = tdc.app.__wrapped__(demo_ctx, monkeypatch, tmp_path)          # même application que la phase 1
    fid = tdc.new_folder(client)
    tdc.add_catalog(client, fid, tdc.doc_by_file(demo_ctx, "essai_sorgho_2023.txt").id)
    tdc.add_catalog(client, fid, client.pdf_id)
    cid, cp = tdc.build(client, fid)
    base = f"/api/dossiers/{fid}/corpus-pedagogique/{cid}"
    r = client.post(f"{base}/supports", json={"supports": ["qcm", "cartes", "infographie"]}, headers=tdc.H1)
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    assert client.get(f"{base}/supports/{sid}", headers=tdc.H1).json()["statut"] == "pret"
    listing = client.get(f"{base}/supports", headers=tdc.H1)                 # pas pris pour un fichier du corpus
    assert listing.status_code == 200 and listing.json()[0]["id"] == sid
    assert client.get(f"{base}/supports/{sid}/infographie.html", headers=tdc.H1).status_code == 200
    assert client.get(f"{base}/corpus.json", headers=tdc.H1).status_code == 200   # la route du corpus marche encore
    assert client.get(f"{base}/supports", headers=tdc.H2).status_code == 404       # dossier non partagé
    assert client.get(f"{base}/supports").status_code == 401                        # sans jeton
    assert client.post(f"{base}/supports", json={}, headers=tdc.H2).status_code == 404


# ---------------------------------------------------------------------- corpus vide, longues séquences, cartes
def test_empty_corpus_refused_everywhere(corpus_dir, capsys):
    """Le cas vu chez l'utilisateur : un corpus sans aucun point clé (modèle muet) ne donne pas de supports vides."""
    cp = load_corpus(corpus_dir)
    with pytest.raises(ValueError, match="aucun point clé"):
        build_supports(cp, [3], ["qcm", "presentation"])                       # la séquence 3 n'a aucun point
    with pytest.raises(SystemExit):
        main(["-c", str(ROOT / "config/test.yaml"), "supports", str(corpus_dir), "--sequences", "3"])
    js = (ROOT / "src/sourcia/api/static/parcours.js").read_text(encoding="utf-8")
    assert "c.points === 0" in js and "c.points !== 0" in js                   # signalé, pas proposé aux supports


def test_api_refuses_empty_corpus(catalog_client):
    r = catalog_client.post("/api/supports", json={"corpus_id": "corpus-20261120-100000", "sequences": [3]})
    assert r.status_code == 409 and "aucun point clé" in r.json()["detail"]


def test_long_sequence_split_over_several_slides(corpus_dir):
    """Beaucoup de points : la séquence continue sur une diapo « (suite) », sans rien couper ni déborder."""
    pytest.importorskip("pptx")
    from pptx import Presentation

    from sourcia.formation.presentation import ZONE_POINTS, card_height, paginate

    cp = load_corpus(corpus_dir)
    seq = cp.sequences[0]
    seq.points = [seq.points[1].model_copy(update={"texte": seq.points[1].texte + " " + "Détail de l'essai. " * k})
                  for k in range(9)]
    pages = paginate(seq.points)
    assert len(pages) > 1 and sum(len(p) for p in pages) == 9
    assert all(sum(card_height(x.texte) + 0.14 for x in p) <= ZONE_POINTS[1] - ZONE_POINTS[0] for p in pages if len(p) > 1)
    sup = build_supports(cp, [1], ["presentation"])
    prs = Presentation(str(write_supports(sup, cp, corpus_dir)[0].parent / "presentation.pptx"))
    texts = [" ".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame) for s in prs.slides]
    assert len(prs.slides) == expected_slides(sup, cp, corpus_dir)
    assert any("(suite)" in x for x in texts)


def test_cards_show_the_answer_apart(corpus_dir):
    cp = load_corpus(corpus_dir)
    sup = build_supports(cp, None, ["cartes"])
    cloze = [c for c in sup.cartes if c.reponse]
    assert cloze and all(c.verso == f"{c.reponse}. {c.phrase}" for c in cloze)     # le CSV garde réponse + phrase
    html_text = (write_supports(sup, cp, corpus_dir)[0].parent / "cartes.html").read_text(encoding="utf-8")
    assert f"Réponse : <strong>{cloze[0].reponse}</strong>" in html_text


def test_podcast_lines_reusing_verified_points_are_kept(corpus_dir, ctx):
    """Vu avec Gemini le 22/11 : l'expert reprend un point clé (déjà vérifié contre la source) avec des mots qui
    ne sont pas dans l'extrait court ; ces répliques étaient toutes retirées et le podcast n'était pas produit."""
    from sourcia.formation.supports import CorpusPassages, items_of

    cp = load_corpus(corpus_dir)
    p1, p3 = cp.sequences[0].points[1], cp.sequences[0].points[2]
    p1.texte = "Le sorgho fourrager a produit 9,5 t MS/ha en année sèche, davantage que le maïs témoin."
    p3.texte = "En sol superficiel et en année sèche, le sorgho fourrager sécurise mieux le stock fourrager que le maïs."
    passages = CorpusPassages(cp, items_of(cp, [1])).passages
    assert any(p1.texte in p.text and p1.reference.extrait in p.text for p in passages)   # extrait + point

    def podcast(messages, tools, schema):
        return {"titre": "Le sorgho", "repliques": [
            {"voix": "animateur", "texte": "Que disent les essais ?", "source": None},
            {"voix": "expert", "texte": p1.texte, "source": 1},
            {"voix": "animateur", "texte": "Et en sol superficiel ?", "source": None},
            {"voix": "expert", "texte": p3.texte, "source": 2},
            {"voix": "animateur", "texte": "Et pour les vaches malades ?", "source": None},
            {"voix": "expert", "texte": "Le sorgho guérit les vaches malades en 3 jours.", "source": 1}]}

    ctx.__dict__["llm"] = FakeLLM(responder=podcast)
    sup = build_supports(cp, [1], ["podcast"], ctx=ctx)
    assert sup.podcast, sup.retires
    experts = [r["texte"] for r in sup.podcast["repliques"] if r["voix"] == "expert"]
    assert p1.texte in experts and p3.texte in experts
    assert not any("guérit" in t for t in experts) and any("guérit" in r for r in sup.retires)   # invention retirée
    assert all(REF_RE.fullmatch(r["ref"]) for r in sup.podcast["repliques"] if r["voix"] == "expert")
    voices = [r["voix"] for r in sup.podcast["repliques"]]
    assert "Et pour les vaches malades ?" not in [r["texte"] for r in sup.podcast["repliques"]]  # question orpheline
    assert all(not (a == b == "animateur") for a, b in zip(voices, voices[1:]))   # jamais deux questions à la suite
