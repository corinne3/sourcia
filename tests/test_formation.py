"""M7 Formation : le modèle est simulé ; on teste NOS contrôles (rien d'inventé ne passe) et les sorties."""
import json
import re

from sourcia.formation import checks
from sourcia.formation.builder import FormationBuilder
from sourcia.core.demande import Demande
from sourcia.formation.render import load, personal_blocks, to_gift, to_markdown, write
from sourcia.formation.schemas import QuestionQCM
from sourcia.llm.fake import FakeLLM

PASSAGE_RE = re.compile(r"\[(\d+)\] \([^\n]*\)\n(.+?)(?=\n\n\[\d+\] |\n\nTâche|\Z)", re.S)


def first_sentence(text):
    return re.split(r"(?<=[.!?])\s", " ".join(text.split()))[0]


def responder(messages, tools, schema):
    """Un « modèle » qui recopie les passages (fidèle) et ajoute UNE invention par contenu."""
    title = (schema or {}).get("title")
    user = messages[-1].content if messages[-1].role == "user" else messages[1].content
    ps = [(int(n), t) for n, t in PASSAGE_RE.findall(user)]
    if title == "PlanFormation" and "DIPLÔMANTE" in user:
        codes = re.findall(r"^- (C[\d.]+) : ", user, re.M)
        return {"titre": "Sorgho et conduite des cultures", "sequences": [
            {"titre": "Adapter la culture du sorgho", "objectif": "Ajuster l'itinéraire du sorgho en année sèche",
             "duree_min": 60, "mots_cles": ["sorgho", "sécheresse"], "capacite": codes[0]},
            {"titre": "Une séquence mal rattachée", "objectif": "Citer les variétés", "duree_min": 30,
             "mots_cles": ["variété"], "capacite": "C9.9"}]}
    if title == "PlanFormation":
        return {"titre": "Le sorgho fourrager", "sequences": [
            {"titre": "Sorgho en conditions sèches", "objectif": "Comparer sorgho et maïs en année sèche",
             "duree_min": 60, "mots_cles": ["sorgho", "sécheresse", "maïs"]},
            {"titre": "Implanter le sorgho", "objectif": "Réussir le semis", "duree_min": 60,
             "mots_cles": ["semis", "implantation", "décompacteur"]}]}
    if title == "FicheSequence":
        pts = [{"texte": first_sentence(t), "source": n} for n, t in ps[:3]]
        pts.append({"texte": "Le sorgho produit 25 t MS/ha sans aucun arrosage en Alaska.", "source": 1})
        return {"points_cles": pts, "a_retenir": "Le sorgho sécurise le stock fourrager."}
    if title == "Quiz":
        qs = []
        for n, t in ps[:3]:
            s = first_sentence(t)
            w = max(re.findall(r"[A-Za-zÀ-ÿ]{6,}", s), key=len)
            qs.append({"enonce": f"Quel mot manque : {s.replace(w, '…')}", "choix": [w, "betterave", "tournesol", "colza"],
                       "explication": s, "bonne_reponse": 0, "source": n})
        qs.append({"enonce": "Quelle est la capitale du sorgho ?", "choix": ["Paris", "Lyon", "Rome", "Oslo"],
                   "explication": "Le sorgho a été inventé à Paris en 1850 par un ingénieur.", "bonne_reponse": 0, "source": 1})
        return {"questions": qs}
    if title == "Glossaire":
        termes = []
        for n, t in ps[:4]:
            s = first_sentence(t)
            w = max(re.findall(r"[A-Za-zÀ-ÿ]{7,}", s), key=len)
            termes.append({"terme": w, "definition": s, "source": n})
        termes.append({"terme": "photosynthèse quantique", "definition": "Un mot inventé.", "source": 1})
        return {"termes": termes}
    if title == "FicheTechnique":
        return {"titre": "Implanter le sorgho", "recommandations": [{"texte": first_sentence(t), "source": n} for n, t in ps[:3]]
                + [{"texte": "Semer 200 kg/ha de sorgho le 1er janvier.", "source": 1}], "vigilance": []}
    if title == "Synthese":
        return {"paragraphes": [{"texte": first_sentence(t), "source": n} for n, t in ps[:3]]
                + [{"texte": "Le sorgho double le revenu de toutes les fermes du monde.", "source": 1}], "conclusion": "Bilan."}
    if title == "ScriptPodcast":
        reps = [{"voix": "animateur", "texte": "Bonjour, de quoi parle-t-on aujourd'hui ?", "source": None}]
        for n, t in ps[:3]:
            reps += [{"voix": "animateur", "texte": "Et que disent les essais ?", "source": None},
                     {"voix": "expert", "texte": first_sentence(t), "source": n}]
        reps.append({"voix": "expert", "texte": "Le sorgho guérit les vaches malades en 3 jours.", "source": 1})
        return {"titre": "Le sorgho", "repliques": reps}
    if title == "CasPratique":
        return {"contexte": "La ferme fictive des Tilleuls manque de fourrage en été.",
                "questions": ["Quelle culture choisir ?", "Quand semer ?"],
                "elements_de_reponse": [{"texte": first_sentence(t), "source": n} for n, t in ps[:2]]}
    return "{}"


