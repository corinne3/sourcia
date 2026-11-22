"""Étape 3 : le CORPUS PÉDAGOGIQUE (``corpus.json``), à partir des SEULS documents cochés et des acquis visés.

C'est la matière vérifiée que l'étape 4 (supports : Word, diaporama, QCM…) met en forme :
- les séquences du plan (titre, objectif, capacité du référentiel) ;
- les points clés, chacun avec sa RÉFÉRENCE : document, page, EXTRAIT EXACT (phrase recopiée du document)
  et lien (``#page=N`` pour un PDF) ;
- la synthèse, avec les mêmes références ;
- les illustrations d'origine des pages citées (illustrations.py, PyMuPDF), copiées dans le dossier ;
- la bibliographie (titre, organisme, année, adresse).

On réutilise ``FormationBuilder`` (plan, rattachement, points clés, synthèse, contrôles de checks.py), sans QCM.
Le contenu personnel du formateur n'est pas repris ici : seulement les documents cochés.

Dossier : ``data/corpus/corpus-<date>/`` avec ``corpus.json`` (rechargeable), ``demande.yaml`` et ``illustrations/``.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from sourcia.core.demande import Demande
from sourcia.core.text import split_sentences, tokenize
from sourcia.formation import checks
from sourcia.formation.builder import FormationBuilder, as_demande
from sourcia.observability.tracing import span


# ---------------------------------------------------------------------- modèle (corpus.json)
class Reference(BaseModel):
    doc_id: str
    page: int
    extrait: str = ""                        # phrase EXACTE du document (prise dans le passage), pour vérifier
    lien: str | None = None                  # adresse du document, avec #page=N pour un PDF ; None si privé


class PointCle(BaseModel):
    texte: str                               # phrase contrôlée par checks.py
    reference: Reference


class SequenceCorpus(BaseModel):
    titre: str
    objectif: str
    duree_min: int
    capacite: str | None = None              # C4.2…
    capacite_libelle: str | None = None
    capacite_statut: str = "aucune"          # mêmes valeurs que dans la formation (propose_ia, repli…)
    mots_cles: list[str] = Field(default_factory=list)
    points: list[PointCle] = Field(default_factory=list)
    a_retenir: str = ""
    remarques: list[str] = Field(default_factory=list)
    retires: list[str] = Field(default_factory=list)


class ParagrapheSynthese(BaseModel):
    texte: str
    reference: Reference


class SyntheseCorpus(BaseModel):
    paragraphes: list[ParagrapheSynthese] = Field(default_factory=list)
    conclusion: str = ""


class Illustration(BaseModel):
    chemin: str                              # relatif au dossier du corpus
    legende: str = ""                        # prise dans le document, sinon « Illustration tirée de … »
    doc_id: str
    page: int
    sequence: int | None = None              # séquence qui cite cette page (None : synthèse ou photo cochée)


class SourceBiblio(BaseModel):
    numero: str                              # S1, S2… dans l'ordre de première citation
    doc_id: str
    titre: str
    organisme: str | None = None
    annee: int | str | None = None           # année de publication, sinon des résultats, sinon date connue
    url: str | None = None                   # None pour un document privé
    nature: str = "pdf"                      # Document.kind
    pages_citees: list[int] = Field(default_factory=list)
    citee: bool = True                       # False : document coché mais jamais cité
    fourni_par_formateur: bool = False       # PDF téléversé dans un dossier enseignant (cité sans lien)
    catalog_id: str | None = None            # dossier enseignant : identifiant du document dans le catalogue


# Document.meta : marque posée par le contexte d'un dossier sur un PDF téléversé par le formateur
FOURNI = "fourni_par_formateur"


class CorpusPedagogique(BaseModel):
    version: str = "1"
    cree_le: str = ""
    demande: Demande
    titre: str
    dossier_id: str | None = None            # corpus construit depuis un dossier enseignant
    doc_ids: list[str]                       # les documents cochés (hors privés exclus)
    referentiel: dict | None = None          # id, nom, version, statut
    capacites_visees: list[dict] = Field(default_factory=list)   # code, libelle
    couverture: list[dict] = Field(default_factory=list)         # code, libelle, séquences
    sequences: list[SequenceCorpus] = Field(default_factory=list)
    synthese: SyntheseCorpus | None = None
    illustrations: list[Illustration] = Field(default_factory=list)
    bibliographie: list[SourceBiblio] = Field(default_factory=list)
    retires: list[str] = Field(default_factory=list)
    remarques: list[str] = Field(default_factory=list)
    exclus_prives: list[str] = Field(default_factory=list)
    echecs_modele: list[dict] = Field(default_factory=list)
    appels_modele: int = 0
    duree_s: float = 0.0


# ---------------------------------------------------------------------- références vérifiables
def source_url(doc) -> str | None:
    """Adresse à citer : la nouvelle si le document a été déplacé (``current_url``, branche catalogue),
    sinon l'adresse d'origine. Jamais pour un document privé (on ne montre pas son chemin)."""
    if doc is None or doc.private:
        return None
    return getattr(doc, "current_url", None) or doc.url or None


def page_link(doc, page: int | None) -> str | None:
    """Lien vers la page citée : ``#page=N`` ouvre un PDF à la bonne page (navigateurs, lecteurs PDF)."""
    url = source_url(doc)
    if url and doc.kind == "pdf" and page:
        return f"{url.split('#')[0]}#page={page}"
    return url


