"""Étape 4 : SUPPORTS à partir du corpus pédagogique (``corpus.json``) SEULEMENT.

Les supports ne relisent jamais les documents d'origine : chaque information vient d'un point clé (ou d'un
paragraphe de synthèse) déjà contrôlé, et garde sa référence [S1, p. N] (mêmes numéros que le Word du corpus).
L'étape marche donc de la même façon pour un corpus du catalogue et pour un corpus de dossier enseignant.

Supports SANS modèle (justes par construction) :
- ``qcm``          : quizgen.make_question masque une valeur (ou une culture) d'un point vérifié ;
                     ``avec_modele`` : le modèle complète, chaque question contrôlée contre l'extrait cité ;
- ``cartes``       : flashcards (recto à trou, verso réponse + phrase + source) → CSV Anki, HTML à découper ;
- ``presentation`` : .pptx (python-pptx) : titre, une diapo par séquence, illustrations, notes, sources ;
- ``infographie``  : page HTML A4 : chiffres clés (valeurs avec unité), une phrase par séquence, sources.
Supports AVEC modèle (seul endroit où il sert) : ``fiche``, ``glossaire``, ``podcast`` : les fonctions du
FormationBuilder, sur un mini-corpus fait des EXTRAITS EXACTS du corpus (``CorpusPassages``) : leurs contrôles
(checks.py) retirent tout ce qui n'y est pas. Verrou : avec un modèle en ligne et sans l'accord du corpus
(``autoriser_cloud_personnel``), les extraits des documents privés ne sont pas envoyés.

Dossier : ``<dossier du corpus>/supports/supports-<date>/`` (supports.json + les fichiers).
"""
from __future__ import annotations

import csv
import html
import io
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, Field

from sourcia.core.text import normalize, tokenize
from sourcia.formation.corpus import Passage
from sourcia.formation.quizgen import VALUE_RE, make_question
from sourcia.search.bm25 import BM25

SUPPORTS = ("qcm", "cartes", "presentation", "infographie", "fiche", "glossaire", "podcast")
SANS_MODELE = ("qcm", "cartes", "presentation", "infographie")
AVEC_MODELE = ("fiche", "glossaire", "podcast")
LETTERS = "ABCD"
MAX_CHIFFRES = 6
POINTS_PAR_DIAPO = 5
SOURCES_PAR_DIAPO = 12


# ---------------------------------------------------------------------- modèle (supports.json)
class Ref(BaseModel):
    doc_id: str
    page: int
    numero: str = ""                         # S1, S2… (numéros du corpus)
    extrait: str = ""                        # phrase exacte du document
    lien: str | None = None

    def label(self) -> str:
        return f"[{self.numero or 'source'}, p. {self.page}]"


class Question(BaseModel):
    sequence: int
    enonce: str
    choix: list[str]
    bonne_reponse: int
    explication: str                         # la phrase vérifiée dont vient la question
    reference: Ref
    origine: str = "construite"              # construite (sans modèle) · modele (contrôlée par checks.py)


class Carte(BaseModel):
    sequence: int
    recto: str
    verso: str                               # réponse et phrase, en un texte (CSV Anki)
    reference: Ref
    reponse: str = ""                        # l'information masquée au recto (vide : question ouverte)
    phrase: str = ""                         # la phrase vérifiée du corpus


class Chiffre(BaseModel):
    valeur: str                              # « 9,5 t MS/ha » : valeur et unité, telles que dans la phrase
    phrase: str
    sequence: int
    reference: Ref


class Supports(BaseModel):
    version: str = "1"
    cree_le: str = ""
    corpus_titre: str
    corpus_cree_le: str = ""
    dossier_id: str | None = None
    sequences: list[int]                     # numéros des séquences retenues (1 = première)
    supports: list[str]
    qcm: list[Question] = Field(default_factory=list)
    cartes: list[Carte] = Field(default_factory=list)
    chiffres: list[Chiffre] = Field(default_factory=list)
    fiche_technique: dict | None = None
    glossaire: list[dict] = Field(default_factory=list)
    podcast: dict | None = None
    fichiers: list[str] = Field(default_factory=list)
    retires: list[str] = Field(default_factory=list)
    remarques: list[str] = Field(default_factory=list)
    appels_modele: int = 0
    duree_s: float = 0.0


@dataclass
class Item:
    """Une information du corpus : sa séquence, la phrase contrôlée et sa référence."""
    sequence: int
    texte: str
    ref: Ref


# ---------------------------------------------------------------------- lecture du corpus
EMPTY_MESSAGE = ("Ce corpus n'a aucun point clé dans les séquences choisies : le modèle n'a pas pu en écrire. "
                 "Construisez à nouveau le corpus avec un modèle qui répond (Gemini ou Ollama), puis revenez ici.")


