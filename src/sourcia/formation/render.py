"""Sorties de la formation (dossier ``data/formations/formation-<date>/``) :

- ``support_formateur.md`` : la demande, le rattachement au référentiel, le contrôle du niveau, le plan,
  les séquences (points clés sourcés, QCM avec corrigé, BLOCS PERSONNELS), fiche technique, synthèse,
  glossaire, cas concret, déroulé de séance, annexes (sources et alertes ; ce qui a été retiré) ;
- ``quiz_apprenants.md`` (sans réponses), ``quiz_moodle.gift.txt`` (import Moodle) ;
- ``podcast_script.md`` (si demandé), ``rattachements.csv`` (à valider par l'enseignant, si diplômante) ;
- ``formation.json`` (tout, rechargeable), ``demande.yaml`` (la demande, réutilisable).

Blocs personnels : ``<!-- PERSONNEL:cle -->…<!-- /PERSONNEL:cle -->``. Ce que le formateur y écrit est
CONSERVÉ quand on régénère le support (``--reprendre``).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

LETTERS = "ABCD"
STATUT_LABEL = {"propose_ia": "proposé par l'IA, à valider", "repli": "proposé (plan sans modèle), à valider",
                "ajoute_couverture": "ajouté pour couvrir la capacité, à valider", "deja_valide": "✅ déjà validé",
                "valide": "✅ validé", "refuse": "❌ refusé", "aucune": "—"}
BLOCK_RE = re.compile(r"<!-- PERSONNEL:(?P<k>[\w-]+) -->\n(?P<body>.*?)\n<!-- /PERSONNEL:(?P=k) -->", re.S)
PLACEHOLDER = "_(Espace personnel : écris ici tes ajouts. Ce bloc est conservé si tu régénères le support.)_"


class SourceRefs:
    """Numérote les documents (S1, S2…) dans l'ordre de leur première citation."""

    def __init__(self):
        self.order: list[str] = []

    def ref(self, doc_id: str | None, page: int | None) -> str:
        if not doc_id:
            return "sans source"
        if doc_id not in self.order:
            self.order.append(doc_id)
        return f"S{self.order.index(doc_id) + 1}, p. {page}"


def personal_blocks(md: str) -> dict[str, str]:
    return {m.group("k"): m.group("body") for m in BLOCK_RE.finditer(md)}


def _block(key: str, keep: dict[str, str]) -> list[str]:
    return [f"<!-- PERSONNEL:{key} -->", keep.get(key, PLACEHOLDER), f"<!-- /PERSONNEL:{key} -->", ""]


def _gift_escape(s: str) -> str:
    for ch in "\\~=#{}:":
        s = s.replace(ch, "\\" + ch)
    return " ".join(s.split())


def to_gift(form) -> str:
    out = [f"// {form.titre} — généré par SourcIA, à relire avant usage", ""]
    k = 0
    for s in form.sequences:
        out += [f"$CATEGORY: {_gift_escape(s.titre)}", ""]
        for q in s.quiz:
            k += 1
            opts = " ".join(("=" if j == q.bonne_reponse else "~") + _gift_escape(c) for j, c in enumerate(q.choix))
            out += [f"::Q{k}:: {_gift_escape(q.enonce)} {{ {opts} #### {_gift_escape(q.explication)} }}", ""]
    return "\n".join(out)


