"""M7 Formation : construire le support à partir de la sélection, piloté par la DEMANDE STRUCTURÉE (M0).

Déroulé :
1. contenu personnel (notes, fichiers) ajouté au corpus, en privé ;
2. PLAN : séquences (objectif = verbe d'action). Formation diplômante : chaque séquence est rattachée à une
   capacité du référentiel (M8) ; les capacités non couvertes sont ajoutées ; repli sans modèle :
   une séquence par capacité (diplômante) ou par thème des fiches (non diplômante) ;
3. par séquence : passages utiles → POINTS CLÉS cités et QCM contrôlés ;
4. sorties demandées : fiche technique, synthèse, glossaire, cas concret, script de podcast, déroulé oral ;
5. contrôles dans le code (checks.py) : non soutenu par sa source → retiré et listé ;
6. contrôle du NIVEAU (verbes des objectifs, lisibilité) et du rattachement au référentiel.
"""
from __future__ import annotations

import hashlib
import time
from collections import Counter

from pydantic import BaseModel, Field

from sourcia.core.demande import Demande
from sourcia.core.text import normalize
from sourcia.formation import checks
from sourcia.formation.corpus import Passage, SelectionCorpus, prompt_block
from sourcia.formation.schemas import (CasPratique, FicheSequence, FicheTechnique, Glossaire, PlanFormation, Quiz,
                                       ScriptPodcast, Sequence, Synthese)
from sourcia.llm.base import Message, StructuredOutputError, chat_structured
from sourcia.observability.tracing import span

import re

CODE_RE = re.compile(r"\bC[PG]?\d{1,2}(?:\.\d{1,2})?\b")

SYSTEM = ("Tu es un ingénieur pédagogique en agronomie. Tu prépares un support de formation À PARTIR "
          "UNIQUEMENT des passages numérotés fournis. Chaque information doit citer le numéro [n] du passage "
          "qui la contient. N'ajoute rien qui ne soit pas dans les passages. Réponds en français, en JSON.")


class Item(BaseModel):
    texte: str
    doc_id: str
    page: int


class QuizItem(BaseModel):
    enonce: str
    choix: list[str]
    bonne_reponse: int
    explication: str
    doc_id: str
    page: int


class SequenceResult(BaseModel):
    titre: str
    objectif: str
    duree_min: int
    mots_cles: list[str] = Field(default_factory=list)
    capacite: str | None = None
    capacite_libelle: str | None = None
    capacite_statut: str = "aucune"          # propose_ia · ajoute_couverture · repli · deja_valide · valide · refuse · aucune
    points: list[Item] = Field(default_factory=list)
    a_retenir: str = ""
    quiz: list[QuizItem] = Field(default_factory=list)
    remarques: list[str] = Field(default_factory=list)
    retires: list[str] = Field(default_factory=list)


class Formation(BaseModel):
    demande: Demande
    titre: str
    doc_ids: list[str]
    sequences: list[SequenceResult] = Field(default_factory=list)
    referentiel: dict | None = None          # id, nom, version, statut
    couverture: list[dict] = Field(default_factory=list)
    niveau: dict = Field(default_factory=dict)
    fiche_technique: dict | None = None
    synthese: dict | None = None
    glossaire: list[dict] = Field(default_factory=list)
    cas_pratique: dict | None = None
    podcast: dict | None = None
    deroule: list[dict] = Field(default_factory=list)
    retires: list[str] = Field(default_factory=list)
    remarques: list[str] = Field(default_factory=list)
    exclus_prives: list[str] = Field(default_factory=list)
    personnel_ids: list[str] = Field(default_factory=list)
    echecs_modele: list[dict] = Field(default_factory=list)   # réponses invalides du modèle (diagnostic)
    appels_modele: int = 0
    duree_s: float = 0.0


def as_demande(d) -> Demande:
    return d if isinstance(d, Demande) else Demande(sujet=str(d))