def count_points(cp, seqs: list[int]) -> int:
    return sum(len(cp.sequences[i - 1].points) for i in seqs)


def chosen_sequences(cp, sequences: list[int] | None) -> list[int]:
    n = len(cp.sequences)
    seqs = sorted(set(sequences)) if sequences else list(range(1, n + 1))
    bad = [i for i in seqs if not 1 <= i <= n]
    if bad:
        raise ValueError(f"séquence(s) inexistante(s) : {', '.join(map(str, bad))} (le corpus en a {n})")
    return seqs


def numbers(cp) -> dict[str, str]:
    return {b.doc_id: b.numero for b in cp.bibliographie if b.numero}


def make_ref(reference, nums: dict[str, str]) -> Ref:
    return Ref(doc_id=reference.doc_id, page=reference.page, numero=nums.get(reference.doc_id, ""),
               extrait=reference.extrait, lien=reference.lien)


def items_of(cp, seqs: list[int]) -> list[Item]:
    nums = numbers(cp)
    return [Item(i, p.texte, make_ref(p.reference, nums)) for i in seqs for p in cp.sequences[i - 1].points]


def private_docs(cp) -> set[str]:
    """Documents privés du corpus (champ ``prive`` ; pour un ancien corpus : pas d'adresse = privé)."""
    return {b.doc_id for b in cp.bibliographie if b.prive or b.fourni_par_formateur or b.url is None}


class CorpusPassages:
    """Mini-corpus fait de corpus.json, pour les fonctions du FormationBuilder (même interface que
    SelectionCorpus : ``passages``, ``search()``, ``title()``).

    Un passage = l'EXTRAIT EXACT d'un point, suivi du point clé lui-même quand il le reformule. Le point a déjà
    été vérifié contre sa source à l'étape du corpus : une phrase du modèle qui le reprend reste donc soutenue
    par le document (même document, même page). Avec l'extrait seul (une phrase, 300 caractères au plus), les
    répliques d'un podcast qui résument deux informations étaient toutes retirées (vu le 22/11 avec Gemini)."""

    def __init__(self, cp, items: list[Item], exclude: set[str] = frozenset()):
        self.titles = {b.doc_id: b.titre for b in cp.bibliographie}
        self.excluded_private: list = []
        self.passages: list[Passage] = []
        seen = set()
        for it in items:
            text = it.ref.extrait.removeprefix("… ").removesuffix(" …")
            if it.texte and normalize(it.texte) not in normalize(text):
                text = f"{text} {it.texte}".strip()
            if it.ref.doc_id in exclude or not text or (it.ref.doc_id, it.ref.page, text) in seen:
                continue
            seen.add((it.ref.doc_id, it.ref.page, text))
            self.passages.append(Passage(it.ref.doc_id, it.ref.page, text))
        self.bm25 = BM25().fit([str(i) for i in range(len(self.passages))], [p.text for p in self.passages]) \
            if self.passages else None

    def search(self, query: str, k: int = 6, per_doc: int = 2) -> list[Passage]:
        if not self.passages:
            return []
        ranked = [int(i) for i, s in self.bm25.search(query, 50) if s > 0] or list(range(len(self.passages)))
        out, per = [], {}
        for i in ranked:
            p = self.passages[i]
            if per.get(p.doc_id, 0) >= per_doc:
                continue
            per[p.doc_id] = per.get(p.doc_id, 0) + 1
            out.append(Passage(p.doc_id, p.page, p.text, n=len(out) + 1))
            if len(out) >= k:
                break
        return out

    def title(self, doc_id: str) -> str:
        return self.titles.get(doc_id, doc_id)


# ---------------------------------------------------------------------- supports sans modèle
def build_qcm(items: list[Item], all_texts: list[str], topic: frozenset, per_seq: int) -> list[Question]:
    out, seen = [], set()
    count: dict[int, int] = {}
    for it in items:
        if count.get(it.sequence, 0) >= per_seq:
            continue
        for text in (it.texte, it.ref.extrait.removeprefix("… ").removesuffix(" …")):
            q = make_question(text, all_texts, topic) if text else None
            if q and normalize(q["enonce"]) not in seen:
                seen.add(normalize(q["enonce"]))
                out.append(Question(sequence=it.sequence, reference=it.ref, **q))
                count[it.sequence] = count.get(it.sequence, 0) + 1
                break
    return out


PETITS_MOTS = {"de", "des", "du", "d", "la", "le", "les", "l", "un", "une", "à", "au", "aux", "en", "et", "ou",
               "par", "pour", "sur", "dans", "avec", "sans", "que", "qui", "est", "sont", "son", "sa", "ses", "leur",
               "leurs", "ce", "cette", "ces", "se", "ne", "pas", "plus", "très", "entre", "selon", "comme",
               "a", "ont", "été", "être", "doit", "doivent", "peut", "peuvent"}


