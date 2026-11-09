"""Types de ressources (données, photos, vidéos) et référentiels extraits de vrais PDF."""
from pathlib import Path

from sourcia.collect.local import scan_folder
from sourcia.collect.media import kind_of, parse_media
from sourcia.extract.pdf import extract
from sourcia.referentiel.extract import capacities_from_text
from sourcia.referentiel.models import ReferentielStore

from conftest import ROOT


def test_kind_detection():
    assert kind_of("https://www.youtube.com/watch?v=x") == "video"
    assert kind_of("https://x.org/a/b/essais.csv") == "donnees"
    assert kind_of("https://x.org/photo.JPG") == "image"
    assert kind_of("https://x.org/page", hint="Jeu de données") == "donnees"
    assert kind_of("https://x.org/doc.pdf") == "pdf"


def test_parse_media_keeps_meaningful_images_and_videos():
    html = ('<img src="/logo.png" alt="Logo de la chambre agricole"><img src="/i/sorgho.jpg" '
            'alt="Parcelle de sorgho multicoupe en août"><iframe src="https://www.youtube.com/embed/abc" title="Semis du sorgho">'
            '</iframe><a href="/data/rendements.csv">Rendements 2023</a><img src="/x.jpg" alt="court">')
    items = parse_media(html, "https://ex.org/page")
    kinds = {k for _, _, k in items}
    assert kinds == {"image", "video", "donnees"}
    assert not any("logo" in u for u, _, _ in items)
    assert ("https://ex.org/i/sorgho.jpg", "Parcelle de sorgho multicoupe en août", "image") in items


def test_dataset_and_photo_are_indexed_and_flagged(ctx, tmp_path):
    (tmp_path / "rendements_sorgho.csv").write_text("annee;variete;rendement_t_ms_ha\n2023;Multicoupe A;9.5\n", encoding="utf-8")
    (tmp_path / "parcelle.jpg").write_bytes(b"\xff\xd8\xff")
    docs = {Path(d.local_path).suffix: d for d in scan_folder(tmp_path, source="test", private=False)}
    assert docs[".csv"].kind == "donnees" and docs[".jpg"].kind == "image"
    r = extract(docs[".csv"], ctx.text_dir, 10)
    assert "Colonnes : annee, variete, rendement_t_ms_ha" in r["pages"][0] and not r["meta"]["metadonnees_seules"]
    extract(docs[".jpg"], ctx.text_dir, 10)
    ctx.store.add(docs[".jpg"])
    f = ctx.qualifier.qualify(docs[".jpg"])
    assert any("métadonnées" in a for a in f.alertes) and any("droits" in a for a in f.alertes)


def test_web_video_without_file_uses_metadata(ctx):
    from sourcia.core.models import Document

    d = Document(id="v1", url="https://www.youtube.com/watch?v=x", source="yt", kind="video",
                 title="Implanter un sorgho fourrager", meta={"titre_page": "Vidéos techniques fourrages"})
    r = extract(d, ctx.text_dir, 10)
    assert "Implanter un sorgho fourrager" in r["pages"][0] and d.status == "extracted"


def test_capacity_extraction_patterns():
    text = ("C5- Réaliser des choix techniques dans le cadre d’un système de production\n"
            "C5.1- Définir des actions de préservation des ressources C5.2- Réaliser des choix techniques\n\n"
            "Capacité 6 correspondant au bloc de compétences B6 : Manager l’activité d’une entreprise agricole\n\n"
            "C 6.1. Organiser la combinaison des facteurs de production\n"
            "C11 oral + 2\nCP4 – Réaliser des travaux liés à la conduite de l’élevage\n")
    caps = {c.code: c for c in capacities_from_text(text)}
    assert caps["C5.1"].libelle == "Définir des actions de préservation des ressources"
    assert caps["C5.2"].parent == "C5"
    assert caps["C6"].libelle.startswith("Manager") and caps["C6.1"].libelle.startswith("Organiser")
    assert "C11" not in caps                                           # « oral + » : pas un verbe, rejeté
    assert caps["CP4"].libelle.startswith("Réaliser")


def test_shipped_referentials():
    store = ReferentielStore(ROOT / "config" / "referentiels")
    assert set(store.ids()) >= {"capa-ma", "bacpro-cgea", "btsa-acsagri"}
    bts = store.get("btsa-acsagri")
    assert bts.niveau == 5 and [c.code for c in bts.leaves(["C4"])] == ["C4.1", "C4.2", "C4.3", "C4.4"]
    assert bts.get("C4.2").libelle.startswith("Ajuster")
    assert store.get("bacpro-cgea").get("C7.2") and store.get("capa-ma").get("CP5.2")