def ids(ctx):
    return [d.id for d in ctx.store if not d.title.startswith("Ventilation")]


def test_support_check_rejects_invented_numbers():
    p = "Le sorgho multicoupe a produit 9,5 t MS/ha en deux coupes."
    assert checks.support("Le sorgho multicoupe a produit 9,5 t MS/ha.", p) >= 0.5
    assert checks.support("Le sorgho multicoupe a produit 12 t MS/ha.", p) == 0.0


def test_question_checks():
    p = {1: "La luzerne maintient 70 % de sa production en été sec."}
    good = QuestionQCM(enonce="Quelle plante maintient sa production en été sec ?",
                       choix=["trèfle", "luzerne", "maïs", "colza"],
                       explication="La luzerne maintient 70 % de sa production en été sec.", bonne_reponse=0, source=1)
    ok, note = checks.check_question(good, p, 0.5)
    assert ok and good.bonne_reponse == 1 and "corrigée" in note     # index incohérent avec l'explication : corrigé
    bad = good.model_copy(update={"explication": "Le colza pousse sur la Lune.", "source": 1})
    assert checks.check_question(bad, p, 0.5)[0] is False
    moved = good.model_copy(update={"source": 9})                       # mauvais numéro : rattaché au bon passage
    ok, note = checks.check_question(moved, p, 0.5)
    assert ok and moved.source == 1 and "source corrigée" in note
    assert checks.check_question(bad.model_copy(update={"source": 9}), p, 0.5)[0] is False


# Cas réels du 09/11 (qwen2.5:3b, formation BTSA) : ce qui était retiré à tort, et ce qui doit l'être
MAIZE = "Le sorgho multicoupe a produit 9,5 t MS/ha en deux coupes, contre 7,8 t MS/ha pour le maïs témoin non irrigué."
P = {1: "Méteils fourragers récoltés en ensilage : essai 2016. Le protocole compare 3 modalités de mélanges "
        "céréales-protéagineux, avec 4 répétitions par modalité. Essai conduit en Bretagne sur sol limoneux profond.",
     2: "Conclusion. En sol superficiel et en année sèche, le sorgho fourrager sécurise le stock fourrager. "
        "Implantation après le 15 mai, sol réchauffé.",
     3: "Les mélanges de graminées et de légumineuses résistent mieux au déficit hydrique que les prairies pures."}


def test_real_case_inline_citation_and_wrong_number_kept():
    txt = checks.clean("L'implantation du sorgho fourrager après le 15 mai, dans un sol réchauffé, permet de sécuriser "
                       "le stock fourrager (Sorgho fourrager en conditions sèches : résultats de l'essai 2023, [3]).")
    assert "[3]" not in txt and "2023" not in txt
    assert checks.best_source(txt, P, 3, 0.5)[0] == 2                   # cité [3], trouvé dans [2] : gardé


def test_real_case_crop_mixup_removed():
    txt = "Le sorgho fourrager a été testé en Bretagne en 2016, avec trois modalités de mélange de céréales et protéagineux."
    assert checks.best_source(txt, P, 1, 0.5)[0] is None                # le passage parle de méteils, pas de sorgho
    assert checks.support(MAIZE, MAIZE) == 1.0