def sentence_start(text: str) -> str | None:
    """Début d'une phrase à faire compléter (carte sans information précise à masquer).

    On coupe après « : » s'il arrive assez tôt, sinon vers 40 % des mots ; jamais sur un petit mot (« de »,
    « la », « est »…) qui laisserait une suite trop évidente ou incompréhensible. None si la phrase est trop
    courte pour en cacher une partie utile."""
    words = text.split()
    if len(words) < 6:
        return None
    colon = next((k for k, w in enumerate(words) if w == ":" or w.endswith(":")), None)
    cut = colon + 1 if colon is not None and 3 <= colon + 1 <= 0.7 * len(words) else max(3, round(0.4 * len(words)))
    def unfinished(k):                               # petit mot en dernier, ou parenthèse pas refermée
        head = " ".join(words[:k])
        return words[k - 1].lower().strip(",;").split("'")[-1] in PETITS_MOTS | {""} or head.count("(") > head.count(")")

    while cut < len(words) - 2 and unfinished(cut):
        cut += 1                                     # « … permettent de » → « … permettent de plusieurs »
    start = " ".join(words[:cut]).rstrip(",;")
    return start if cut < len(words) - 1 else None


def build_cartes(cp, items: list[Item], all_texts: list[str], topic: frozenset) -> list[Carte]:
    out = []
    rank: dict[int, int] = {}
    for it in items:
        rank[it.sequence] = rank.get(it.sequence, 0) + 1
        q = make_question(it.texte, all_texts, topic)
        start = None if q else sentence_start(it.texte)
        if q:
            answer = q["choix"][q["bonne_reponse"]]
            recto, verso, reponse = q["enonce"], f"{answer}. {it.texte}", answer
        elif start:                                  # rien de précis à masquer : la fin de la phrase à retrouver
            recto, verso, reponse = f"Complétez la phrase : « {start}… »", it.texte, ""
        else:                                        # phrase très courte : question ouverte sur la séquence
            titre = cp.sequences[it.sequence - 1].titre
            recto, verso, reponse = f"« {titre} » : que faut-il retenir ? (point {rank[it.sequence]})", it.texte, ""
        out.append(Carte(sequence=it.sequence, recto=recto, verso=verso, reference=it.ref, reponse=reponse,
                         phrase=it.texte))
    return out


def build_chiffres(items: list[Item]) -> list[Chiffre]:
    out, seen = [], set()
    for it in items:
        for m in VALUE_RE.finditer(it.texte):
            value = f"{m.group(1)} {' '.join(m.group(2).split())}"
            if value in seen:
                continue
            seen.add(value)
            out.append(Chiffre(valeur=value, phrase=it.texte, sequence=it.sequence, reference=it.ref))
            if len(out) >= MAX_CHIFFRES:
                return out
    return out


# ---------------------------------------------------------------------- supports avec modèle
def _ref_of(doc_id: str, page: int, items: list[Item], nums: dict[str, str]) -> Ref:
    for it in items:
        if it.ref.doc_id == doc_id and it.ref.page == page:
            return it.ref
    return Ref(doc_id=doc_id, page=page or 0, numero=nums.get(doc_id, ""))


def model_questions(b, cp, items: list[Item], seqs: list[int], exclude: set[str], per_seq: int,
                    have: list[Question], removed: list[str]) -> list[Question]:
    """Questions du modèle pour compléter : le chemin contrôlé de FormationBuilder.sequence (checks.py)."""
    from sourcia.formation.builder import SequenceResult

    d = cp.demande.model_copy(update={"sorties": ["quiz"]})
    nums, out = numbers(cp), []
    known = {normalize(q.enonce) for q in have}
    for i in seqs:
        missing = per_seq - sum(q.sequence == i for q in have)
        seq_items = [it for it in items if it.sequence == i]
        corpus = CorpusPassages(cp, seq_items, exclude)
        if missing <= 0 or not corpus.passages:
            continue
        b.use_corpus(corpus, d)
        s = cp.sequences[i - 1]
        res = b.sequence(corpus, SequenceResult(titre=s.titre, objectif=s.objectif, duree_min=s.duree_min,
                                                mots_cles=s.mots_cles), d, missing)
        for qi in res.quiz:
            if normalize(qi.enonce) in known:
                continue
            known.add(normalize(qi.enonce))
            out.append(Question(sequence=i, enonce=qi.enonce, choix=qi.choix, bonne_reponse=qi.bonne_reponse,
                                explication=qi.explication, reference=_ref_of(qi.doc_id, qi.page, items, nums),
                                origine="modele"))
        removed.extend(f"séquence {i} : {r}" for r in res.retires)
    return out