MAX_EXTRACT = 300           # caractères : un tableau extrait d'un PDF peut former une « phrase » de 1 000 caractères


def shorten(sentence: str, words: set[str], limit: int = MAX_EXTRACT) -> str:
    """Phrase trop longue : le morceau d'au plus ``limit`` caractères qui contient le plus de mots du point,
    coupé entre deux mots et marqué « … ». Le morceau reste recopié mot pour mot."""
    if len(sentence) <= limit:
        return sentence
    toks = sentence.split()
    best, best_score = (0, 0), -1
    for i in range(len(toks)):
        j, size = i, 0
        while j < len(toks) and size + len(toks[j]) + (j > i) <= limit:
            size += len(toks[j]) + (j > i)
            j += 1
        if j == i:
            continue
        score = len(words & set(tokenize(" ".join(toks[i:j]))))
        if score > best_score:
            best, best_score = (i, j), score
        if j == len(toks):
            break
    i, j = best
    return ("… " if i > 0 else "") + " ".join(toks[i:j]) + (" …" if j < len(toks) else "")


def best_extract(texte: str, doc_id: str, page: int, corpus, ignore: frozenset = frozenset()) -> str:
    """La phrase du document (même page) qui soutient le mieux ``texte`` : recopiée telle quelle
    (raccourcie avec « … » si elle dépasse MAX_EXTRACT caractères)."""
    sents = [s for p in corpus.passages if p.doc_id == doc_id and p.page == page for s in split_sentences(p.text)]
    if not sents:
        return ""
    words = set(tokenize(texte))

    def score(s: str) -> tuple[float, float]:
        return checks.support(texte, s, ignore), len(words & set(tokenize(s))) / max(1, len(words))
    return shorten(max(dict.fromkeys(sents), key=score), words)


def make_reference(texte: str, doc_id: str, page: int, corpus, ignore: frozenset = frozenset()) -> Reference:
    doc = corpus.ctx.store.get(doc_id)
    return Reference(doc_id=doc_id, page=page, extrait=best_extract(texte, doc_id, page, corpus, ignore),
                     lien=page_link(doc, page))


def bibliography(cp: CorpusPedagogique, ctx) -> list[SourceBiblio]:
    """Les documents cités (S1, S2… dans l'ordre de première citation), puis les documents cochés non cités."""
    pages: dict[str, list[int]] = {}
    refs = [p.reference for s in cp.sequences for p in s.points]
    refs += [x.reference for x in (cp.synthese.paragraphes if cp.synthese else [])]
    for r in refs:
        pages.setdefault(r.doc_id, [])
        if r.page not in pages[r.doc_id]:
            pages[r.doc_id].append(r.page)
    out = []
    for did in list(pages) + [x for x in cp.doc_ids if x not in pages]:
        doc = ctx.store.get(did)
        if doc is None:
            continue
        fi = ctx.qualifier.get(did)
        annee = (fi.get("annee_publication") or fi.get("annee")) if fi else None
        annee = annee or (doc.date[:4] if doc.date else None)
        organisme = fi.get("organisme") if fi else None
        cited = did in pages
        out.append(SourceBiblio(numero=f"S{len(out) + 1}" if cited else "", doc_id=did, titre=doc.title or did,
                                organisme=str(organisme) if organisme else None, annee=annee, url=source_url(doc),
                                nature=doc.kind, pages_citees=sorted(pages.get(did, [])), citee=cited,
                                fourni_par_formateur=bool(doc.meta.get(FOURNI)),
                                catalog_id=doc.meta.get("catalog_id")))
    return out