def test_real_case_meta_sentence():
    assert checks.is_meta("Le passage [2] montre que le sorgho fourrager a été testé en conditions sèches en 2023.")
    assert not checks.is_meta("Le sorgho fourrager sécurise le stock fourrager.")
    assert checks.is_meta("Le document fictif de 2023, non publié, indique que le sorgho sécurise le stock fourrager.")
    assert not checks.is_meta("Le document d'accompagnement du BTSA a été publié en 2024.")


def test_real_case_capacity_code_in_keywords(demo_ctx):
    from sourcia.formation.schemas import Sequence
    from sourcia.referentiel.models import ReferentielStore

    ref = ReferentielStore(demo_ctx.settings.referentiels_dir).get("btsa-acsagri")
    visees = {c.code: c for c in ref.leaves(["C4.2", "C4.3"])}
    raw = Sequence(titre="Adapter le système d'élevage", objectif="Ajuster la conduite d'un système d'élevage à la sécheresse",
                   duree_min=60, mots_cles=["C4.2", "C4.3", "sorgho"])
    assert FormationBuilder._guess_code(raw, visees, set()) == "C4.3"   # deux codes cités : le libellé tranche



def test_build_keeps_grounded_content_and_removes_inventions(demo_ctx):
    form = FormationBuilder(demo_ctx, FakeLLM(responder=responder)).build("sorgho fourrager", ids(demo_ctx), n_quiz=3)
    assert [s.titre for s in form.sequences] == ["Sorgho en conditions sèches", "Implanter le sorgho"]
    points = [p.texte for s in form.sequences for p in s.points]
    assert points and not any("Alaska" in p for p in points)
    questions = [q.enonce for s in form.sequences for q in s.quiz]
    assert questions and not any("capitale" in q for q in questions)
    assert all(len(s.quiz) <= 3 for s in form.sequences)
    assert form.glossaire and not any("quantique" in g["terme"] for g in form.glossaire)
    assert form.cas_pratique and form.cas_pratique["elements"]
    removed = " ".join(r for s in form.sequences for r in s.retires) + " ".join(form.retires)
    assert "Alaska" in removed and "capitale" in removed and "quantique" in removed


def test_outputs(demo_ctx, tmp_path):
    form = FormationBuilder(demo_ctx, FakeLLM(responder=responder)).build("sorgho fourrager", ids(demo_ctx))
    md, quiz = to_markdown(form, demo_ctx)
    assert "## Annexe A : sources" in md and "(S1, p." in md and "À relire" in md
    assert "⚠️ résultats de 2016" in md or "⚠️ résultats de 2019" in md or "⚠️ résultats de 2021" in md
    assert "Annexe B" in md and "✅" in md and "✅" not in quiz
    gift = to_gift(form)
    assert "::Q1::" in gift and "=" in gift and "####" in gift
    paths = write(form, demo_ctx, tmp_path)
    assert {p.name for p in paths} == {"support_formateur.md", "quiz_apprenants.md", "quiz_moodle.gift.txt",
                                       "formation.json", "demande.yaml"}
    assert json.loads((paths[0].parent / "formation.json").read_text(encoding="utf-8"))["demande"]["sujet"] == "sorgho fourrager"
    assert load(paths[0].parent).titre == form.titre


def test_gift_escapes_special_characters():
    from sourcia.formation.render import _gift_escape

    assert _gift_escape("a = b {c} ~d #e : f") == "a \\= b \\{c\\} \\~d \\#e \\: f"


def test_plan_fallback_without_model(demo_ctx):
    d = Demande(sujet="sorgho fourrager", sorties=["plan", "points_cles", "quiz"])
    form = FormationBuilder(demo_ctx, FakeLLM(script=["pas du json"] * 50)).build(d, ids(demo_ctx))
    assert form.sequences                                             # plan de repli : par thèmes des fiches
    assert all(s.remarques for s in form.sequences if not s.points)   # l'échec est dit, pas caché