# ---------------------------------------------------------------------- construction
def build_supports(cp, sequences: list[int] | None = None, supports: list[str] | tuple = SANS_MODELE, ctx=None,
                   log=lambda *a: None, avec_modele: bool = False, qcm_par_sequence: int = 4) -> Supports:
    """Calcule les supports demandés (données contrôlées) ; ``write_supports`` écrit les fichiers."""
    t0 = time.perf_counter()
    unknown = [s for s in supports if s not in SUPPORTS]
    if unknown:
        raise ValueError(f"support(s) inconnu(s) : {', '.join(unknown)} (possibles : {', '.join(SUPPORTS)})")
    seqs = chosen_sequences(cp, sequences)
    sup = Supports(cree_le=datetime.now().isoformat(timespec="seconds"), corpus_titre=cp.titre,
                   corpus_cree_le=cp.cree_le, dossier_id=getattr(cp, "dossier_id", None), sequences=seqs,
                   supports=list(dict.fromkeys(supports)))
    items = items_of(cp, seqs)
    all_texts = [p.texte for s in cp.sequences for p in s.points] + \
        [p.reference.extrait for s in cp.sequences for p in s.points if p.reference.extrait]
    topic = frozenset(tokenize(cp.demande.sujet))
    if not items:                                    # des supports vides ne servent à personne : on le dit
        raise ValueError(EMPTY_MESSAGE)

    if "qcm" in supports:
        log("  QCM")
        sup.qcm = build_qcm(items, all_texts, topic, qcm_par_sequence)
    if "cartes" in supports:
        log("  cartes")
        sup.cartes = build_cartes(cp, items, all_texts, topic)
    if "infographie" in supports:
        sup.chiffres = build_chiffres(items)
        if not sup.chiffres:
            sup.remarques.append("infographie : aucun chiffre avec unité dans les points choisis")

    needs_model = [s for s in supports if s in AVEC_MODELE] + (["qcm"] if avec_modele and "qcm" in supports else [])
    if needs_model:
        if ctx is None:
            sup.remarques.append(f"{', '.join(needs_model)} : demande(nt) un modèle, non produit(s) ici")
        else:
            _model_supports(sup, cp, items, seqs, ctx, log, avec_modele, qcm_par_sequence)
    if "qcm" in supports and not sup.qcm:
        sup.remarques.append("QCM : aucune question possible (pas de valeur ni de culture à demander dans les points)")
    sup.duree_s = round(time.perf_counter() - t0, 1)
    return sup


def _model_supports(sup, cp, items, seqs, ctx, log, avec_modele, per_seq) -> None:
    from sourcia.formation.builder import FormationBuilder

    b = FormationBuilder(ctx)
    cloud = ctx.settings.llm.provider == "litellm"
    exclude = set()
    if cloud and not cp.demande.autoriser_cloud_personnel:
        exclude = private_docs(cp) & {it.ref.doc_id for it in items}
        if exclude:
            sup.remarques.append(f"{len(exclude)} document(s) privé(s) non envoyé(s) au modèle en ligne "
                                 "(pas d'accord dans la demande du corpus)")
    if avec_modele and "qcm" in sup.supports:
        log("  QCM complétés par le modèle")
        sup.qcm += model_questions(b, cp, items, seqs, exclude, per_seq, sup.qcm, sup.retires)
    # fiche, glossaire, podcast : sur tout ce que les séquences choisies contiennent, plus la synthèse si on les
    # prend toutes (elle porte sur l'ensemble du corpus)
    pool = list(items)
    if cp.synthese and len(seqs) == len(cp.sequences):
        nums = numbers(cp)
        pool += [Item(0, x.texte, make_ref(x.reference, nums)) for x in cp.synthese.paragraphes]
    corpus = CorpusPassages(cp, pool, exclude)
    if not corpus.passages:
        sup.remarques.append("aucun extrait utilisable pour les supports avec modèle")
    else:
        b.use_corpus(corpus, cp.demande)
        nums = numbers(cp)
        for name, fn in (("fiche", b.fiche_technique), ("glossaire", b.glossaire), ("podcast", b.podcast)):
            if name not in sup.supports:
                continue
            log(f"  {name}")
            val = fn(corpus, cp.demande, sup.retires)
            if not val:
                sup.remarques.append(f"{name} : non produit(e) (modèle indisponible, ou tout a été retiré par les "
                                     "contrôles : voir « retires »)")
            if name == "fiche":
                sup.fiche_technique = _with_refs(val, ("recommandations", "vigilance"), pool, nums) if val else None
            elif name == "glossaire":
                sup.glossaire = [x | {"ref": _ref_of(x["doc_id"], x["page"], pool, nums).label()} for x in val or []]
            else:
                if val:
                    for r in val["repliques"]:
                        r["ref"] = _ref_of(r["doc_id"], r["page"], pool, nums).label() if r.get("doc_id") else ""
                    val["repliques"], orphans = answered(val["repliques"])
                    sup.retires += [f"question de l'animateur sans réponse (réponse retirée) : « {q[:90]} »"
                                    for q in orphans]
                sup.podcast = val
    sup.appels_modele = b.calls


