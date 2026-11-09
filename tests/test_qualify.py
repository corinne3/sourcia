"""M2 Extraction et M3 Qualification : règles, preuves, passe modèle, verrou des documents privés."""
from sourcia.core.models import Fiche
from sourcia.llm.fake import FakeLLM
from sourcia.qualify.llm import evidence_found, qualify_llm
from sourcia.qualify.pipeline import Qualifier
from sourcia.qualify.rules import qualify_rules

from conftest import doc_by_file

TEXT = ("Chambre d'agriculture de Bretagne\nEssai 2021 sur le méteil.\n"
        "Le protocole compare trois modalités avec 4 répétitions.\nSol limoneux, climat océanique.\n")


def test_rules_fill_fields_with_evidence():
    f = qualify_rules(TEXT)
    assert f.get("organisme") == "Chambre d'agriculture de Bretagne"      # le territoire est gardé
    assert f.get("annee") == 2021 and f.get("modalites") == 3 and f.get("repetitions") == 4
    assert f.get("lieu") == "Bretagne"                                  # casse et accents d'origine
    for name in ("organisme", "annee", "modalites"):
        assert getattr(f, name).evidence and getattr(f, name).evidence in TEXT
    assert f.get("chiffrage_economique") is False


def test_publication_year_separate_from_results_year():
    f = qualify_rules(TEXT, doc_date="2023-05-01")
    assert f.get("annee_publication") == 2023 and f.annee_publication.method == "source"
    assert f.get("annee") == 2021                                     # l'essai, pas la publication
    f = qualify_rules("Institut technique. Essais 2017-2019 sur le sorgho.\nPublié en 2021.")
    assert f.get("annee") == 2019 and f.get("annee_publication") == 2021


def test_alert_old_results_in_recent_document(demo_ctx):
    from sourcia.qualify.pipeline import alerts

    f = qualify_rules("Essai 2016 sur le méteil.\nPublié en 2022.")
    assert any("résultats de 2016 publiés en 2022" in a for a in alerts(f, "", demo_ctx.settings))


def test_evidence_check():
    assert evidence_found("Le protocole compare trois modalités", TEXT, 0.6)
    assert not evidence_found("Essai conduit en 2023 à Rennes sur 5 sites", TEXT, 0.6)
    assert not evidence_found(None, TEXT, 0.6)


def champ(v, p):
    return {"valeur": v, "preuve": p}


def llm_answer(year_evidence):
    return {"organisme": champ("Chambre d'agriculture de Bretagne", "Chambre d'agriculture de Bretagne"),
            "annee": champ(2023, year_evidence), "lieu": champ(None, None),
            "contexte_pedoclimatique": champ("sol limoneux, climat océanique", "Sol limoneux, climat océanique."),
            "type": champ("experimentation", "Le protocole compare trois modalités avec 4 répétitions."),
            "modalites": champ(3, "Le protocole compare trois modalités"), "repetitions": champ(4, "avec 4 répétitions"),
            "chiffrage_economique": champ(False, None), "resume": "Essai de méteil."}


def test_llm_value_without_true_evidence_is_rejected():
    f, rep = qualify_llm(FakeLLM(script=[llm_answer("Essai conduit en 2023 sur cinq sites")]), TEXT, 0.6)
    assert f.get("annee") is None and "annee" in rep["rejetes"]        # année inventée : rejetée
    assert f.get("modalites") == 3 and f.modalites.method == "llm"
    assert f.resume == "Essai de méteil."


def test_llm_number_must_appear_in_its_evidence():
    ans = llm_answer("Essai 2021 sur le méteil.")
    ans["annee"] = champ(2023, "Essai 2021 sur le méteil.")              # vraie phrase, mauvaise valeur
    f, rep = qualify_llm(FakeLLM(script=[ans]), TEXT, 0.6)
    assert f.get("annee") is None and "annee" in rep["rejetes"]


def test_qualifier_merges_and_caches(demo_ctx):
    doc = doc_by_file(demo_ctx, "essai_meteil_2016.txt")
    q = Qualifier(demo_ctx.settings, FakeLLM(script=[llm_answer("Méteils fourragers récoltés en ensilage : essai 2016")]))
    f = q.qualify(doc, use_llm=True, force=True)
    assert "llm" in f.passes and f.get("repetitions") == 4
    assert f.repetitions.confidence > 0.7                              # règles et modèle d'accord
    assert any("glyphosate" in a for a in f.alertes)
    assert any("2016" in a for a in f.alertes)
    assert q.qualify(doc, use_llm=True) is f                           # cache : pas de 2e appel