def test_private_documents_excluded_with_cloud_model(demo_ctx):
    demo_ctx.settings.llm.provider = "litellm"
    llm = FakeLLM(responder=responder)
    d = Demande(sujet="sorgho fourrager", sorties=["plan", "points_cles", "quiz"])
    form = FormationBuilder(demo_ctx, llm).build(d, ids(demo_ctx))
    assert form.exclus_prives == ["Ancien support de formation : cultures fourragères d'été"]
    sent = " ".join(m.content for c in llm.calls for m in c["messages"])
    assert "Exercice : calculer le stock fourrager" not in sent and "Ancien support" not in sent


def test_all_outputs_checked(demo_ctx):
    d = Demande(sujet="sorgho fourrager", sorties=["plan", "points_cles", "fiche_technique", "synthese", "podcast"],
                modalite="distanciel")
    form = FormationBuilder(demo_ctx, FakeLLM(responder=responder)).build(d, ids(demo_ctx), n_quiz=0)
    assert form.fiche_technique and not any("janvier" in x["texte"] for x in form.fiche_technique["recommandations"])
    assert form.synthese and not any("revenu" in x["texte"] for x in form.synthese["paragraphes"])
    assert form.podcast and not any("guérit" in r["texte"] for r in form.podcast["repliques"])
    assert any(r["voix"] == "animateur" for r in form.podcast["repliques"])     # questions sans chiffre : gardées
    assert form.deroule == [] and form.glossaire == []                          # distanciel écrit : pas de déroulé oral
    paths = write(form, demo_ctx, demo_ctx.settings.path("f", ".keep").parent)
    assert any(p.name == "podcast_script.md" for p in paths)


def test_diplomante_attachment_coverage_and_validation(demo_ctx, tmp_path):
    from sourcia.referentiel.validation import Rattachements

    d = Demande(sujet="sorgho fourrager en conditions sèches", diplomante=True, diplome="btsa-acsagri",
                capacites=["C4.2", "C4.4"], niveau="bts", sorties=["plan", "points_cles"])
    form = FormationBuilder(demo_ctx, FakeLLM(responder=responder)).build(d, ids(demo_ctx))
    assert form.referentiel["id"] == "btsa-acsagri"
    assert form.sequences[0].capacite == "C4.2" and form.sequences[0].capacite_statut == "propose_ia"
    assert form.sequences[1].capacite is None                                  # C9.9 n'existe pas : retiré
    assert any("C9.9" in r and "inexistant" in r for r in form.remarques)
    assert form.sequences[-1].capacite == "C4.4" and form.sequences[-1].capacite_statut == "ajoute_couverture"
    assert all(c["sequences"] for c in form.couverture)                        # tout est couvert
    obj = form.niveau["objectifs"]
    assert obj[1]["alerte"] and "hors du niveau" in obj[1]["alerte"]           # « Citer » trop bas pour un BTS
    paths = write(form, demo_ctx, tmp_path)
    folder = paths[0].parent
    csv_text = (folder / "rattachements.csv").read_text(encoding="utf-8-sig")
    lines = csv_text.splitlines()
    lines[1] = lines[1].rstrip(";") + ";oui;;ok"                               # l'enseignant valide la séquence 1
    (folder / "rattachements.csv").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    from sourcia.referentiel.models import ReferentielStore
    from sourcia.referentiel.validation import import_rattachements_csv

    ref = ReferentielStore(demo_ctx.settings.referentiels_dir).get("btsa-acsagri")
    store = Rattachements(demo_ctx.settings.path("rattachements_valides.jsonl"))
    stats = import_rattachements_csv(form, folder / "rattachements.csv", store, ref, "Mme Test")
    assert stats["valides"] == 1 and form.sequences[0].capacite_statut == "valide"
    form2 = FormationBuilder(demo_ctx, FakeLLM(responder=responder)).build(d, ids(demo_ctx))
    assert form2.sequences[0].capacite_statut == "deja_valide"                  # mémorisé pour la suite