def answered(repliques: list[dict]) -> tuple[list[dict], list[str]]:
    """Retire les questions de l'animateur restées sans réponse (la réponse de l'expert a été retirée par les
    contrôles) : sinon deux questions se suivent dans le script. Renvoie (répliques gardées, questions retirées)."""
    kept, orphans = [], []
    for k, r in enumerate(repliques):
        nxt = repliques[k + 1] if k + 1 < len(repliques) else None
        if r["voix"] == "animateur" and (nxt is None or nxt["voix"] != "expert"):
            orphans.append(r["texte"])
            continue
        kept.append(r)
    return kept, orphans


def _with_refs(val: dict, keys, pool, nums) -> dict:
    out = dict(val)
    for k in keys:
        out[k] = [x | {"ref": _ref_of(x["doc_id"], x["page"], pool, nums).label()} for x in val.get(k, [])]
    return out


# ---------------------------------------------------------------------- fichiers
def new_supports_folder(corpus_dir: Path) -> Path:
    base = Path(corpus_dir) / "supports" / f"supports-{datetime.now():%Y%m%d-%H%M%S}"
    out, k = base, 1
    while out.exists():
        k += 1
        out = base.with_name(f"{base.name}-{k}")
    out.mkdir(parents=True)
    return out


def write_supports(sup: Supports, cp, corpus_dir: Path, folder: Path | None = None) -> list[Path]:
    """Écrit ``supports-<date>/`` (dans le dossier du corpus) : supports.json et un fichier par support."""
    from sourcia.formation.export_word import word_safe

    cp = type(cp).model_validate(word_safe(cp.model_dump()))          # sans caractères interdits (pptx, xml)
    folder = Path(folder) if folder is not None else new_supports_folder(corpus_dir)
    folder.mkdir(parents=True, exist_ok=True)
    files: dict[str, str | bytes] = {}
    if "qcm" in sup.supports and sup.qcm:
        files["qcm_apprenants.md"] = qcm_markdown(sup, cp, corrige=False)
        files["qcm_corrige.md"] = qcm_markdown(sup, cp, corrige=True)
        files["qcm_moodle.gift.txt"] = qcm_gift(sup, cp)
    if "cartes" in sup.supports and sup.cartes:
        files["cartes_anki.csv"] = cartes_csv(sup)
        files["cartes.html"] = cartes_html(sup, cp)
    if "infographie" in sup.supports:
        files["infographie.html"] = infographie_html(sup, cp)
    if sup.fiche_technique:
        files["fiche_technique.md"] = fiche_markdown(sup.fiche_technique)
    if sup.glossaire:
        files["glossaire.md"] = glossaire_markdown(sup.glossaire, cp)
    if sup.podcast:
        files["podcast_script.md"] = podcast_markdown(sup.podcast)
    paths = []
    for name, content in files.items():
        p = folder / name
        p.write_bytes(content) if isinstance(content, bytes) else p.write_text(content, encoding="utf-8")
        paths.append(p)
    if "presentation" in sup.supports:
        try:
            paths.append(presentation_pptx(sup, cp, Path(corpus_dir), folder / "presentation.pptx"))
        except ImportError:
            sup.remarques.append("présentation non produite : python-pptx manque (pip install -e \".[pptx]\")")
    sup.fichiers = [p.name for p in paths]
    (folder / "supports.json").write_text(sup.model_dump_json(indent=1), encoding="utf-8")
    return [folder / "supports.json"] + paths


def load_supports(folder: Path) -> Supports:
    return Supports.model_validate_json((Path(folder) / "supports.json").read_text(encoding="utf-8"))


def _seq_title(cp, i: int) -> str:
    return f"Séquence {i} : {cp.sequences[i - 1].titre}"


def cited_sources(cp, refs) -> list:
    used = {r.doc_id for r in refs}
    return [b for b in cp.bibliographie if b.numero and b.doc_id in used]


def source_line(b) -> str:
    lead = " ".join(x for x in [b.organisme, f"({b.annee})" if b.annee else None] if x)
    where = "document fourni par le formateur" if b.fourni_par_formateur else \
        (b.url if b.url and b.url.startswith("http") else "document privé" if b.url is None else "fichier local")
    return f"{b.numero}. " + (f"{lead}. " if lead else "") + f"{b.titre}. {where}"