def test_private_document_never_sent_to_cloud(demo_ctx):
    s = demo_ctx.settings
    s.llm.provider = "litellm"
    llm = FakeLLM()
    q = Qualifier(s, llm)
    doc = doc_by_file(demo_ctx, "ancien_support_formation.txt")
    assert doc.private
    q.qualify(doc, use_llm=True, force=True)
    assert llm.calls == []                                             # verrou : aucun appel au modèle en ligne


def test_llm_failure_keeps_rules(demo_ctx):
    q = Qualifier(demo_ctx.settings, FakeLLM(script=["pas du json"] * 5))
    f = q.qualify(doc_by_file(demo_ctx, "essai_sorgho_2023.txt"), use_llm=True, force=True)
    assert f.get("modalites") == 4 and any(p.startswith("llm_echec") for p in f.passes)


def test_fiches_file_roundtrip(demo_ctx):
    demo_ctx.qualifier.save()
    q2 = Qualifier(demo_ctx.settings)
    assert len(q2.fiches) == 8
    assert all(isinstance(f, Fiche) for f in q2.fiches.values())


# Cas réels du 09/11, 23 h 18 (étape 12 : vrais PDF)
def test_real_pdfs_regions_years_and_organisms():
    from sourcia.core.geo import region_of
    from sourcia.qualify.rules import organisme_from_url

    assert region_of("Chambre d'agriculture de Saône-et-Loire, ferme de Jalogny") == "Bourgogne-Franche-Comté"  # pas « Loire »
    assert region_of("Essai Prométerre, canton de Vaud, Suisse") == "Suisse"
    guide = qualify_rules("Chambre d'agriculture de Saône-et-Loire\nSorgho fourrager : conduite technique en 2025\n"
                          "Préconisations de semis. Conseils de récolte. Guide de choix des variétés.", title="sorgho 2025")
    assert guide.get("type") == "guide_technique" and guide.get("annee") is None and guide.get("annee_publication") == 2025
    assert guide.get("organisme") == "Chambre d'agriculture de Saône-et-Loire"
    cr = qualify_rules("Compte rendu des essais 2021-2024. Note 2021 : protocole. Essais sur 4 modalités.")
    assert cr.get("annee") == 2024 and cr.get("annee_publication") is None    # « publié » avant ses résultats : impossible
    assert organisme_from_url("https://www.geves.fr/wp-content/uploads/Sorgho-fourrager.pdf") == "GEVES"
    assert organisme_from_url("https://www.prometerre.ch/s3/site/a.pdf").startswith("Prométerre")


def test_real_pdfs_title_url_year_and_country(ctx, tmp_path):
    from sourcia.core.models import Document
    from sourcia.extract.pdf import extract
    from sourcia.select.funnel import Filters, justify
    from sourcia.core.models import Candidate

    p = tmp_path / "x.txt"
    p.write_text("Résultats d'essais Proconseil\nEssai sorgho monocoupe Compte-rendu 2020\nLes sécheresses répétées…", encoding="utf-8")
    d = Document(id="ch1", url="https://www.prometerre.ch/s3/site/1608792721_20rap01prapportessaissorgho.pdf", source="web",
                 title="1608792721 20rap01prapportessaissorgho", local_path=str(p), status="downloaded",
                 meta={"titre_provisoire": True})
    extract(d, ctx.text_dir, 5)
    assert d.title == "Résultats d'essais Proconseil"                    # première ligne parlante, pas le nom de fichier
    ctx.store.add(d)
    fi = ctx.qualifier.qualify(d)
    c = Candidate(document=d, fiche=fi, passage="x", page=1)
    assert "(Suisse)" in justify(c, Filters(region="Pays de la Loire"))  # pays déduit de l'adresse (.ch)
    q = tmp_path / "s.txt"
    q.write_text("Sorgho de la culture fourragère à la valorisation.", encoding="utf-8")
    d2 = Document(id="w1", url="https://www.sorghum-id.com/content/uploads/2017/10/Synthese.pdf", source="web",
                  title="Synthese", local_path=str(q), status="downloaded")
    extract(d2, ctx.text_dir, 5)
    ctx.store.add(d2)
    assert ctx.qualifier.qualify(d2).get("annee_publication") == 2017    # « /2017/10/ » dans l'adresse