def test_diplomante_fallback_one_sequence_per_capacity(demo_ctx):
    d = Demande(sujet="sorgho", diplomante=True, diplome="btsa-acsagri", capacites=["C4"], sorties=["plan"])
    form = FormationBuilder(demo_ctx, FakeLLM(script=["x"] * 50)).build(d, ids(demo_ctx))
    assert [s.capacite for s in form.sequences] == ["C4.1", "C4.2", "C4.3", "C4.4"]
    assert all(s.capacite_statut == "repli" for s in form.sequences)


def test_personal_content_included_and_preserved(demo_ctx, tmp_path):
    d = Demande(sujet="sorgho fourrager", sorties=["plan", "points_cles"],
                notes_personnelles="Dans notre lycée, le sorgho multicoupe est semé après le méteil, vers le 20 mai.")
    b = FormationBuilder(demo_ctx, FakeLLM(responder=responder))
    form = b.build(d, ids(demo_ctx))
    assert form.personnel_ids
    notes = demo_ctx.store.get(form.personnel_ids[0])
    assert notes.private and notes.title == "Notes personnelles du formateur"
    paths = write(form, demo_ctx, tmp_path)
    md = paths[0].read_text(encoding="utf-8")
    md = md.replace("<!-- PERSONNEL:seq-1 -->\n" + md.split("<!-- PERSONNEL:seq-1 -->\n")[1].split("\n")[0],
                    "<!-- PERSONNEL:seq-1 -->\nMon exemple : la parcelle du lycée, 2024.")
    paths[0].write_text(md, encoding="utf-8")
    write(b.build(d, ids(demo_ctx)), demo_ctx, tmp_path, reprendre=paths[0].parent)
    again = paths[0].read_text(encoding="utf-8")
    assert personal_blocks(again)["seq-1"] == "Mon exemple : la parcelle du lycée, 2024."
    assert (paths[0].parent / "support_formateur.precedent.md").exists()


def test_personal_content_not_sent_to_cloud_without_consent(demo_ctx):
    demo_ctx.settings.llm.provider = "litellm"
    llm = FakeLLM(responder=responder)
    d = Demande(sujet="sorgho fourrager", sorties=["plan", "points_cles"], notes_personnelles="Secret : parcelle 12 du lycée.")
    FormationBuilder(demo_ctx, llm).build(d, ids(demo_ctx))
    assert "parcelle 12" not in " ".join(m.content for c in llm.calls for m in c["messages"])


def test_real_case_vague_sentence_rejected_with_subject_discount():
    from sourcia.core.text import tokenize

    topic = frozenset(tokenize("sorgho fourrager et adaptation des systèmes de culture et d'élevage à la sécheresse"))
    p = ("Sorgho fourrager en conditions sèches : résultats de l'essai 2023. Essai conduit à la ferme expérimentale "
         "des Grands Prés en 2023. Le dispositif comprend 4 modalités.")
    vague = "Le choix du sorgho fourrager est influencé par les résultats d'essais précédents."
    assert checks.support(vague, p) >= 0.5 and checks.support(vague, p, topic) < 0.5   # sans le sujet, il ne reste rien
    meteil = ("Méteils fourragers récoltés en ensilage : essai 2016. Les parcelles ont été désherbées au glyphosate. "
              "Le mélange triticale-pois-vesce a donné le meilleur rendement (8,2 t MS/ha).")
    vrai = "Le mélange triticale-pois-vesce a donné le meilleur rendement (8,2 t MS/ha) dans l'essai 2016 des méteils."
    assert checks.support(vrai, meteil, topic) >= 0.5                  # la culture est dans le TITRE du document


def test_quizgen_values_and_crops():
    from sourcia.formation.quizgen import make_question

    corpus = ["Le mélange triticale-pois-vesce a donné 8,2 t MS/ha.", "La luzerne maintient 70 % de sa production."]
    q = make_question("Le sorgho multicoupe a produit 9,5 t MS/ha, contre 7,8 t MS/ha pour le maïs.", corpus)
    assert q["choix"][q["bonne_reponse"]] == "9,5 t MS/ha" and "7,8 t MS/ha" not in q["choix"]   # pas d'indice dans la phrase
    assert len(set(q["choix"])) == 4 and "……" in q["enonce"]
    q = make_question("Le sorgho fourrager a sécurisé le stock fourrager en année sèche.", corpus)
    assert q["choix"][q["bonne_reponse"]] == "sorgho" and "sorgho" not in q["enonce"]
    assert make_question("Le sorgho fourrager a sécurisé le stock fourrager en année sèche.", corpus,
                         frozenset({"sorgho"})) is None                # culture du sujet : question trop facile
    assert make_question("Une phrase sans valeur ni culture.", corpus) is None