# --- QCM
def qcm_markdown(sup: Supports, cp, corrige: bool) -> str:
    title = "Corrigé du QCM" if corrige else "QCM"
    out = [f"# {title} : {cp.titre}", "",
           "_Questions construites à partir des sources citées. À relire avant usage._" if corrige else
           "_Une seule bonne réponse par question._", ""]
    n = 0
    for i in sup.sequences:
        qs = [q for q in sup.qcm if q.sequence == i]
        if not qs:
            continue
        out += [f"## {_seq_title(cp, i)}", ""]
        for q in qs:
            n += 1
            out.append(f"**{n}. {q.enonce}**")
            out += [f"- {LETTERS[j]}. {c}" for j, c in enumerate(q.choix)]
            if corrige:
                out.append(f"\n> Réponse : **{LETTERS[q.bonne_reponse]}**. {q.explication} {q.reference.label()}"
                           + (" _(question proposée par le modèle, contrôlée)_" if q.origine == "modele" else ""))
            out.append("")
    if corrige:
        out += ["## Sources", ""] + [f"- {source_line(b)}" for b in cited_sources(cp, [q.reference for q in sup.qcm])]
    return "\n".join(out) + "\n"


def qcm_gift(sup: Supports, cp) -> str:
    from sourcia.formation.render import to_gift

    seqs = [SimpleNamespace(titre=_seq_title(cp, i), quiz=[
        SimpleNamespace(enonce=q.enonce, choix=q.choix, bonne_reponse=q.bonne_reponse,
                        explication=f"{q.explication} {q.reference.label()}")
        for q in sup.qcm if q.sequence == i]) for i in sup.sequences]
    return to_gift(SimpleNamespace(titre=cp.titre, sequences=[s for s in seqs if s.quiz]))


# --- cartes
def cartes_csv(sup: Supports) -> str:
    """CSV pour Anki : 3 colonnes (recto ; verso ; source). Les lignes « # » sont les réglages d'import d'Anki."""
    buf = io.StringIO()
    buf.write("#separator:Semicolon\n#html:false\n#columns:Recto;Verso;Source\n")
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    for c in sup.cartes:
        w.writerow([c.recto, c.verso, c.reference.label()])
    return buf.getvalue()


FONTS_DIR = Path(__file__).resolve().parents[1] / "api" / "static" / "fonts"
PLANTES = {   # les pousses de la charte (mêmes dessins que l'interface), en SVG
    "pousse": '<svg viewBox="0 0 52 52" aria-hidden="true"><ellipse cx="26" cy="43" rx="16" ry="5" fill="#b9a98a"/><path d="M26 42V25" stroke="#2e7d4b" stroke-width="3" stroke-linecap="round"/><path d="M26 31c-8 0-11-6-11-10 7 0 11 4 11 10z" fill="#4e9b63"/><path d="M26 28c7 0 11-6 11-10-7 0-11 4-11 10z" fill="#2e7d4b"/></svg>',
    "epi": '<svg viewBox="0 0 52 52" aria-hidden="true"><ellipse cx="26" cy="46" rx="16" ry="5" fill="#b9a98a"/><path d="M26 45V17" stroke="#b88a1c" stroke-width="3" stroke-linecap="round"/><g fill="#e0a82e"><ellipse cx="21.5" cy="14" rx="3.3" ry="5.4" transform="rotate(-22 21.5 14)"/><ellipse cx="30.5" cy="14" rx="3.3" ry="5.4" transform="rotate(22 30.5 14)"/><ellipse cx="21" cy="23" rx="3.3" ry="5.4" transform="rotate(-22 21 23)"/><ellipse cx="31" cy="23" rx="3.3" ry="5.4" transform="rotate(22 31 23)"/><ellipse cx="26" cy="7" rx="3.1" ry="5.4"/></g></svg>',
}


def embedded_fonts() -> str:
    """Les polices de la charte DANS le fichier (base64) : la page reste belle hors ligne et imprimée."""
    import base64

    faces = [("Fredoka", "fredoka.woff2", "500 600"),
             ("Atkinson Hyperlegible", "atkinson-hyperlegible-normal.woff2", "400"),
             ("Atkinson Hyperlegible", "atkinson-hyperlegible-gras.woff2", "700")]
    css = []
    for family, name, weight in faces:
        f = FONTS_DIR / name
        if f.is_file():
            data = base64.b64encode(f.read_bytes()).decode()
            css.append(f'@font-face{{font-family:"{family}";font-weight:{weight};'
                       f'src:url(data:font/woff2;base64,{data}) format("woff2")}}')
    return "".join(css)


