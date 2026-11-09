"""Sélection (M5) : l'entonnoir qui mène à ≈ 50 documents justifiés.

1. recherche (M4) : quelques centaines de candidats ;
2. qualification (M3) : passe « règles » pour tous, passe « modèle » pour les mieux classés (coût maîtrisé) ;
3. filtres du formateur (années, types, sources) ;
4. score = pertinence + récence + qualité du dispositif, puis diversité (pas plus de N par organisme) ;
5. justification courte, construite à partir de la fiche et du passage trouvé : elle ne peut pas inventer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlparse

from sourcia.core.models import Candidate
from sourcia.core.text import normalize, truncate_words
from sourcia.observability.tracing import span

QUALITY = {"experimentation": 0.8, "synthese": 0.7, "guide_technique": 0.6, "retour_experience": 0.6, "autre": 0.4}
TYPE_LABEL = {"experimentation": "expérimentation", "retour_experience": "retour d'expérience", "synthese": "synthèse",
              "guide_technique": "guide technique", "autre": "autre"}


@dataclass
class Filters:
    annee_min: int | None = None
    annee_max: int | None = None
    types: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    region: str | None = None                  # région du formateur (alerte « contexte éloigné »)
    strict: bool = False                       # True : exclure les documents dont la valeur filtrée est inconnue
    kinds: list[str] = field(default_factory=list)          # natures : pdf, donnees, video, image…
    publiques_seulement: bool = False
    bonus_types: dict[str, float] = field(default_factory=dict)   # préférences du profil et du public
    bonus_organismes: list[str] = field(default_factory=list)


def quality_score(fiche) -> float:
    if fiche is None:
        return 0.4
    t = fiche.get("type")
    q = QUALITY.get(t, 0.4)
    if t == "experimentation" and fiche.get("repetitions"):
        q = 1.0
    return max(0.0, q - 0.03 * len(fiche.alertes))


def recency_score(year: int | None) -> float:
    if not isinstance(year, int):
        return 0.4
    return max(0.0, min(1.0, (year - (date.today().year - 20)) / 20))


def passes(c: Candidate, f: Filters) -> bool:
    fi = c.fiche
    year = fi.year() if fi else None
    typ = fi.get("type") if fi else None
    if f.annee_min and (year is None and f.strict or isinstance(year, int) and year < f.annee_min):
        return False
    if f.annee_max and isinstance(year, int) and year > f.annee_max:
        return False
    if f.types and (typ is None and f.strict or typ is not None and typ not in f.types):
        return False
    if f.sources and c.document.source not in f.sources:
        return False
    if f.kinds and c.document.kind not in f.kinds:
        return False
    if f.publiques_seulement and c.document.private:
        return False
    return True


def bonus(c: Candidate, f: Filters) -> float:
    b = f.bonus_types.get(c.fiche.get("type"), 0.0) if c.fiche else 0.0
    org = normalize(" ".join([str(c.fiche.get("organisme") or "") if c.fiche else "", c.document.source]))
    if any(normalize(o) in org for o in f.bonus_organismes):
        b += 0.1
    return b


def justify(c: Candidate, f: Filters) -> str:
    fi = c.fiche
    parts = []
    if c.passage:
        where = f" (p. {c.page})" if c.page else " (titre)"
        parts.append(f"Pertinent : « {truncate_words(c.passage, 28)} »{where}")
    if fi:
        facts = [str(fi.get("organisme") or ("document privé" if c.document.private else c.document.source))]
        if fi.get("annee"):
            facts.append(f"résultats {fi.get('annee')}")
        if fi.get("annee_publication") and fi.get("annee_publication") != fi.get("annee"):
            facts.append(f"publié en {fi.get('annee_publication')}")
        if fi.get("type"):
            facts.append(TYPE_LABEL.get(fi.get("type"), fi.get("type")))
        if fi.get("modalites") or fi.get("repetitions"):
            facts.append(f"{fi.get('modalites') or '?'} modalités × {fi.get('repetitions') or '?'} répétitions")
        if fi.get("lieu"):
            facts.append(str(fi.get("lieu")))
        parts.append(" · ".join(facts))
        alerts = list(fi.alertes)
        if f.region and (fi.get("lieu") or fi.get("organisme")):
            from sourcia.core.geo import canonical_region, region_of

            want = canonical_region(f.region) or f.region
            # région du lieu ; sinon celle de l'organisme (« Chambre d'agriculture de Normandie »)
            got = region_of(f"{fi.get('lieu')} {fi.lieu.evidence or ''}") or region_of(fi.organisme.evidence or "") \
                or {".ch": "Suisse", ".be": "Belgique", ".lu": "Luxembourg", ".ca": "Canada"}.get(
                    "." + urlparse(c.document.url).netloc.rsplit(".", 1)[-1] if c.document.url.startswith("http") else "")
            if got and got != want:
                alerts.insert(0, f"contexte éloigné de {f.region} ({got})")   # en tête : c'est le filtre demandé
        if alerts:
            parts.append("⚠️ " + " ; ".join(alerts[:3]))
    return " — ".join(parts)


def select_demande(selector, demande, llm_top: int = 0) -> list[Candidate]:
    """Sélection pilotée par la demande structurée (M0) : sujet, filtres, préférences du profil et du public."""
    return selector.select(demande.sujet, demande.filters(), n=demande.nombre_sources, llm_top=llm_top)


class Selector:
    def __init__(self, settings, store, index, qualifier):
        self.settings = settings
        self.store = store
        self.index = index
        self.qualifier = qualifier

    def select(self, demande: str, filters: Filters | None = None, n: int | None = None,
               llm_top: int = 0) -> list[Candidate]:
        """``llm_top`` : nombre de candidats les mieux classés à qualifier par le modèle (0 = règles seules)."""
        f = filters or Filters()
        cfg = self.settings.select
        n = n or cfg.n
        with span("select", demande=demande, n=n):
            hits = self.index.search(demande)
            cands: list[Candidate] = []
            for rank, h in enumerate(hits):
                doc = self.store.get(h.doc_id)
                if doc is None:
                    continue
                fiche = self.qualifier.qualify(doc, use_llm=rank < llm_top) if doc.status != "listed" else None
                cands.append(Candidate(document=doc, fiche=fiche, relevance=h.score, passage=h.passage, page=h.page))
            kept = [c for c in cands if passes(c, f)]
            for c in kept:
                year = c.fiche.year() if c.fiche else None
                c.components = {"pertinence": round(c.relevance, 3), "recence": round(recency_score(year), 3),
                                "qualite": round(quality_score(c.fiche), 3)}
                c.components["bonus_demande"] = round(bonus(c, f), 3)
                c.score = (cfg.weight_relevance * c.components["pertinence"] + cfg.weight_recency * c.components["recence"]
                           + cfg.weight_quality * c.components["qualite"] + c.components["bonus_demande"])
            kept.sort(key=lambda c: -c.score)
            chosen, per_org = [], {}
            for c in kept:                                   # diversité des organismes
                org = normalize(str((c.fiche.get("organisme") if c.fiche else None) or c.document.source))
                if per_org.get(org, 0) >= cfg.max_per_source:
                    continue
                per_org[org] = per_org.get(org, 0) + 1
                c.justification = justify(c, f)
                chosen.append(c)
                if len(chosen) >= n:
                    break
        return chosen