def test_fallback_quiz_when_model_quiz_fails(demo_ctx):
    def resp(messages, tools, schema):
        return "pas du json" if (schema or {}).get("title") == "Quiz" else responder(messages, tools, schema)

    d = Demande(sujet="sorgho fourrager", sorties=["plan", "points_cles", "quiz"])
    b = FormationBuilder(demo_ctx, FakeLLM(responder=resp))
    form = b.build(d, ids(demo_ctx), n_quiz=2)
    quiz = [q for s in form.sequences for q in s.quiz]
    assert quiz and all(q.explication in [p.texte for s in form.sequences for p in s.points] for q in quiz)
    assert any("sans modèle" in r for s in form.sequences for r in s.remarques)
    assert form.echecs_modele and form.echecs_modele[0]["contenu"] == "Quiz"   # réponses invalides gardées pour diagnostic


def test_real_case_looping_definition_is_cut_not_rejected():
    from sourcia.formation.schemas import Glossaire

    loop = "Variété de sorgho cultivée pour le fourrage. " + "Elle est également appelée sorgho fourrager en conditions sèches. " * 30
    g = Glossaire.model_validate({"termes": [{"terme": "Sorgho fourrager", "definition": loop, "source": "[2]"},
                                             {"terme": "Méteil", "definition": "Mélange de céréales et protéagineux.", "source": 1}]})
    assert len(g.termes[0].definition) <= 250 and g.termes[0].definition.endswith(".") and g.termes[0].source == 2
    assert Glossaire.model_json_schema()["$defs"]["Terme"]["properties"]["definition"]["maxLength"] == 250   # borne pour Ollama


# Cas réels du 09/11, 21 h 31 (s3.5) : défauts restants
SORGHO_P3 = ("Sorgho fourrager en conditions sèches : résultats de l'essai 2023. Conclusion. En sol superficiel et en "
             "année sèche, le sorgho fourrager sécurise le stock fourrager. Implantation après le 15 mai, sol réchauffé.")


def test_real_case_leftovers_cleaned():
    assert checks.clean("Le mélange a donné 8,2 t MS/ha lors de l'essai en 2016. Ce résultat est mentionné dans [2].") \
        == "Le mélange a donné 8,2 t MS/ha lors de l'essai en 2016."
    assert checks.clean("Le sorgho sécurise le stock. Ce point est basé sur [3] et [4].") == "Le sorgho sécurise le stock."
    assert "UNE phrase" not in checks.clean("Désherbage au glyphosate. L'explication est UNE phrase reprise du passage cité.")
    assert checks.clean_choice("{A) Semis direct}") == "Semis direct" and checks.clean_choice("B) Le maïs") == "Le maïs"


def test_real_case_wrong_question_rejected():
    q = QuestionQCM(enonce="Quelle est la date limite pour l'implantation du méteil fourragers ?",
                    choix=["{A) Avril}", "{B) Mai}", "{C) Juin}", "{D) Août}"],
                    explication="Implantation après le 15 mai, sol réchauffé.", bonne_reponse=2, source=1)
    ok, why = checks.check_question(q, {1: SORGHO_P3}, 0.65)
    assert not ok and "culture" in why                                  # la question parle de méteil, le passage de sorgho
    q2 = q.model_copy(update={"enonce": "Quelle est la date limite pour l'implantation du sorgho ?"})
    ok, why = checks.check_question(q2, {1: SORGHO_P3}, 0.65)
    assert not ok and "bonne réponse" in why                            # « Juin » n'est pas dans l'explication