class FormationBuilder:
    def __init__(self, ctx, llm=None, threshold: float | None = None):
        self.ctx = ctx
        self.llm = llm if llm is not None else ctx.llm
        # seuil du contrôle : 0,65 pour un petit modèle qui enjolive ; un grand modèle reformule plus (config)
        self.threshold = threshold if threshold is not None else ctx.settings.formation_threshold
        self.calls = 0
        self.seen_points: set[str] = set()
        self.seen_bags: list[tuple[set, str]] = []   # (mots du point, document) : repère les reformulations en double
        self.topic: frozenset = frozenset()
        self.corpus = None
        self.pool: dict = {}
        self.pool_texts: dict = {}
        self.failures: list[dict] = []
        self.seen_answers: set[tuple] = set()      # (bonne réponse, document) : pas deux fois la même question

    def _ctext(self, p) -> str:
        """Texte d'un passage POUR LE CONTRÔLE : précédé du titre du document (la culture citée dans le titre
        compte : « triticale-pois-vesce » p. 2 du document sur les méteils)."""
        return f"{self.corpus.title(p.doc_id)}. {p.text}" if self.corpus else p.text

    # ------------------------------------------------------------------ appels au modèle
    def _ask(self, model_cls, task: str, passages: list[Passage] | None, corpus, d: Demande, max_tokens: int = 900):
        ctx_txt = f"\n\nPassages :\n{prompt_block(passages, corpus)}" if passages else ""
        msgs = [Message("system", SYSTEM),
                Message("user", f"Demandeur : {d.profil_description()}.\nPublic : {d.public_description()}.\n"
                                f"Modalité : {d.modalite}, support {', '.join(d.supports)}.{ctx_txt}\n\nTâche : {task}")]
        try:
            # QCM et glossaire : une seule nouvelle tentative (un repli existe ; chaque essai coûte 2 à 3 min en local)
            retries = 1 if model_cls in (Quiz, Glossaire) else 2
            obj, attempts = chat_structured(self.llm, msgs, model_cls, max_tokens=max_tokens, retries=retries)
        except StructuredOutputError as exc:
            self.calls += len(exc.attempts)
            self.failures.append({"contenu": model_cls.__name__, "tache": task[:300],
                                  "reponses": [a[:3000] for a in exc.attempts]})
            raise
        except Exception as exc:                      # erreur du fournisseur (schéma refusé, quota…) : on la garde
            self.calls += 1
            self.failures.append({"contenu": model_cls.__name__, "tache": task[:300],
                                  "erreur": f"{type(exc).__name__} : {str(exc)[:1500]}"})
            raise
        self.calls += attempts
        return obj

    # ------------------------------------------------------------------ contenu personnel (critère 7)
    def personal_docs(self, d: Demande) -> list[str]:
        from pathlib import Path

        from sourcia.collect.local import scan_folder
        from sourcia.extract.pdf import extract

        ids = []
        paths = [Path(p) for p in d.fichiers_personnels]
        if d.notes_personnelles.strip():
            h = hashlib.sha1(d.notes_personnelles.encode("utf-8")).hexdigest()[:10]
            folder = self.ctx.settings.path("personnel", f"notes-{h}", ".keep").parent
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "notes_personnelles.md").write_text(d.notes_personnelles, encoding="utf-8")
            paths.append(folder)
        for p in paths:
            if not p.exists():
                continue
            docs = scan_folder(p if p.is_dir() else p.parent, source="personnel", private=True)
            if p.is_file():
                docs = [x for x in docs if Path(x.local_path).name == p.name]
            for doc in docs:
                if Path(doc.local_path).name == "notes_personnelles.md":
                    doc.title = "Notes personnelles du formateur"
                self.ctx.store.add(doc)
                doc = self.ctx.store.get(doc.id)
                if doc.status == "downloaded":
                    extract(doc, self.ctx.text_dir, self.ctx.settings.extract.max_pages)
                self.ctx.qualifier.qualify(doc)
                ids.append(doc.id)
        if ids:
            self.ctx.store.save()
            self.ctx.qualifier.save()
        return ids

    # ------------------------------------------------------------------ plan (+ référentiel)
    def plan(self, corpus: SelectionCorpus, d: Demande, ref, n_seq: int) -> tuple[PlanFormation, str]:
        lines = []
        for doc in corpus.docs:
            fi = self.ctx.qualifier.get(doc.id)
            themes = ", ".join(fi.themes[:6]) if fi else ""
            lines.append(f"- {doc.title}" + (f" (thèmes : {themes})" if themes else ""))
        caps = ref.leaves(d.capacites) if ref else []
        cap_txt = ""
        if caps:
            cap_txt = ("\nFormation DIPLÔMANTE. Capacités du référentiel visées :\n"
                       + "\n".join(f"- {c.code} : {c.libelle}" for c in caps)
                       + "\nChaque séquence vise UNE capacité : écris son code dans le champ « capacite » (pas dans "
                       "les mots-clés). Toutes les capacités doivent être couvertes. Exemple de séquence : "
                       f'{{"titre": "Implanter un fourrage d\'été", "objectif": "Choisir la date et la densité de semis selon le sol", '
                       f'"duree_min": 45, "mots_cles": ["semis", "densité"], "capacite": "{caps[0].code}"}}')
        task = (f"Propose le plan d'une formation de {d.duree_min} minutes sur : « {d.sujet} », en {max(n_seq, len(caps))} "
                f"séquences au plus. Chaque objectif commence par un verbe d'action adapté au public.{cap_txt}\n"
                "Documents disponibles :\n" + "\n".join(lines[:60]) +
                "\nPour chaque séquence : titre, objectif, durée en minutes, mots-clés pour retrouver les passages.")
        try:
            p = self._ask(PlanFormation, task, None, corpus, d, max_tokens=900)
            p.sequences = p.sequences[: max(n_seq, len(caps))]
            return p, "modele"
        except Exception:
            return self.fallback_plan(corpus, d, caps, n_seq), "repli"

    def fallback_plan(self, corpus: SelectionCorpus, d: Demande, caps, n_seq: int) -> PlanFormation:
        """Sans modèle : une séquence par capacité visée (diplômante), sinon par thème le plus fréquent des fiches."""
        if caps:
            items = [(c.libelle[:80], c.libelle, [d.sujet] + [w for w in c.libelle.split() if len(w) > 5][:4], c.code)
                     for c in caps]
        else:
            cnt = Counter(t for doc in corpus.docs if (fi := self.ctx.qualifier.get(doc.id)) for t in fi.themes)
            themes = [t for t, _ in cnt.most_common(n_seq)] or [d.sujet]
            items = [(t[:1].upper() + t[1:], f"Expliquer les résultats disponibles sur : {t}", [t, d.sujet], None)
                     for t in themes]
        durs = [max(10, d.duree_min // len(items))] * len(items)
        durs[-1] = max(10, d.duree_min - sum(durs[:-1]))
        return PlanFormation(titre=d.sujet, sequences=[
            Sequence(titre=t, objectif=o, duree_min=min(240, du), mots_cles=k, capacite=code)
            for (t, o, k, code), du in zip(items, durs)])

    def attach(self, plan: PlanFormation, d: Demande, ref, how: str) -> tuple[list[SequenceResult], list[dict], list[str]]:
        """Contrôle du rattachement : code existant et visé ; couverture de toutes les capacités visées."""
        from sourcia.referentiel.models import normalize_code
        from sourcia.referentiel.validation import Rattachements

        notes = []
        def objective(s) -> str:
            o = checks.clean(s.objectif or "").strip()               # « … sécheresse [1, 2, 4, 5] » → sans citations
            # le 3B recopie parfois l'exemple de la consigne (« Comparer … », vu le 09/11) : on reprend le titre
            if o.endswith("…") or len(o.split()) < 3 or normalize(o).startswith("choisir la date et la densite de semis"):
                notes.append(f"« {s.titre} » : objectif incomplet (« {o} ») remplacé par le titre de la séquence")
                return s.titre
            return o

        seqs = [SequenceResult(titre=s.titre, objectif=objective(s), duree_min=s.duree_min, mots_cles=s.mots_cles)
                for s in plan.sequences]
        if not ref:
            self._fit_durations(seqs, d.duree_min)
            return seqs, [], notes
        visees = {c.code: c for c in ref.leaves(d.capacites)}
        memo = Rattachements(self.ctx.settings.path("rattachements_valides.jsonl"))
        for s, raw in zip(seqs, plan.sequences):
            code = normalize_code(raw.capacite) if raw.capacite else None
            if not code:                     # le petit modèle met souvent le code dans les mots-clés ou le titre
                code = self._guess_code(raw, visees, {x.capacite for x in seqs if x.capacite})
                if code:
                    notes.append(f"« {s.titre} » : capacité {code} déduite (le modèle ne l'avait pas mise dans le champ prévu)")
            s.mots_cles = [k for k in s.mots_cles if not CODE_RE.fullmatch(k.strip().upper())]
            if code and code not in visees:
                cap = ref.get(code)
                notes.append(f"« {s.titre} » : code {code} " + ("hors des capacités visées" if cap else "inexistant dans le référentiel")
                             + " → rattachement retiré")
                code = None
            if code:
                s.capacite, s.capacite_libelle = code, visees[code].libelle
                s.capacite_statut = "repli" if how == "repli" else "propose_ia"
                if memo.is_validated(ref.id, ref.version, code, s.titre):
                    s.capacite_statut = "deja_valide"
        covered = {s.capacite for s in seqs if s.capacite}
        for code, cap in visees.items():
            if code not in covered:
                notes.append(f"capacité {code} non couverte par le plan → séquence ajoutée")
                seqs.append(SequenceResult(titre=f"{code} : {cap.libelle}"[:90], objectif=cap.libelle, duree_min=30,
                                           mots_cles=[d.sujet] + [w for w in cap.libelle.split() if len(w) > 5][:4],
                                           capacite=code, capacite_libelle=cap.libelle, capacite_statut="ajoute_couverture"))
        self._fit_durations(seqs, d.duree_min)
        couverture = [{"code": c, "libelle": cap.libelle,
                       "sequences": [i + 1 for i, s in enumerate(seqs) if s.capacite == c]} for c, cap in visees.items()]
        return seqs, couverture, notes

    @staticmethod
    def _guess_code(raw, visees: dict, taken: set) -> str | None:
        """Code cité dans les mots-clés, le titre ou l'objectif ; s'il y en a plusieurs (ou aucun), la capacité dont
        le libellé ressemble le plus à la séquence, de préférence encore non couverte."""
        from sourcia.core.text import tokenize

        text = " ".join([raw.titre, raw.objectif] + list(raw.mots_cles))
        found = [c for c in dict.fromkeys(m.upper() for m in CODE_RE.findall(text.upper())) if c in visees]
        cands = found or list(visees)
        words = set(tokenize(f"{raw.titre} {raw.objectif}"))

        def score(code):
            lib = set(tokenize(visees[code].libelle))
            return (len(words & lib) / max(1, len(lib)), code not in taken)
        best = max(cands, key=score, default=None)
        if best is None or (not found and score(best)[0] < 0.5):
            return None
        return best

    @staticmethod
    def _fit_durations(seqs, total: int) -> None:
        """Les durées des séquences (dont celles ajoutées) ramenées à la durée demandée."""
        cur = sum(s.duree_min for s in seqs)
        if not seqs or cur == total:
            return
        for s in seqs:
            s.duree_min = max(10, round(s.duree_min * total / cur))
        seqs[-1].duree_min = max(10, total - sum(s.duree_min for s in seqs[:-1]))

    # ------------------------------------------------------------------ séquence
    def sequence(self, corpus: SelectionCorpus, res: SequenceResult, d: Demande, n_quiz: int) -> SequenceResult:
        query = f"{res.titre} {res.objectif} {' '.join(res.mots_cles)} {d.sujet}"
        passages = corpus.search(query, k=6)
        if not passages:
            res.remarques.append("aucun passage des sources ne couvre cette séquence : à compléter (bloc personnel)")
            return res
        by_n = {p.n: p for p in passages}
        texts = {p.n: self._ctext(p) for p in passages}
        by_n_all = dict(by_n) | self.pool                       # repli : tout le mini-corpus (clés ≥ 1000)
        if d.wants("points_cles") or d.wants("plan"):
            try:
                f = self._ask(FicheSequence, f"Écris les points clés de la séquence « {res.titre} » "
                              f"(objectif : {res.objectif}). Chaque point cite son passage [n].", passages, corpus, d)
                moved = 0
                for pc in f.points_cles:
                    txt = checks.clean(pc.texte)
                    key = normalize(txt)
                    if checks.is_meta(txt):
                        res.retires.append(f"point clé qui décrit le passage au lieu d'en donner l'information : « {txt[:100]} »")
                        continue
                    if key in self.seen_points:
                        res.retires.append(f"point clé en double : « {txt[:80]} »")
                        continue
                    n, _, mv = checks.best_source(txt, texts, pc.source, self.threshold, self.topic, self.pool_texts)
                    bag = checks.meaning_bag(txt)
                    if n is not None and any(doc == by_n_all[n].doc_id and checks.jaccard(bag, b) >= 0.5
                                             for b, doc in self.seen_bags):
                        # vu le 09/11 avec Gemini : « implantation après le 15 mai » reformulé en S1 puis en S2
                        res.retires.append(f"point clé déjà donné (reformulé) : « {txt[:80]} »")
                        continue
                    if n is None:
                        res.retires.append(f"point clé non soutenu par les sources : « {txt[:120]} »")
                        continue
                    moved += mv
                    self.seen_points.add(key)
                    self.seen_bags.append((bag, by_n_all[n].doc_id))
                    res.points.append(Item(texte=txt, doc_id=by_n_all[n].doc_id, page=by_n_all[n].page))
                if moved:
                    res.remarques.append(f"{moved} point(s) clé(s) : numéro de source corrigé (le modèle citait un autre passage)")
                res.a_retenir = self.supported_sentences(f.a_retenir, texts, res.retires, "à retenir")
            except Exception as exc:
                res.remarques.append(f"points clés non générés ({type(exc).__name__})")
        if (d.wants("points_cles") or d.wants("plan")) and not res.points:
            res.remarques.append("aucun point clé retenu par les contrôles pour cette séquence : à compléter (bloc personnel)")
        if d.wants("quiz") and n_quiz > 0:
            try:
                q = self._ask(Quiz, f"Écris {n_quiz + 2} questions QCM sur « {res.titre} ». Une seule bonne réponse "
                              "par question, 3 propositions fausses plausibles et COURTES (10 mots au plus, sans parenthèses). "
                              "L'explication est UNE phrase reprise du passage cité. N'invente aucun chiffre.",
                              passages, corpus, d, max_tokens=1800)
                kept = []
                for qq in q.questions:
                    ok, note = checks.check_question(qq, texts, self.threshold, self.topic, self.pool_texts)
                    if ok and any(checks.same_choices(qq, k) for k in kept):
                        ok, note = False, "doublon d'une autre question"
                    key = (normalize(qq.choix[qq.bonne_reponse]), by_n_all[qq.source].doc_id) if ok else None
                    if ok and key in self.seen_answers:   # vu le 09/11 : « après le 15 mai » en S1 ET en S2
                        ok, note = False, "même question qu'une séquence précédente"
                    if not ok:
                        res.retires.append(f"question retirée ({note}) : « {qq.enonce[:100]} »")
                        continue
                    if note:
                        res.remarques.append(f"« {qq.enonce[:80]} » : {note}")
                    kept.append(qq)
                for qq in kept[:n_quiz]:
                    p = by_n_all[qq.source]
                    self.seen_answers.add((normalize(qq.choix[qq.bonne_reponse]), p.doc_id))
                    res.quiz.append(QuizItem(enonce=qq.enonce, choix=qq.choix, bonne_reponse=qq.bonne_reponse,
                                             explication=qq.explication, doc_id=p.doc_id, page=p.page))
            except Exception as exc:
                res.remarques.append(f"QCM du modèle non généré ({type(exc).__name__} : {str(exc)[:100]})")
            if len(res.quiz) < n_quiz:                     # repli : QCM construits sans modèle, justes par construction
                from sourcia.formation.quizgen import make_question

                added = 0
                for pt in res.points:
                    if len(res.quiz) >= n_quiz:
                        break
                    q = make_question(pt.texte, list(self.pool_texts.values()), self.topic)
                    if q and not any(q["enonce"] == x.enonce for x in res.quiz):
                        res.quiz.append(QuizItem(**q, doc_id=pt.doc_id, page=pt.page))
                        added += 1
                if added:
                    res.remarques.append(f"{added} QCM construit(s) sans modèle à partir des points clés vérifiés "
                                         "(une information masquée ; distracteurs tirés des sources)")
        return res

    def supported_sentences(self, text: str, texts: dict[int, str], removed: list[str], label: str) -> str:
        """Garde seulement les phrases soutenues par au moins un passage (le « à retenir » n'était pas contrôlé)."""
        from sourcia.core.text import split_sentences

        kept = []
        for sent in split_sentences(checks.clean(text)):
            # une phrase de synthèse doit être plus proche de la source qu'un point clé : les énumérations
            # (« influencé par la sécheresse, la canicule, le sol et les essais précédents ») passaient par cumul
            if checks.best_source(sent, texts, None, max(self.threshold, 0.65), self.topic, self.pool_texts)[0] is not None:
                kept.append(sent)
            elif sent.strip():
                removed.append(f"{label} : phrase non soutenue par les sources : « {sent[:110]} »")
        return " ".join(kept)

    # ------------------------------------------------------------------ sorties globales
    def _kept(self, items, by_n, removed: list[str], label: str, factor: float = 1.0) -> list[dict]:
        texts = {n: self._ctext(p) for n, p in by_n.items()}
        all_ = dict(by_n) | self.pool
        out = []
        for it in items:
            txt = checks.clean(it.texte)
            n, _, _ = checks.best_source(txt, texts, it.source, self.threshold * factor, self.topic, self.pool_texts)
            if n is not None and not checks.is_meta(txt):
                out.append({"texte": txt, "doc_id": all_[n].doc_id, "page": all_[n].page})
            else:
                removed.append(f"{label} — non retrouvé dans les sources : « {txt[:100]} »")
        return out

    def fiche_technique(self, corpus, d: Demande, removed: list[str]) -> dict | None:
        passages = corpus.search(d.sujet + " recommandations itinéraire technique conseils dose date", k=7)
        if not passages:
            return None
        by_n = {p.n: p for p in passages}
        try:
            f = self._ask(FicheTechnique, f"Écris une fiche technique sur « {d.sujet} » : recommandations pratiques "
                          "(chiffrées si les passages le permettent) et points de vigilance, chacun cité [n].",
                          passages, corpus, d, max_tokens=1000)
        except Exception as exc:
            removed.append(f"fiche technique non générée ({type(exc).__name__} : {str(exc)[:100]})")
            return None
        reco = self._kept(f.recommandations, by_n, removed, "recommandation")
        vig = self._kept(f.vigilance, by_n, removed, "point de vigilance")
        return {"titre": f.titre, "recommandations": reco, "vigilance": vig} if reco else None

    def synthese(self, corpus, d: Demande, removed: list[str]) -> dict | None:
        passages = corpus.search(d.sujet + " résultats conclusions", k=8, per_doc=1)
        if not passages:
            return None
        by_n = {p.n: p for p in passages}
        try:
            s = self._ask(Synthese, f"Écris une synthèse des résultats sur « {d.sujet} » : un paragraphe court par idée, "
                          "chacun cité [n], en signalant les désaccords entre sources.", passages, corpus, d, max_tokens=1000)
        except Exception as exc:
            removed.append(f"synthèse non générée ({type(exc).__name__} : {str(exc)[:100]})")
            return None
        paras = self._kept(s.paragraphes, by_n, removed, "paragraphe de synthèse")
        texts = {n: self._ctext(p) for n, p in by_n.items()}
        concl = self.supported_sentences(s.conclusion, texts, removed, "conclusion de la synthèse")
        return {"paragraphes": paras, "conclusion": concl} if paras else None

    def glossaire(self, corpus, d: Demande, removed: list[str]) -> list[dict]:
        passages = corpus.search(d.sujet + " définition", k=6)
        if not passages:
            return []
        by_n = {p.n: p for p in passages}
        try:
            g = self._ask(Glossaire, "Écris un glossaire de 3 à 5 termes techniques présents dans les passages ; pour chacun, UNE phrase "
                          "de définition (25 mots au plus), sans répétition, "
                          "avec une définition simple tirée du passage cité.", passages, corpus, d, max_tokens=1200)
        except Exception as exc:
            removed.append(f"glossaire non généré ({type(exc).__name__} : {str(exc)[:100]})")
            return []
        out = []
        # un terme du glossaire doit être DANS les sources ; sa définition, elle, est souvent une connaissance
        # générale (absente des passages) : on la garde alors comme « proposée, à vérifier », avec la phrase
        # des sources où le terme apparaît. Jamais de chiffre ni d'aveu (« non précisé ») non sourcé.
        from sourcia.core.text import split_sentences

        pool = dict(by_n) | self.pool
        for t in g.termes:
            if normalize(t.terme) in {normalize(x["terme"]) for x in out}:
                continue
            definition = checks.clean(t.definition)
            with_term = {n: self._ctext(p) for n, p in pool.items() if normalize(t.terme) in normalize(p.text)}
            if not with_term or not definition:
                removed.append(f"terme retiré (absent des sources) : « {t.terme} »")
                continue
            n, _, _ = checks.best_source(definition, with_term, t.source, self.threshold, self.topic)
            if n is not None:
                out.append({"terme": t.terme, "definition": definition, "doc_id": pool[n].doc_id, "page": pool[n].page,
                            "sourcee": True})
                continue
            if checks.NUM_RE.search(definition) or checks.is_hedged(definition) or \
                    not checks.entities(definition) <= checks.entities(" ".join(with_term.values())):
                removed.append(f"terme retiré (définition avec un chiffre, une culture ou un aveu non sourcés) : « {t.terme} »")
                continue
            k = next(iter(with_term))
            ctx_sent = next((x for x in split_sentences(pool[k].text) if normalize(t.terme) in normalize(x)), "")
            out.append({"terme": t.terme, "definition": definition, "doc_id": pool[k].doc_id, "page": pool[k].page,
                        "sourcee": False, "extrait": ctx_sent[:220]})
        return sorted(out, key=lambda x: normalize(x["terme"]))

    def cas_pratique(self, corpus, d: Demande, removed: list[str]) -> dict | None:
        passages = corpus.search(d.sujet + " résultats rendement coût", k=5)
        if not passages:
            return None
        by_n = {p.n: p for p in passages}
        try:
            region = f" située en {d.region}" if d.region else ""
            c = self._ask(CasPratique, f"Écris un cas concret : une exploitation FICTIVE{region}, décrite en 3 phrases simples "
                          "et cohérentes (production, taille, problème), face au problème de la formation ; 2 à 4 "
                          "questions ; des éléments de réponse tirés des passages cités.",
                          passages, corpus, d, max_tokens=1000)
        except Exception as exc:
            removed.append(f"cas concret non généré ({type(exc).__name__} : {str(exc)[:100]})")
            return None
        elems = self._kept(c.elements_de_reponse, by_n, removed, "élément de réponse")
        if not elems:
            removed.append("cas concret retiré : aucun élément de réponse soutenu")
            return None
        questions = [q for q in (checks.clean(x) for x in c.questions) if q]
        return {"contexte": checks.clean(c.contexte), "questions": questions, "elements": elems}

    def podcast(self, corpus, d: Demande, removed: list[str]) -> dict | None:
        """Script à deux voix. L'expert cite ses sources ; l'animateur pose les questions (pas de chiffre sans source).
        L'audio n'est pas produit ici (NotebookLM le fait ; une voix locale est une évolution possible)."""
        passages = corpus.search(d.sujet, k=6, per_doc=1)
        if not passages:
            return None
        by_n = {p.n: p for p in passages}
        try:
            s = self._ask(ScriptPodcast, f"Écris le script d'un podcast de 5 minutes sur « {d.sujet} » entre un animateur "
                          "(qui pose des questions simples) et un expert (qui répond en citant [n]).", passages, corpus, d,
                          max_tokens=1600)
        except Exception as exc:
            removed.append(f"script de podcast non généré ({type(exc).__name__} : {str(exc)[:100]})")
            return None
        lines = []
        texts = {n: p.text for n, p in by_n.items()}
        for r in s.repliques:
            txt = checks.clean(r.texte)
            needs = r.voix == "expert" or bool(checks.NUM_RE.search(txt))
            n = checks.best_source(txt, texts, r.source, self.threshold, self.topic)[0] if needs else (r.source if r.source in by_n else None)
            if needs and n is None:
                removed.append(f"réplique ({r.voix}) non soutenue : « {txt[:90]} »")
                continue
            p = by_n.get(n) if n else None
            lines.append({"voix": r.voix, "texte": txt, "doc_id": p.doc_id if p else None, "page": p.page if p else None})
        return {"titre": s.titre, "repliques": lines} if sum(l["voix"] == "expert" for l in lines) >= 2 else None

    @staticmethod
    def deroule(seqs: list[SequenceResult], d: Demande) -> list[dict]:
        """Déroulé de séance, sans modèle : accroche, apport, activité, synthèse, adaptés à la modalité."""
        out = []
        dist = d.modalite == "distanciel"
        for i, s in enumerate(seqs, 1):
            t = s.duree_min
            act = ("QCM en ligne (Moodle) puis forum" if dist else "QCM à main levée, puis échange en binômes") if s.quiz \
                else ("étude du cas concret" if d.wants("cas_concret") else "échange à partir d'une situation d'exploitation")
            if "pratique" in d.supports:
                act += " ; mise en situation pratique (parcelle, atelier)"
            steps = [("accroche", round(t * .1), "question ouverte sur la pratique des apprenants" if not dist else "courte vidéo ou question sur le forum"),
                     ("apport", round(t * .4), "présentation des points clés, sources citées" + (" (classe virtuelle)" if dist else "")),
                     ("activité", round(t * .35), act),
                     ("synthèse", t - round(t * .1) - round(t * .4) - round(t * .35), s.a_retenir or "reformulation par les apprenants")]
            out.append({"sequence": i, "titre": s.titre, "etapes": [{"etape": a, "duree_min": m, "consigne": c} for a, m, c in steps]})
        return out

    # ------------------------------------------------------------------ niveau
    @staticmethod
    def level(form: Formation, ref) -> dict:
        from sourcia.referentiel.niveau import check_objectives, check_readability

        d = form.demande
        obj = check_objectives([(s.titre, s.objectif) for s in form.sequences], d.niveau, ref,
                               [s.capacite for s in form.sequences])
        text = " ".join([p.texte for s in form.sequences for p in s.points]
                        + [x["texte"] for x in (form.synthese or {}).get("paragraphes", [])])
        return {"objectifs": obj, "lisibilite": check_readability(text, d.niveau)}

    # ------------------------------------------------------------------ tout
    def build(self, demande, doc_ids: list[str], n_seq: int = 4, n_quiz: int = 4, log=lambda *a: None) -> Formation:
        from sourcia.referentiel.models import ReferentielStore

        d = as_demande(demande)
        t0 = time.perf_counter()
        ref = None
        if d.diplomante and d.diplome:
            ref = ReferentielStore(self.ctx.settings.referentiels_dir).get(d.diplome)
        perso = self.personal_docs(d)
        cloud = self.ctx.settings.llm.provider == "litellm"
        corpus = SelectionCorpus(self.ctx, perso + list(doc_ids), cloud=cloud,
                                 allow_private=tuple(perso) if d.autoriser_cloud_personnel else ())
        from sourcia.core.text import tokenize

        self.corpus = corpus
        self.topic = frozenset(tokenize(d.sujet))
        self.pool = {1000 + i: p for i, p in enumerate(corpus.passages)}
        self.pool_texts = {k: self._ctext(p) for k, p in self.pool.items()}
        with span("formation", demande=d.sujet, docs=len(corpus.docs)):
            log(f"  {len(corpus.docs)} documents ({len(perso)} personnels), {len(corpus.passages)} passages"
                + (f" ({len(corpus.excluded_private)} privés exclus : modèle en ligne)" if corpus.excluded_private else ""))
            plan, how = self.plan(corpus, d, ref, n_seq)
            seqs, couverture, notes = self.attach(plan, d, ref, how)
            log(f"  plan ({'modèle' if how == 'modele' else 'repli sans modèle'}) : {len(seqs)} séquences")
            titre = d.sujet[:1].upper() + d.sujet[1:] if re.match(r"(?i)^s[ée]quence\b", plan.titre.strip()) else plan.titre
            form = Formation(demande=d, titre=titre, doc_ids=[x.id for x in corpus.docs], couverture=couverture,
                             remarques=notes, exclus_prives=[x.title for x in corpus.excluded_private], personnel_ids=perso,
                             referentiel={"id": ref.id, "nom": ref.nom, "version": ref.version, "statut": ref.statut} if ref else None)
            if d.diplomante and not ref:
                form.remarques.append("formation diplômante sans référentiel trouvé : rattachement impossible "
                                      f"(« {d.diplome} » absent de config/referentiels)")
            for i, s in enumerate(seqs, 1):
                log(f"  séquence {i}/{len(seqs)} : {s.titre}")
                form.sequences.append(self.sequence(corpus, s, d, n_quiz))
            for name, fn in [("fiche_technique", self.fiche_technique), ("synthese", self.synthese),
                             ("glossaire", self.glossaire), ("cas_concret", self.cas_pratique), ("podcast", self.podcast)]:
                if d.wants(name):
                    log(f"  {name.replace('_', ' ')}")
                    val = fn(corpus, d, form.retires)
                    if not val and name != "glossaire":
                        form.remarques.append(f"{name.replace('_', ' ')} demandé(e) mais non produit(e) : tout ce que le "
                                              "modèle a proposé a été retiré par les contrôles (annexe B)")
                    setattr(form, {"cas_concret": "cas_pratique"}.get(name, name), val if val is not None else
                            ([] if name == "glossaire" else None))
            if d.wants("deroule_oral") or "oral" in d.supports or d.modalite in ("presentiel", "hybride"):
                form.deroule = self.deroule(form.sequences, d)
            form.niveau = self.level(form, ref)
        form.echecs_modele = self.failures
        form.appels_modele = self.calls
        form.duree_s = round(time.perf_counter() - t0, 1)
        return form