CHARTE_CSS = """:root{--craie:#f7f8f3;--blanc:#fff;--terre:#2a231c;--terre-douce:#5e5145;--trait:#dcd8c9;--sillon:#b9a98a;
--bleuet:#2f4fb8;--colza:#f5c518;--colza-pale:#fdf3c4;--prairie:#2e7d4b;--prairie-pale:#e3f1e6;--prairie-texte:#1f5a35;
--ble:#efe3be;--ble-texte:#6b5418}
*{box-sizing:border-box}body{margin:0;background:var(--craie);color:var(--terre);
font:11pt/1.5 "Atkinson Hyperlegible","Segoe UI",system-ui,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
h1,h2,h3{font-family:"Fredoka","Trebuchet MS",system-ui,sans-serif;font-weight:600;line-height:1.15;margin:0}
.ref{display:inline-block;font-size:8.5pt;font-weight:700;color:var(--ble-texte);background:var(--ble);
padding:0 7px 0 11px;white-space:nowrap;clip-path:polygon(7px 0,100% 0,100% 100%,7px 100%,0 50%)}
.pied{font-size:8pt;color:var(--terre-douce);border-top:2px dotted var(--trait);margin-top:6mm;padding-top:3mm}
.pied ul{margin:2mm 0;padding-left:4mm}.pied li{margin-bottom:1mm}"""


def _page(title: str, body: str, extra_css: str) -> str:
    e = html.escape
    return (f'<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>{e(title)}</title>'
            f"<style>{embedded_fonts()}\n{CHARTE_CSS}\n{extra_css}</style></head><body>{body}</body></html>\n")


def _sources_html(cp, refs) -> str:
    e = html.escape
    items = "".join(f"<li>{e(source_line(b))}</li>" for b in cited_sources(cp, refs))
    return f"<ul>{items}</ul>" if items else ""


def _chip(ref) -> str:
    return f'<span class="ref">{html.escape((ref.numero or "Source") + ", page " + str(ref.page))}</span>'


def cartes_html(sup: Supports, cp) -> str:
    """Cartes à découper comme des sachets de graines : question à gauche, réponse et source à droite, on plie."""
    e = html.escape
    cards = "".join(
        f'<article class="carte"><div class="recto"><p class="seq">{PLANTES["pousse"]}Séquence {c.sequence}</p>'
        f'<p class="q">{e(c.recto)}</p></div><div class="verso">'
        + (f'<p class="rep">Réponse : <strong>{e(c.reponse)}</strong></p>' if c.reponse else "")
        + f'<p class="r">{e(c.phrase or c.verso)}</p>{_chip(c.reference)}'
        "</div></article>" for c in sup.cartes)
    body = (f"<header><h1>Cartes de révision</h1><p>{e(cp.titre)} : découpez sur les pointillés, pliez au milieu. "
            "La question est devant, la réponse et sa source derrière.</p></header>"
            f'<main class="cartes">{cards}</main><footer class="pied"><strong>Sources</strong>'
            f"{_sources_html(cp, [c.reference for c in sup.cartes])}"
            "Cartes préparées avec SourcIA à partir de sources vérifiées. À relire avant de les distribuer.</footer>")
    css = """@page{size:A4;margin:12mm}body{padding:8mm;max-width:210mm;margin:auto}
header h1{font-size:22pt}header p{color:var(--terre-douce);margin:2mm 0 6mm}
.cartes{display:grid;gap:5mm}
.carte{display:grid;grid-template-columns:1fr 1fr;min-height:46mm;break-inside:avoid;border:2px dashed var(--sillon);
border-radius:4mm;background:var(--blanc);overflow:hidden}
.recto{padding:4mm 5mm;border-right:2px dashed var(--sillon)}.verso{padding:4mm 5mm;background:var(--prairie-pale)}
.seq{display:flex;align-items:center;gap:2mm;margin:0 0 2mm;font:600 9pt "Fredoka",sans-serif;color:var(--prairie-texte)}
.seq svg{width:7mm;height:7mm}.q{margin:0;font-size:12pt}.r{margin:0 0 2mm;font-size:10pt;color:var(--terre-douce)}
.rep{margin:0 0 2mm;font-size:12pt;color:var(--prairie-texte)}.rep strong{font:600 14pt "Fredoka",sans-serif}
@media print{body{padding:0;background:#fff}}"""
    return _page(f"Cartes : {cp.titre}", body, css)