def test_real_case_hedge_and_second_sentence_invented():
    p = {1: "Analyse économique : le coût de production du sorgho est de 85 €/t MS."}
    hedged = "Le coût de production du sorgho est de 85 €/t MS, inférieur à celui du maïs (non précisé dans le passage)."
    assert checks.best_source(hedged, p, 1, 0.65)[0] is None
    two = ("Le coût de production du sorgho est de 85 €/t MS. "
           "Il permet de doubler la marge brute des exploitations laitières de montagne.")
    assert checks.best_source(two, p, 1, 0.65)[0] is None                # la 2e phrase est inventée


def test_glossary_general_definition_kept_but_flagged(demo_ctx):
    def resp(messages, tools, schema):
        if (schema or {}).get("title") == "Glossaire":
            return {"termes": [{"terme": "méteil", "definition": "Mélange de céréales et de légumineuses semé ensemble.", "source": 1},
                               {"terme": "ensilage", "definition": "Conservation du fourrage humide, coûte 40 € la tonne.", "source": 1},
                               {"terme": "photosynthèse", "definition": "Processus des plantes.", "source": 1}]}
        return responder(messages, tools, schema)

    d = Demande(sujet="sorgho fourrager", sorties=["glossaire"])
    form = FormationBuilder(demo_ctx, FakeLLM(responder=resp)).build(d, ids(demo_ctx), n_quiz=0)
    terms = {g["terme"]: g for g in form.glossaire}
    assert "méteil" in terms and terms["méteil"]["sourcee"] is False and "éteil" in terms["méteil"]["extrait"]
    assert "ensilage" not in terms                                       # chiffre non sourcé
    assert "photosynthèse" not in terms                                  # absent des sources
    md, _ = to_markdown(form, demo_ctx)
    assert "définition proposée, non sourcée" in md


# Cas réels du 09/11, 21 h 50 (étape 10, agriculteurs à distance)
def test_real_case_step10_citations_frames_and_choices():
    assert checks.clean("Il est recommandé de semer vers le 20 mai (n°5).") == "Il est recommandé de semer vers le 20 mai."
    assert checks.clean("[n] - Le sorgho sécurise le stock. Selon [2], il a permis de passer l'été.") \
        == "Le sorgho sécurise le stock. Il a permis de passer l'été."
    p = "Méteils fourragers récoltés en ensilage : essai 2016. Le mélange triticale-pois-vesce a donné le meilleur rendement (8,2 t MS/ha)."
    framed = ("Une étude sur les méteils fourragers récoltés en ensilage a montré que le mélange triticale-pois-vesce "
              "a donné le meilleur rendement (8,2 t MS/ha).")
    assert checks.support_all(framed, p) >= 0.65                         # le cadre « une étude a montré que » ne compte pas
    q = QuestionQCM(enonce="Quelle culture fourragère permet de sécuriser le stock en année sèche ?",
                    choix=["Sorgho multicoupe (50%)}, {B) Triticale-pois-vesce (40%)}, {C) Maïs témoin (10%)",
                           "La luzerne maintient 70 % de sa production en été sec.", "Le mélange triticale", "L'été 2023"],
                    explication="La luzerne maintient 70 % de sa production en été sec.", bonne_reponse=1, source=1)
    ok, why = checks.check_question(q, {1: "La luzerne maintient 70 % de sa production en été sec."}, 0.65)
    assert not ok and "mal formées" in why


def test_short_personal_note_is_not_flagged_as_scanned(ctx, tmp_path):
    from sourcia.collect.local import scan_folder
    from sourcia.extract.pdf import extract

    (tmp_path / "notes.md").write_text("Semis vers le 20 mai.", encoding="utf-8")
    doc = scan_folder(tmp_path)[0]
    assert extract(doc, ctx.text_dir, 10)["scanned"] is False


def test_real_case_copied_example_objective_replaced(demo_ctx):
    from sourcia.formation.schemas import PlanFormation, Sequence

    plan = PlanFormation(titre="t", sequences=[Sequence(titre="Analyser les mélanges de sorgho", objectif="Comparer …",
                                                        duree_min=30, mots_cles=["sorgho"])])
    seqs, _, notes = FormationBuilder(demo_ctx, FakeLLM()).attach(plan, Demande(sujet="sorgho"), None, "modele")
    assert seqs[0].objectif == "Analyser les mélanges de sorgho" and any("objectif incomplet" in n for n in notes)


