"""Qualification (M3) : deux passes, fusion, alertes, cache.

- passe 1 (règles) sur tous les documents : gratuite ;
- passe 2 (modèle) sur les documents demandés (en pratique, les candidats d'une recherche) ;
- fusion : la valeur la plus sûre l'emporte ; si règles et modèle s'accordent, la confiance monte ;
- alertes : date, réglementation ancienne, absence de chiffrage, dispositif non précisé…
- cache : une fiche calculée est réutilisée (``fiches.jsonl``), pour tous les formateurs.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from sourcia.core.models import Field_, Fiche
from sourcia.core.text import normalize
from sourcia.extract.pdf import first_pages_text, load_text
from sourcia.observability.tracing import span
from sourcia.qualify.llm import qualify_llm
from sourcia.qualify.rules import qualify_rules

THEMES_VOCAB = ["sorgho", "prairie", "prairies temporaires", "luzerne", "trèfle", "méteil", "maïs", "fourrage",
                "dérobée", "couvert végétal", "sécheresse", "irrigation", "pâturage", "ensilage", "foin", "stock fourrager",
                "changement climatique", "autonomie fourragère", "légumineuses", "mélanges", "rendement", "valeur alimentaire"]


def merge(a: Field_, b: Field_) -> Field_:
    """Fusionne deux qualifications d'un même champ."""
    if a.value is None:
        return b
    if b.value is None:
        return a
    if normalize(str(a.value)) == normalize(str(b.value)):
        best = a if a.confidence >= b.confidence else b
        return best.model_copy(update={"confidence": min(0.95, max(a.confidence, b.confidence) + 0.15)})
    return a if a.confidence >= b.confidence else b


def alerts(f: Fiche, text: str, settings) -> list[str]:
    cfg = settings.qualify
    out = []
    y = f.get("annee")
    if isinstance(y, int) and y < cfg.recent_year:
        out.append(f"résultats de {y}, antérieurs aux sécheresses récentes ({cfg.recent_year})")
    pub = f.get("annee_publication")
    if f.get("annee") is None and not (pub and f.get("type") in ("guide_technique", "synthese")):
        out.append("année des résultats non trouvée" + (f" (publication {pub})" if pub else ""))
    if f.get("annee") is None:
        if isinstance(pub, int) and pub < cfg.recent_year:
            out.append(f"publié en {pub}, avant les sécheresses récentes ({cfg.recent_year})")
    elif isinstance(pub, int) and isinstance(y, int) and pub - y >= 3:
        out.append(f"résultats de {y} publiés en {pub} : données anciennes dans un document récent")
    low = normalize(text)
    for term in cfg.old_regulation_terms:
        if normalize(term) in low:
            out.append(f"mentionne « {term} » : vérifier la réglementation actuelle")
    if f.get("chiffrage_economique") is False:
        out.append("pas de chiffrage économique repéré")
    t = f.get("type")
    if t == "retour_experience":
        out.append("retour d'expérience : pas de dispositif statistique")
    if t == "experimentation" and not f.get("repetitions"):
        out.append("expérimentation : nombre de répétitions non précisé")
    if f.get("lieu") is None:
        out.append("lieu non trouvé")
    return out


def resource_alerts(doc) -> list[str]:
    out = []
    if doc.meta.get("metadonnees_seules"):
        out.append("ressource qualifiée sur ses seules métadonnées (titre, description) : contenu non lu")
    if doc.kind in ("image", "video", "audio"):
        out.append(f"{ {'image': 'photo', 'video': 'vidéo', 'audio': 'audio'}[doc.kind]} : vérifier les droits d'utilisation")
    if doc.kind == "donnees":
        out.append("jeu de données : vérifier la licence et la date de mise à jour")
    return out


class Qualifier:
    def __init__(self, settings, llm=None):
        self.settings = settings
        self.llm = llm
        self.text_dir = settings.path("text", ".keep").parent
        self.path = settings.path("fiches.jsonl")
        self.fiches: dict[str, Fiche] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    fi = Fiche.model_validate_json(line)
                    self.fiches[fi.document_id] = fi

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(f.model_dump_json() + "\n" for f in self.fiches.values()), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, doc_id: str) -> Fiche | None:
        return self.fiches.get(doc_id)

    def _llm_allowed(self, doc) -> bool:
        cloud = self.settings.llm.provider == "litellm"
        return bool(self.llm) and self.settings.qualify.llm_pass and not (doc.private and cloud)

    def qualify(self, doc, use_llm: bool = False, force: bool = False) -> Fiche | None:
        old = self.fiches.get(doc.id)
        if old and not force and (not use_llm or "llm" in old.passes):
            return old                                               # cache
        text_data = load_text(doc.id, self.text_dir)
        if text_data is None:
            return None
        text = first_pages_text(text_data, self.settings.extract.first_pages)
        t0 = time.perf_counter()
        with span("qualify", doc=doc.id, llm=use_llm):
            f = qualify_rules(text, doc.date, doc.keywords, THEMES_VOCAB, title=doc.title)
            if not f.organisme.value and not doc.private:
                from sourcia.qualify.rules import organisme_from_url

                org = organisme_from_url(doc.url) if doc.url.startswith("http") else None
                if org or doc.source not in ("prive", "local", "personnel"):
                    f.organisme = Field_(value=org or doc.source, evidence=f"site : {org or doc.source}",
                                         confidence=0.3, method="source")
            if not f.get("annee_publication") and not f.get("annee") and doc.url.startswith("http"):
                # dernier recours : l'année dans l'adresse (« …/uploads/2017/10/… », « …-2024.pdf »), indice faible
                m = re.search(r"/((?:19[89]|20[0-4])\d)/\d{2}/|[_-]((?:19[89]|20[0-4])\d)(?:[_-]|\.pdf)", doc.url)
                if m:
                    y = int(m.group(1) or m.group(2))
                    f.annee_publication = Field_(value=y, evidence=f"année tirée de l'adresse : {doc.url[-80:]}",
                                                 confidence=0.3, method="source")
            if use_llm and self._llm_allowed(doc):
                try:
                    g, report = qualify_llm(self.llm, text[: self.settings.qualify.max_chars],
                                            self.settings.qualify.min_evidence_overlap)
                    for name in Fiche.FIELDS:
                        setattr(f, name, merge(getattr(f, name), getattr(g, name)))
                    f.resume = g.resume
                    f.passes.append("llm")
                    if report["rejetes"]:
                        f.passes.append("preuves_rejetees:" + ",".join(report["rejetes"]))
                except Exception as exc:                              # le modèle échoue : on garde les règles
                    f.passes.append(f"llm_echec:{type(exc).__name__}")
            if text_data.get("scanned"):
                f.alertes.append("PDF sans texte lisible (scanné) : qualification impossible sans OCR")
        f.document_id = doc.id
        f.alertes += alerts(f, text, self.settings) + resource_alerts(doc)
        if doc.kind in ("image", "video", "audio", "donnees"):          # pas de dispositif ni de lieu attendus
            f.alertes = [a for a in f.alertes if not a.startswith(("lieu non trouvé", "pas de chiffrage"))]
        f.cout_s = round(time.perf_counter() - t0, 2)
        self.fiches[doc.id] = f
        doc.status = "qualified"
        return f
