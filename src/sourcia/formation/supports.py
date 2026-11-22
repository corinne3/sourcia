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
    verso: str
    reference: Ref


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
    SelectionCorpus : ``passages``, ``search()``, ``title()``). Un passage = l'EXTRAIT EXACT d'un point."""

    def __init__(self, cp, items: list[Item], exclude: set[str] = frozenset()):
        self.titles = {b.doc_id: b.titre for b in cp.bibliographie}
        self.excluded_private: list = []
        self.passages: list[Passage] = []
        seen = set()
        for it in items:
            text = it.ref.extrait.removeprefix("… ").removesuffix(" …")
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


def build_cartes(cp, items: list[Item], all_texts: list[str], topic: frozenset) -> list[Carte]:
    out = []
    rank: dict[int, int] = {}
    for it in items:
        rank[it.sequence] = rank.get(it.sequence, 0) + 1
        q = make_question(it.texte, all_texts, topic)
        if q:
            answer = q["choix"][q["bonne_reponse"]]
            recto, verso = q["enonce"], f"{answer}. {it.texte}"
        else:                                        # rien de précis à masquer : question ouverte
            titre = cp.sequences[it.sequence - 1].titre
            recto, verso = f"« {titre} » : que faut-il retenir ? (point {rank[it.sequence]})", it.texte
        out.append(Carte(sequence=it.sequence, recto=recto, verso=verso, reference=it.ref))
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
    if not items:
        sup.remarques.append("aucun point clé dans les séquences choisies : rien à mettre dans les supports")

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
                sup.podcast = val
    sup.appels_modele = b.calls


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


PAGE_CSS = """body{font-family:Calibri,Arial,sans-serif;color:#1d2a20;margin:0}
h1{font-size:20pt;margin:0 0 4mm}.meta{color:#555;font-size:10pt;margin-bottom:6mm}
footer{font-size:8pt;color:#555;border-top:1px solid #ccc;margin-top:6mm;padding-top:2mm}"""


def cartes_html(sup: Supports, cp) -> str:
    e = html.escape
    cards = "\n".join(
        f'<div class="carte"><div class="recto"><span class="seq">Séquence {c.sequence}</span>{e(c.recto)}</div>'
        f'<div class="verso">{e(c.verso)}<span class="src">{e(c.reference.label())}</span></div></div>'
        for c in sup.cartes)
    sources = "".join(f"<li>{e(source_line(b))}</li>" for b in cited_sources(cp, [c.reference for c in sup.cartes]))
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>Cartes : {e(cp.titre)}</title>
<style>{PAGE_CSS}
@page{{size:A4;margin:12mm}}.cartes{{display:grid;grid-template-columns:1fr;gap:5mm}}
.carte{{display:grid;grid-template-columns:1fr 1fr;border:1px dashed #888;break-inside:avoid;min-height:38mm}}
.recto,.verso{{padding:4mm;font-size:11pt}}.verso{{border-left:1px dotted #888;background:#f6f8f4}}
.seq{{display:block;font-size:8pt;color:#6a7d5a;margin-bottom:2mm}}.src{{display:block;font-size:8pt;color:#555;margin-top:2mm}}
</style></head><body><h1>Cartes : {e(cp.titre)}</h1>
<p class="meta">Découpez sur les pointillés, pliez au milieu : question d'un côté, réponse et source de l'autre.</p>
<div class="cartes">{cards}</div><footer><strong>Sources</strong><ul>{sources}</ul></footer></body></html>
"""


# --- infographie
def infographie_html(sup: Supports, cp) -> str:
    """Page A4 autonome : chiffres clés, une phrase par séquence (son premier point), sources."""
    e = html.escape
    d = cp.demande
    refs = [c.reference for c in sup.chiffres]
    essentiel = []
    for i in sup.sequences:
        pts = cp.sequences[i - 1].points
        if pts:
            nums = numbers(cp)
            r = make_ref(pts[0].reference, nums)
            refs.append(r)
            essentiel.append(f"<li><strong>{e(cp.sequences[i - 1].titre)}</strong> : {e(pts[0].texte)} "
                             f"<span class='src'>{e(r.label())}</span></li>")
    chiffres = "".join(f"<div class='chiffre'><div class='val'>{e(c.valeur)}</div><div class='phrase'>"
                       f"{e(c.phrase)}</div><div class='src'>{e(c.reference.label())}</div></div>"
                       for c in sup.chiffres)
    sources = "".join(f"<li>{e(source_line(b))}</li>" for b in cited_sources(cp, refs))
    public = e(d.public_description())
    return f"""<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8"><title>Infographie : {e(cp.titre)}</title>
<style>{PAGE_CSS}
@page{{size:A4;margin:12mm}}body{{width:186mm}}header{{background:#2f5d3a;color:#fff;padding:6mm;border-radius:3mm}}
header h1{{color:#fff}}header .meta{{color:#e3eedd;margin:0}}h2{{color:#2f5d3a;font-size:14pt;margin:6mm 0 3mm}}
.chiffres{{display:grid;grid-template-columns:repeat(3,1fr);gap:4mm}}
.chiffre{{border:2px solid #b9cfa8;border-radius:3mm;padding:3mm}}.val{{font-size:20pt;font-weight:bold;color:#2f5d3a}}
.phrase{{font-size:9pt;margin-top:1mm}}.src{{font-size:8pt;color:#555}}ul.essentiel li{{margin-bottom:2mm;font-size:10.5pt}}
@media print{{body{{width:auto}}}}
</style></head><body><header><h1>{e(cp.titre)}</h1><p class="meta">{public}</p></header>
<h2>Chiffres clés</h2><div class="chiffres">{chiffres or "<p>Aucun chiffre dans les points choisis.</p>"}</div>
<h2>L'essentiel</h2><ul class="essentiel">{"".join(essentiel)}</ul>
<footer><strong>Sources</strong> (chaque information renvoie à son document et à sa page)<ul>{sources}</ul>
Infographie générée par SourcIA à partir du corpus pédagogique. À relire avant diffusion. Pour un PDF :
imprimer la page depuis le navigateur (format A4).</footer></body></html>
"""


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


# --- présentation
def presentation_pptx(sup: Supports, cp, corpus_dir: Path, path: Path) -> Path:
    """Diapos : titre ; par séquence, objectif + points, puis ses illustrations ; illustrations sans séquence
    (si toutes les séquences sont prises) ; sources. Références complètes dans les notes de l'orateur."""
    from pptx import Presentation
    from pptx.enum.text import MSO_AUTO_SIZE
    from pptx.util import Inches, Pt

    from sourcia.formation.illustrations import caption_label

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    title_l, content_l, only_l = prs.slide_layouts[0], prs.slide_layouts[1], prs.slide_layouts[5]
    d = cp.demande

    def notes(slide, lines):
        slide.notes_slide.notes_text_frame.text = "\n".join(lines)

    def place(slide, ph, left, top, width, height):
        # le modèle par défaut de python-pptx est en 4:3 : on replace chaque zone pour le 16:9
        ph.left, ph.top, ph.width, ph.height = left, top, width, height

    def style(tf, pt, bold=False, italic=False):
        """Taille fixe : sans ça, la réduction automatique de PowerPoint rendait les points minuscules."""
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.word_wrap = True
        for para in tf.paragraphs:
            for run in para.runs:
                run.font.size, run.font.bold, run.font.italic = Pt(pt), bold or None, italic or None

    def title(slide, text, pt=32):
        slide.shapes.title.text = text
        place(slide, slide.shapes.title, Inches(0.6), Inches(0.3), Inches(12.1), Inches(1.0))
        style(slide.shapes.title.text_frame, pt)

    s = prs.slides.add_slide(title_l)
    s.shapes.title.text = cp.titre
    place(s, s.shapes.title, Inches(0.8), Inches(1.8), Inches(11.7), Inches(1.6))
    style(s.shapes.title.text_frame, 40)
    sub = [d.public_description()]
    if cp.referentiel:
        caps = ", ".join(f"{c['code']}" for c in cp.capacites_visees)
        sub.append(f"{cp.referentiel['nom']}" + (f" : {caps}" if caps else ""))
    s.placeholders[1].text = "\n".join(sub)
    place(s, s.placeholders[1], Inches(0.8), Inches(3.6), Inches(11.7), Inches(2.6))
    style(s.placeholders[1].text_frame, 20)
    notes(s, ["Support généré par SourcIA à partir du corpus pédagogique : chaque information renvoie à sa source.",
              f"Séquences présentées : {', '.join(map(str, sup.sequences))}."])

    nums = numbers(cp)
    figure = 0
    refs_used = []

    def add_image(ill, label):
        nonlocal figure
        img = corpus_dir / ill.chemin
        if not img.is_file():
            sup.remarques.append(f"présentation : illustration introuvable ({ill.chemin})")
            return
        slide = prs.slides.add_slide(only_l)
        title(slide, label, pt=26)
        box_w, box_h, top = Inches(11.5), Inches(4.9), Inches(1.45)
        pic = slide.shapes.add_picture(str(img), Inches(0.9), top, height=box_h)
        if pic.width > box_w:
            pic.height = int(pic.height * box_w / pic.width)
            pic.width = box_w
        pic.left = int((prs.slide_width - pic.width) / 2)
        figure += 1
        num = nums.get(ill.doc_id)
        ref = f"({num}, p. {ill.page})" if num else f"(p. {ill.page})"
        caption = f"{caption_label(figure, ill.legende)} {ref}"
        cap = slide.shapes.add_textbox(Inches(0.9), Inches(6.5), Inches(11.5), Inches(0.6)).text_frame
        cap.text = caption
        style(cap, 14, italic=True)
        notes(slide, [caption, "Illustration d'origine du document cité."])

    for i in sup.sequences:
        seq = cp.sequences[i - 1]
        slide = prs.slides.add_slide(content_l)
        title(slide, _seq_title(cp, i))
        body = slide.placeholders[1]
        place(slide, body, Inches(0.6), Inches(1.4), Inches(12.1), Inches(5.2))
        tf = body.text_frame
        tf.text = f"Objectif : {seq.objectif}"
        points = seq.points[:POINTS_PAR_DIAPO]
        lines, short = [f"Objectif : {seq.objectif}" + (f" (capacité {seq.capacite})" if seq.capacite else "")], []
        for p in points:
            r = make_ref(p.reference, nums)
            refs_used.append(r)
            para = tf.add_paragraph()
            para.text = p.texte
            para.level = 1
            lines += [f"• {p.texte} {r.label()}", f"  Extrait : « {r.extrait} »"]
            short.append(f"{r.numero or 'source'} p. {r.page}")
        if not points:
            para = tf.add_paragraph()
            para.text = "Aucun point clé retenu pour cette séquence : à compléter."
            para.level = 1
        style(tf, 18)
        tf.paragraphs[0].runs[0].font.bold = True
        tf.paragraphs[0].runs[0].font.size = Pt(22)
        if len(seq.points) > POINTS_PAR_DIAPO:
            lines.append(f"(+ {len(seq.points) - POINTS_PAR_DIAPO} autre(s) point(s) dans le corpus)")
        if short:
            foot = slide.shapes.add_textbox(Inches(0.6), Inches(6.8), Inches(12.1), Inches(0.4)).text_frame
            foot.text = "Sources : " + " · ".join(dict.fromkeys(short))
            style(foot, 12)
        notes(slide, lines)
        for ill in [x for x in cp.illustrations if x.sequence == i]:
            add_image(ill, f"{_seq_title(cp, i)} (illustration)")
    if len(sup.sequences) == len(cp.sequences):
        for ill in [x for x in cp.illustrations if not x.sequence or x.sequence > len(cp.sequences)]:
            add_image(ill, "Illustration")

    sources = cited_sources(cp, refs_used) or [b for b in cp.bibliographie if b.numero]
    for k in range(0, max(1, len(sources)), SOURCES_PAR_DIAPO):
        slide = prs.slides.add_slide(content_l)
        title(slide, "Sources" if k == 0 else "Sources (suite)")
        body = slide.placeholders[1]
        place(slide, body, Inches(0.6), Inches(1.4), Inches(12.1), Inches(5.6))
        tf = body.text_frame
        chunk = sources[k:k + SOURCES_PAR_DIAPO]
        tf.text = source_line(chunk[0]) if chunk else "Aucune source citée."
        for b in chunk[1:]:
            tf.add_paragraph().text = source_line(b)
        style(tf, 14)
        notes(slide, [source_line(b) for b in chunk])
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return path


def expected_slides(sup: Supports, cp, corpus_dir: Path) -> int:
    """Nombre de diapos attendu (pour les tests et l'affichage)."""
    n = 1 + len(sup.sequences)
    n += sum(1 for i in sup.sequences for x in cp.illustrations if x.sequence == i and (corpus_dir / x.chemin).is_file())
    if len(sup.sequences) == len(cp.sequences):
        n += sum(1 for x in cp.illustrations if (not x.sequence or x.sequence > len(cp.sequences))
                 and (corpus_dir / x.chemin).is_file())
    refs = [make_ref(p.reference, numbers(cp)) for i in sup.sequences for p in cp.sequences[i - 1].points[:POINTS_PAR_DIAPO]]
    sources = cited_sources(cp, refs) or [b for b in cp.bibliographie if b.numero]
    return n + max(1, -(-len(sources) // SOURCES_PAR_DIAPO))