def _demande_table(d) -> list[str]:
    def j(x):
        return ", ".join(x) if x else "toutes"
    rows = [
        ("1. Profil du demandeur", d.profil),
        ("2. Type de formation", ("diplômante" + (f" ({d.diplome} : {', '.join(d.capacites)})" if d.diplome else ""))
         if d.diplomante else "non diplômante"),
        ("   Modalité et supports", f"{d.modalite} ; {', '.join(d.supports)} ; {d.duree_min} min"),
        ("3. Public", f"{d.apprenants}, niveau {d.niveau}, {d.experience}" + (f", {d.effectif} pers." if d.effectif else "")),
        ("4. Ressources", j(d.ressources)),
        ("5. Résultats attendus", j(d.sorties)),
        ("6. Sources", f"années {d.annee_min or '…'}–{d.annee_max or '…'}"
         + (" ; publiques seulement" if d.sources_publiques_seulement else " ; publiques et privées")
         + (f" ; région {d.region}" if d.region else "") + (f" ; à privilégier : {', '.join(d.organismes)}" if d.organismes else "")),
        ("7. Contenu personnel", ("notes" if d.notes_personnelles.strip() else "")
         + (f"{' + ' if d.notes_personnelles.strip() else ''}{len(d.fichiers_personnels)} fichier(s)" if d.fichiers_personnels else "")
         or "aucun (blocs personnels disponibles ci-dessous)"),
    ]
    return ["| Critère | Valeur |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows] + [""]


def to_markdown(form, ctx, keep: dict[str, str] | None = None) -> tuple[str, str]:
    keep = keep or {}
    d = form.demande
    refs = SourceRefs()
    L = [f"# {form.titre}", "",
         f"- **Sujet** : {d.sujet}",
         f"- **Préparé le** : {datetime.now():%d/%m/%Y} avec SourcIA ({form.appels_modele} appels au modèle, {form.duree_s} s)",
         "",
         "> ⚠️ Contenu généré par IA à partir des sources listées en annexe A, puis contrôlé dans le code "
         "(chaque information doit se retrouver dans sa source). **À relire et valider avant diffusion.**", ""]
    if form.exclus_prives:
        L += [f"> 🔒 Documents privés non envoyés au modèle en ligne : {', '.join(form.exclus_prives)}", ""]
    L += ["## La demande", ""] + _demande_table(d)
    L += _block("introduction", keep)
    # référentiel
    if form.referentiel:
        r = form.referentiel
        L += ["## Rattachement au référentiel", "",
              f"**{r['nom']}** (version {r['version']}, référentiel {'validé' if r['statut'] == 'valide' else 'extrait automatiquement, à valider'})", "",
              "| # | Séquence | Capacité | Statut |", "|---|---|---|---|"]
        for i, s in enumerate(form.sequences, 1):
            cap = f"{s.capacite} : {s.capacite_libelle}" if s.capacite else "—"
            L.append(f"| {i} | {s.titre} | {cap} | {STATUT_LABEL.get(s.capacite_statut, s.capacite_statut)} |")
        L += ["", "**Couverture des capacités visées**", ""]
        for c in form.couverture:
            L.append(f"- {'✅' if c['sequences'] else '❌'} **{c['code']}** {c['libelle']}"
                     + (f" → séquence(s) {', '.join(map(str, c['sequences']))}" if c["sequences"] else " → non couverte"))
        L += ["", "_Valider : remplir `rattachements.csv` puis `sourcia valider-formation <dossier> --par \"Nom\"`._", ""]
    # niveau
    if form.niveau:
        L += ["## Contrôle du niveau", "", "| Séquence | Verbe de l'objectif | Niveau (1 à 6) | Attendu | Alerte |", "|---|---|---|---|---|"]
        for o in form.niveau.get("objectifs", []):
            L.append(f"| {o['sequence']} | {o['verbe'] or '—'} | {o['niveau_bloom'] or '?'} | {o['attendu']}"
                     + (f" (capacité {o['capacite']} : « {o['verbe_capacite']} », {o['niveau_capacite']})" if o.get("capacite") else "")
                     + f" | {o['alerte'] or '✅'} |")
        lis = form.niveau.get("lisibilite", {})
        if lis.get("lisibilite") is not None:
            L.append("")
            L.append(f"- Lisibilité du texte (Kandel-Moles) : **{lis['lisibilite']}** (minimum proposé pour ce public : {lis['minimum']})"
                     + (f" ⚠️ {lis['alerte']}" if lis.get("alerte") else " ✅"))
        L += ["", "_Niveaux de Bloom : 1 se souvenir · 2 comprendre · 3 appliquer · 4 analyser · 5 évaluer · 6 créer. Seuils à calibrer avec les enseignants._", ""]
    # plan
    L += ["## Plan", "", "| # | Séquence | Objectif | Durée |", "|---|---|---|---|"]
    L += [f"| {i} | {s.titre} | {s.objectif} | {s.duree_min} min |" for i, s in enumerate(form.sequences, 1)]
    L.append("")
    Q = [f"# QCM : {form.titre}", "", "_Une seule bonne réponse par question._", ""]
    qn = 0
    for i, s in enumerate(form.sequences, 1):
        L += [f"## Séquence {i} : {s.titre}", "", f"**Objectif** : {s.objectif}"
              + (f" · *capacité {s.capacite}*" if s.capacite else "") + f" · {s.duree_min} min", ""]
        if s.points:
            L += ["### Points clés", ""] + [f"- {p.texte} *({refs.ref(p.doc_id, p.page)})*" for p in s.points] + [""]
        if s.a_retenir:
            L += [f"**À retenir** : {s.a_retenir}", ""]
        if s.quiz:
            L += ["### QCM (avec corrigé)", ""]
            Q += [f"## {s.titre}", ""]
            for q in s.quiz:
                qn += 1
                L.append(f"**Q{qn}. {q.enonce}**")
                Q.append(f"**Q{qn}. {q.enonce}**")
                for j, c in enumerate(q.choix):
                    L.append(f"- {LETTERS[j]}. {c}" + (" ✅" if j == q.bonne_reponse else ""))
                    Q.append(f"- [ ] {LETTERS[j]}. {c}")
                L += [f"  - *Réponse {LETTERS[q.bonne_reponse]}* : {q.explication} *({refs.ref(q.doc_id, q.page)})*", ""]
                Q.append("")
        L += [f"> 📝 {r}" for r in s.remarques] + ([""] if s.remarques else [])
        L += _block(f"seq-{i}", keep)
    if form.fiche_technique:
        f = form.fiche_technique
        L += [f"## Fiche technique : {f['titre']}", "", "**Recommandations**", ""]
        L += [f"- {x['texte']} *({refs.ref(x['doc_id'], x['page'])})*" for x in f["recommandations"]]
        if f["vigilance"]:
            L += ["", "**Points de vigilance**", ""] + [f"- ⚠️ {x['texte']} *({refs.ref(x['doc_id'], x['page'])})*" for x in f["vigilance"]]
        L += [""] + _block("fiche-technique", keep)
    if form.synthese:
        L += ["## Synthèse", ""] + [f"{x['texte']} *({refs.ref(x['doc_id'], x['page'])})*\n" for x in form.synthese["paragraphes"]]
        if form.synthese.get("conclusion"):
            L += [f"**Conclusion** : {form.synthese['conclusion']}", ""]
        L += _block("synthese", keep)
    if form.glossaire:
        L += ["## Glossaire", ""]
        for g in form.glossaire:
            if g.get("sourcee", True):
                L.append(f"- **{g['terme']}** : {g['definition']} *({refs.ref(g['doc_id'], g['page'])})*")
            else:
                L.append(f"- **{g['terme']}** : {g['definition']} *(définition proposée, non sourcée : à vérifier)* — "
                         f"dans les sources : « {g.get('extrait', '')} » *({refs.ref(g['doc_id'], g['page'])})*")
        L.append("")
    if form.cas_pratique:
        c = form.cas_pratique
        L += ["## Cas concret (exploitation fictive)", "", c["contexte"], "", "**Questions**", ""]
        L += [f"{i}. {q}" for i, q in enumerate(c["questions"], 1)] + ["", "**Éléments de réponse**", ""]
        L += [f"- {e['texte']} *({refs.ref(e['doc_id'], e['page'])})*" for e in c["elements"]] + [""] + _block("cas-concret", keep)
    if form.podcast:
        L += ["## Podcast", "", f"Script à deux voix dans `podcast_script.md` ({len(form.podcast['repliques'])} répliques). "
              "Audio : à produire avec NotebookLM ou une voix de synthèse.", ""]
    if form.deroule:
        L += ["## Déroulé de séance", ""]
        for x in form.deroule:
            L += [f"**Séquence {x['sequence']} : {x['titre']}**", "", "| Étape | Durée | Consigne |", "|---|---|---|"]
            L += [f"| {e['etape']} | {e['duree_min']} min | {e['consigne']} |" for e in x["etapes"]] + [""]
    # annexes
    L += ["## Annexe A : sources", ""]
    cited = list(refs.order) + [x for x in form.doc_ids if x not in refs.order]
    for i, did in enumerate(cited, 1):
        doc, fi = ctx.store.get(did), ctx.qualifier.get(did)
        if doc is None:
            continue
        label = f"S{i}" if did in refs.order else "non citée"
        facts = [x for x in [fi.get("organisme") if fi else None,
                             f"résultats {fi.get('annee')}" if fi and fi.get("annee") else None,
                             f"publié en {fi.get('annee_publication')}" if fi and fi.get("annee_publication") else None,
                             fi.get("type") if fi else None, doc.kind if doc.kind not in ("pdf", "texte", "page") else None] if x]
        link = doc.title + (" 🔒 personnel" if did in form.personnel_ids else " 🔒 privé" if doc.private else "") \
            if doc.private else f"[{doc.title}]({doc.url})"
        L.append(f"- **{label}** {link}" + (f" — {' · '.join(map(str, facts))}" if facts else "")
                 + (f" — licence {doc.licence}" if doc.licence else ""))
        L += [f"  - ⚠️ {a}" for a in (fi.alertes if fi else [])]
    L.append("")
    removed = list(dict.fromkeys([r for s in form.sequences for r in s.retires] + form.retires))   # sans doublons
    if removed:
        L += ["## Annexe B : retiré par les contrôles", "",
              "_Contenus proposés par le modèle mais non retrouvés dans leur source : absents du support._", ""]
        L += [f"- {r}" for r in removed] + [""]
    if form.remarques:
        L += ["## Annexe C : remarques", ""] + [f"- {r}" for r in form.remarques] + [""]
    return "\n".join(L), "\n".join(Q)


def podcast_md(form) -> str:
    p = form.podcast
    refs = SourceRefs()
    out = [f"# Podcast : {p['titre']}", "", "_Script généré par SourcIA à partir des sources, à relire._", ""]
    for r in p["repliques"]:
        src = f" *({refs.ref(r['doc_id'], r['page'])})*" if r.get("doc_id") else ""
        out.append(f"**{r['voix'].capitalize()}** : {r['texte']}{src}\n")
    return "\n".join(out)


def write(form, ctx, out_root: Path, reprendre: Path | None = None) -> list[Path]:
    """Écrit le dossier. ``reprendre`` : dossier existant → mêmes fichiers, blocs personnels conservés."""
    from sourcia.referentiel.validation import export_rattachements_csv

    keep = {}
    if reprendre:
        out = Path(reprendre)
        old = out / "support_formateur.md"
        if old.exists():
            text = old.read_text(encoding="utf-8")
            keep = {k: v for k, v in personal_blocks(text).items() if v.strip() != PLACEHOLDER}
            (out / "support_formateur.precedent.md").write_text(text, encoding="utf-8")
    else:
        out = out_root / f"formation-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    md, quiz = to_markdown(form, ctx, keep)
    files = {"support_formateur.md": md, "quiz_apprenants.md": quiz, "quiz_moodle.gift.txt": to_gift(form)}
    if form.podcast:
        files["podcast_script.md"] = podcast_md(form)
    paths = []
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
        paths.append(out / name)
    if form.referentiel:
        paths.append(export_rattachements_csv(form, out / "rattachements.csv"))
    if form.echecs_modele:                          # pour comprendre pourquoi un contenu n'a pas été généré
        import json

        (out / "echecs_modele.json").write_text(json.dumps(form.echecs_modele, ensure_ascii=False, indent=1), encoding="utf-8")
        paths.append(out / "echecs_modele.json")
    (out / "formation.json").write_text(form.model_dump_json(indent=1), encoding="utf-8")
    paths.append(out / "formation.json")
    paths.append(form.demande.save(out / "demande.yaml"))
    return paths


def load(folder: Path):
    from sourcia.formation.builder import Formation

    return Formation.model_validate_json((Path(folder) / "formation.json").read_text(encoding="utf-8"))