def test_private_document_has_no_path_in_csv(demo_ctx, tmp_path):
    from sourcia.export.exporters import rows

    sel = demo_ctx.selector.select("cultures fourragères d'été sorgho", n=8)
    priv = [r for r in rows(sel) if r["prive"]]
    assert priv and all(r["url"] == "" for r in priv)


def test_schema_portable_sans_longueurs():
    from sourcia.llm.litellm_client import _portable
    from sourcia.formation.schemas import Quiz, Glossaire
    for cls in (Quiz, Glossaire):
        txt = str(_portable(cls.model_json_schema()))
        assert "maxLength" not in txt and "pattern" not in txt


def test_erreur_fournisseur_gardee(tmp_path):
    """Une erreur du fournisseur (pas une réponse illisible) est notée dans echecs_modele, avec son message."""
    from sourcia.formation.builder import FormationBuilder
    from sourcia.formation.schemas import Glossaire

    class Boom:
        def chat_structured(self, *a, **k):
            raise RuntimeError("schéma refusé")
        def chat(self, *a, **k):
            raise RuntimeError("schéma refusé")

    class Ctx:
        class settings:
            formation_threshold = 0.65
        llm = Boom()

    b = FormationBuilder(Ctx())
    try:
        from sourcia.core.demande import Demande
        b._ask(Glossaire, "tâche", [], None, Demande(sujet="sorgho"))
    except Exception:
        pass
    assert b.failures and "schéma refusé" in b.failures[-1].get("erreur", "")


SORGHO = ("Le sorgho multicoupe a produit 9,5 t MS/ha en deux coupes, contre 7,8 t MS/ha pour le maïs témoin non irrigué. "
          "Conclusion En sol superficiel et en année sèche, le sorgho fourrager sécurise le stock fourrager. "
          "Implantation après le 15 mai, sol réchauffé.")
LUZERNE = "La luzerne maintient 70 % de sa production en été sec, le trèfle violet 45 %."


def test_reformulation_fidele_acceptee():
    """Vu le 09/11 avec Gemini : des reformulations justes étaient retirées."""
    from sourcia.formation.checks import support_all
    assert support_all("En conditions de sécheresse estivale, la luzerne conserve 70 % de sa production contre 45 % "
                       "pour le trèfle violet.", LUZERNE) >= 0.65
    assert support_all("L'implantation du sorgho doit être réalisée après le 15 mai, une fois que le sol est "
                       "suffisamment réchauffé.", SORGHO) >= 0.65


def test_invention_toujours_refusee():
    from sourcia.formation.checks import support_all
    assert support_all("Le sorgho doit être implanté avant le 15 mai.", SORGHO) == 0.0          # sens inversé
    assert support_all("Le sorgho multicoupe a produit 12 t MS/ha grâce à l'irrigation.", SORGHO) == 0.0
    assert support_all("Le sorgho est plus résistant aux maladies que le maïs.", SORGHO) < 0.5


def test_proposition_chiffree_reconnue():
    from sourcia.formation.checks import choice_scores
    sc = choice_scores("Quelle part de sa production la luzerne garde-t-elle en été sec ?",
                       ["45 %", "70 %", "90 %", "30 %"], "La luzerne maintient 70 % de sa production en été sec.")
    assert sc.index(max(sc)) == 1 and sc[1] == 1.0


def test_ponctuation_orpheline():
    from sourcia.formation.checks import clean
    assert clean("Comparer le sorgho et la luzerne en conditions sèches, [1, 2].").endswith("sèches.")


def test_reformulation_en_double_reperee():
    from sourcia.formation.checks import jaccard, meaning_bag as m
    a = "Pour une implantation réussie du sorgho, il est préconisé d'attendre un sol réchauffé après le 15 mai."
    b = "L'implantation du sorgho doit être réalisée après le 15 mai, une fois que le sol est suffisamment réchauffé."
    c = "Le sorgho multicoupe a produit 9,5 t MS/ha en deux coupes."
    assert jaccard(m(a), m(b)) >= 0.5 and jaccard(m(a), m(c)) < 0.5