def infographie_html(sup: Supports, cp) -> str:
    """Page A4 : bandeau titre, chiffres clés en grandes cartes, le parcours des séquences, les sources."""
    e = html.escape
    d = cp.demande
    nums = numbers(cp)
    refs = [c.reference for c in sup.chiffres]
    chiffres = "".join(f'<div class="chiffre"><p class="val">{e(c.valeur)}</p><p class="phrase">{e(c.phrase)}</p>'
                       f"{_chip(c.reference)}</div>" for c in sup.chiffres)
    etapes = []
    for i in sup.sequences:
        seq = cp.sequences[i - 1]
        if not seq.points:
            continue
        r = make_ref(seq.points[0].reference, nums)
        refs.append(r)
        etapes.append(f'<li><span class="pot">{i}</span><div><h3>{e(seq.titre)}</h3>'
                      f"<p>{e(seq.points[0].texte)} {_chip(r)}</p></div></li>")
    bloc_chiffres = (f'<h2>Les chiffres clés</h2><div class="chiffres">{chiffres}</div>' if chiffres else
                     '<p class="sans">Pas de chiffre dans ces séquences : l’infographie présente l’essentiel du cours.</p>')
    diplome = f'<p class="dip">{e(cp.referentiel["nom"])}</p>' if cp.referentiel else ""
    body = (f'<header><div class="plante">{PLANTES["epi"]}</div><div><h1>{e(cp.titre)}</h1>'
            f"<p>{e(d.public_description())}</p>{diplome}</div></header>"
            f"<main>{bloc_chiffres}<h2>L’essentiel, séquence par séquence</h2>"
            f'<ol class="parcours">{"".join(etapes)}</ol></main>'
            '<footer class="pied"><strong>Sources</strong> : chaque information renvoie à son document et à sa page.'
            f"{_sources_html(cp, refs)}Infographie préparée avec SourcIA. À relire avant diffusion. "
            "Pour un PDF : imprimer cette page depuis le navigateur, au format A4.</footer>")
    css = """@page{size:A4;margin:10mm}body{width:190mm;margin:8mm auto;padding:0}
header{display:flex;gap:6mm;align-items:center;background:var(--blanc);border:2px solid var(--trait);border-radius:6mm;
padding:6mm 7mm}header .plante svg{width:22mm;height:22mm}header h1{font-size:24pt}
header p{margin:1mm 0 0;color:var(--terre-douce)}header .dip{display:inline-block;margin-top:2mm;padding:1mm 4mm;
border-radius:3mm;background:var(--colza-pale);color:#6a5300;font-weight:700;font-size:9.5pt}
h2{font-size:15pt;margin:7mm 0 3mm}
.chiffres{display:grid;grid-template-columns:repeat(3,1fr);gap:4mm}
.chiffre{background:var(--blanc);border:2px solid var(--trait);border-top:5px solid var(--colza);border-radius:4mm;padding:3mm 4mm}
.val{margin:0;font:600 21pt/1.1 "Fredoka",sans-serif;color:var(--bleuet)}.phrase{margin:1.5mm 0 2mm;font-size:9.5pt}
.sans{margin:6mm 0 0;padding:3mm 4mm;border:2px dashed var(--sillon);border-radius:4mm;color:var(--terre-douce)}
.parcours{list-style:none;margin:0;padding:0;position:relative}
.parcours::before{content:"";position:absolute;left:5.5mm;top:4mm;bottom:4mm;border-left:3px dashed var(--sillon)}
.parcours li{position:relative;display:flex;gap:4mm;margin-bottom:4mm;break-inside:avoid}
.pot{flex:none;width:11mm;height:11mm;border-radius:50%;display:grid;place-items:center;background:var(--colza-pale);
border:2px solid var(--colza);font:600 12pt "Fredoka",sans-serif;z-index:1}
.parcours h3{font-size:12pt;margin:1mm 0}.parcours p{margin:0;font-size:10pt}
@media print{body{margin:0;background:#fff}}
@media screen and (max-width:800px){body{width:auto;margin:4mm}.chiffres{grid-template-columns:1fr}}"""
    return _page(f"Infographie : {cp.titre}", body, css)


# --- fiche, glossaire, podcast
def fiche_markdown(f: dict) -> str:
    out = [f"# Fiche technique : {f['titre']}", "", "_Chaque recommandation renvoie à sa source. À relire._", "",
           "## Recommandations", ""] + [f"- {x['texte']} {x['ref']}" for x in f["recommandations"]]
    if f.get("vigilance"):
        out += ["", "## Points de vigilance", ""] + [f"- {x['texte']} {x['ref']}" for x in f["vigilance"]]
    return "\n".join(out) + "\n"


def glossaire_markdown(g: list[dict], cp) -> str:
    out = [f"# Glossaire : {cp.titre}", ""]
    for x in g:
        flag = "" if x.get("sourcee", True) else " _(définition proposée, à vérifier ; le terme figure dans la source)_"
        out.append(f"- **{x['terme']}** : {x['definition']} {x['ref']}{flag}")
    return "\n".join(out) + "\n"


def podcast_markdown(p: dict) -> str:
    out = [f"# Podcast : {p['titre']}", "", "_Script à deux voix, l'expert cite ses sources. À relire._", ""]
    out += [f"**{r['voix'].capitalize()}** : {r['texte']}" + (f" {r['ref']}" if r.get("ref") else "") + "\n"
            for r in p["repliques"]]
    return "\n".join(out)


# --- présentation : formation/presentation.py (modèle de diapositives « Du champ à la classe »)
from sourcia.formation.presentation import expected_slides, presentation_pptx  # noqa: E402,F401