# ---------------------------------------------------------------------- construction
def build_corpus(ctx, demande, doc_ids: list[str], *, llm=None, n_seq: int = 4,
                 log=lambda *a: None) -> CorpusPedagogique:
    """Plan → rattachement au référentiel → points clés par séquence (sans QCM) → synthèse → références."""
    d = as_demande(demande)
    t0 = time.perf_counter()
    b = FormationBuilder(ctx, llm)
    # les points clés et la synthèse sont TOUJOURS produits ici (ils font le corpus), quelles que soient les sorties
    work = d.model_copy(update={"sorties": list(dict.fromkeys([*d.sorties, "plan", "points_cles", "synthese"]))})
    ref = b.load_ref(d)
    # accord explicite (autoriser_cloud_personnel) : les documents PRIVÉS cochés peuvent aller au modèle en ligne ;
    # sans accord, prepare() les exclut avec un modèle en ligne et ils sont listés dans exclus_prives
    private = [i for i in doc_ids if (x := ctx.store.get(i)) is not None and x.private]
    corpus = b.prepare(work, doc_ids, allow_private=private)
    with span("corpus", demande=d.sujet, docs=len(corpus.docs)):
        log(f"  {len(corpus.docs)} documents cochés, {len(corpus.passages)} passages"
            + (f" ({len(corpus.excluded_private)} privés exclus : modèle en ligne)" if corpus.excluded_private else ""))
        plan, how = b.plan(corpus, work, ref, n_seq)
        seqs, couverture, notes = b.attach(plan, work, ref, how)
        log(f"  plan ({'modèle' if how == 'modele' else 'repli sans modèle'}) : {len(seqs)} séquences")
        cp = CorpusPedagogique(
            cree_le=datetime.now().isoformat(timespec="seconds"), demande=d, titre=b.title_for(plan, d),
            doc_ids=[x.id for x in corpus.docs], couverture=couverture, remarques=notes,
            exclus_prives=[x.title for x in corpus.excluded_private],
            referentiel={"id": ref.id, "nom": ref.nom, "version": ref.version, "statut": ref.statut} if ref else None,
            capacites_visees=[{"code": c.code, "libelle": c.libelle} for c in ref.leaves(d.capacites)] if ref else [])
        if d.diplomante and not ref:
            cp.remarques.append("formation diplômante sans référentiel trouvé : rattachement impossible "
                                f"(« {d.diplome} » absent de config/referentiels)")
        if d.notes_personnelles.strip() or d.fichiers_personnels:
            cp.remarques.append("contenu personnel non repris dans le corpus (seulement les documents cochés) : "
                                "il pourra être ajouté dans les supports")
        for i, s in enumerate(seqs, 1):
            log(f"  séquence {i}/{len(seqs)} : {s.titre}")
            r = b.sequence(corpus, s, work, n_quiz=0)
            cp.sequences.append(SequenceCorpus(
                titre=r.titre, objectif=r.objectif, duree_min=r.duree_min, capacite=r.capacite,
                capacite_libelle=r.capacite_libelle, capacite_statut=r.capacite_statut, mots_cles=r.mots_cles,
                a_retenir=r.a_retenir, remarques=r.remarques, retires=r.retires,
                points=[PointCle(texte=p.texte, reference=make_reference(p.texte, p.doc_id, p.page, corpus, b.topic))
                        for p in r.points]))
        log("  synthèse")
        syn = b.synthese(corpus, work, cp.retires)
        if syn:
            cp.synthese = SyntheseCorpus(conclusion=syn["conclusion"], paragraphes=[
                ParagrapheSynthese(texte=x["texte"],
                                   reference=make_reference(x["texte"], x["doc_id"], x["page"], corpus, b.topic))
                for x in syn["paragraphes"]])
        else:
            cp.remarques.append("synthèse non produite : tout ce que le modèle a proposé a été retiré par les contrôles")
        cp.bibliographie = bibliography(cp, ctx)
    cp.echecs_modele = b.failures
    cp.appels_modele = b.calls
    cp.duree_s = round(time.perf_counter() - t0, 1)
    return cp


# ---------------------------------------------------------------------- fichiers
def new_corpus_folder(out_root: Path) -> Path:
    """Crée ``corpus-<date>`` (``-2``, ``-3``… si deux corpus naissent dans la même seconde) et le renvoie."""
    base = Path(out_root) / f"corpus-{datetime.now():%Y%m%d-%H%M%S}"
    out, k = base, 1
    while out.exists():                      # on n'écrase jamais un corpus existant
        k += 1
        out = base.with_name(f"{base.name}-{k}")
    out.mkdir(parents=True)
    return out


def write_corpus(cp: CorpusPedagogique, out_root: Path, ctx=None, max_illustrations: int = 12,
                 folder: Path | None = None) -> list[Path]:
    """Écrit ``corpus-<date>/corpus.json`` et ``demande.yaml`` ; renvoie les chemins.
    Avec ``ctx`` : copie d'abord les illustrations des pages citées dans ``corpus-<date>/illustrations/``.
    ``folder`` : dossier déjà créé (par ``new_corpus_folder``), quand l'identifiant est donné avant la construction."""
    out = Path(folder) if folder is not None else new_corpus_folder(out_root)
    out.mkdir(parents=True, exist_ok=True)
    if ctx is not None and max_illustrations > 0:
        from sourcia.formation.illustrations import extract_illustrations

        extract_illustrations(cp, ctx, out, max_total=max_illustrations)
    (out / "corpus.json").write_text(cp.model_dump_json(indent=1), encoding="utf-8")
    return [out / "corpus.json", cp.demande.save(out / "demande.yaml")]


def load_corpus(folder: Path) -> CorpusPedagogique:
    """Relit un corpus : le dossier ``corpus-<date>`` ou directement le fichier ``corpus.json``."""
    p = Path(folder)
    p = p / "corpus.json" if p.is_dir() else p
    return CorpusPedagogique.model_validate_json(p.read_text(encoding="utf-8"))
