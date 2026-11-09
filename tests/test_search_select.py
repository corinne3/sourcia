"""M4 Recherche, M5 Sélection, M6 Sorties, évaluation."""
import csv
import json

from sourcia.evaluation import bench
from sourcia.export.exporters import export
from sourcia.search.index import expand_query
from sourcia.select.funnel import Filters

from conftest import ROOT


def titles(sel):
    return [c.document.title for c in sel]


def test_synonyms_expand_query():
    assert "decompacteur" in expand_query("fissurateur", [["fissurateur", "décompacteur"]]).lower().replace("é", "e")


def test_search_finds_by_synonym(demo_ctx):
    hits = demo_ctx.index.search("fissurateur avant semis du sorgho", k=3)
    top = demo_ctx.store.get(hits[0].doc_id)
    assert "implantation" in top.title.lower()


def test_selection_relevant_first_and_off_topic_out(demo_ctx):
    sel = demo_ctx.selector.select("sorgho fourrager en conditions sèches", n=10)
    assert "essai 2023" in titles(sel)[0]
    assert not any("porcheries" in t for t in titles(sel))
    assert all(c.justification for c in sel)


def test_filters_year_and_type(demo_ctx):
    q = "sorgho méteil prairie luzerne"
    sel = demo_ctx.selector.select(q, Filters(annee_min=2020, types=["experimentation"]))
    assert not any("2016" in t for t in titles(sel))                  # méteil 2016 exclu
    for c in sel:                                                     # par défaut, une valeur inconnue ne fait pas exclure
        assert c.fiche.get("type") in ("experimentation", None) and (c.fiche.get("annee") or 2020) >= 2020
    strict = demo_ctx.selector.select(q, Filters(annee_min=2020, types=["experimentation"], strict=True))
    assert strict and all(c.fiche.get("type") == "experimentation" and c.fiche.get("annee") >= 2020 for c in strict)


def test_diversity_cap(demo_ctx):
    demo_ctx.settings.select.max_per_source = 1
    sel = demo_ctx.selector.select("sorgho méteil prairie luzerne sécheresse", n=10)
    orgs = [c.fiche.get("organisme") for c in sel if c.fiche and c.fiche.get("organisme")]
    assert len(orgs) == len(set(orgs))


def test_region_alert(demo_ctx):
    sel = demo_ctx.selector.select("méteil ensilage", Filters(region="Occitanie"), n=3)
    meteil = next(c for c in sel if "Méteils" in c.document.title)
    assert "contexte éloigné de Occitanie (Bretagne)" in meteil.justification
    sel = demo_ctx.selector.select("sorgho fourrager", Filters(region="Pays de la Loire"), n=5)
    luz = demo_ctx.selector.select("luzerne stress hydrique", Filters(region="Pays de la Loire"), n=3)
    assert "(Normandie)" in next(c for c in luz if "Luzerne" in c.document.title).justification   # via l'organisme
    for c in sel:                                                     # Vendée, Maine-et-Loire : même région
        if c.document.title.startswith(("Sorgho fourrager", "Le sorgho")):
            assert "contexte éloigné" not in c.justification


def test_exports(demo_ctx, tmp_path):
    sel = demo_ctx.selector.select("sorgho fourrager", n=5)
    paths = {p.suffix: p for p in export(sel, "sorgho fourrager", tmp_path, ("md", "csv", "txt", "json", "zip"))}
    assert set(paths) == {".md", ".csv", ".txt", ".json", ".zip"}
    with open(paths[".csv"], encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert len(rows) == len(sel) and "justification" in rows[0]
    assert "ancien_support" not in paths[".txt"].read_text()          # document privé : pas d'adresse exportée
    assert json.loads(paths[".json"].read_text(encoding="utf-8"))["demande"] == "sorgho fourrager"


def test_eval_find_and_qualify(demo_ctx):
    r = bench.eval_find(demo_ctx, ROOT / "data/samples/eval/demandes.jsonl", n=10)
    assert r["modes"]["hybrid"]["rappel@N"] >= r["modes"]["titres"]["rappel@N"]
    q = bench.eval_qualify(demo_ctx, ROOT / "data/samples/eval/qualification_reference.csv")
    assert q["documents"] == 4
    assert q["champs"]["annee"]["exactitude"] == 1.0


def test_template(demo_ctx, tmp_path):
    p = bench.qualification_template(demo_ctx, tmp_path / "a_remplir.csv", n=3)
    assert len(p.read_text(encoding="utf-8-sig").splitlines()) == 4


def test_dense_only_margin_drops_meaning_only_noise(demo_ctx):
    q = "ventilation des bâtiments"
    assert len(demo_ctx.index.search(q, k=8)) > 1                      # sans marge : le sens fait tout remonter
    demo_ctx.settings.search.dense_only_margin = 0.0
    hits = demo_ctx.index.search(q, k=8)
    assert [demo_ctx.store.get(h.doc_id).title for h in hits][0].startswith("Ventilation")
    assert all("bm25" in h.ranks or h.ranks.get("sim") == max(x.ranks.get("sim", 0) for x in hits) for h in hits)
