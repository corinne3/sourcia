"""Qualification, passe 1 : des règles simples, gratuites et explicables (pas de modèle).

Chaque valeur trouvée est accompagnée de sa PREUVE (la phrase du document) et d'une confiance
modeste : les règles se trompent parfois, la passe 2 (modèle) ou un humain peut les corriger.
"""
from __future__ import annotations

import re
from datetime import date

from sourcia.core.models import Field_, Fiche
from sourcia.core.text import normalize, split_sentences

ORGANISMES = [
    ("Chambre d'agriculture", r"chambres? d.agriculture[^.,;\n]{0,40}"),
    ("Arvalis", r"arvalis"),
    ("Terres Inovia", r"terres inovia"),
    ("Idele (Institut de l'Élevage)", r"institut de l.elevage|\bidele\b"),
    ("INRAE", r"\binrae?\b"),
    ("Civam", r"\b(fr|ad)?civam\b"),
    ("ACTA", r"\bacta\b"),
    ("Agro-Transfert", r"agro.transfert"),
    ("Comifer", r"\bcomifer\b"),
    ("Lycée agricole / EPLEFPA", r"lycee agricole|eplefpa|lpa\b"),
    ("Coopérative", r"cooperative [a-z]+"),
    ("Institut technique", r"institut technique"),
    ("GEVES", r"\bgeves\b"),
    ("Sorghum ID", r"sorghum id"),
    ("Prométerre / Proconseil", r"prometerre|proconseil"),
    ("Agroscope", r"agroscope"),
    ("CRA-W (Wallonie)", r"\bcra.w\b|centre wallon de recherches"),
    ("Service public de Wallonie", r"service public de wallonie|\bspw\b"),
    ("Inn'Ovin", r"inn.?ovin"),
    ("Semae", r"\bsemae\b|\bgnis\b"),
]
# organisme déduit du site quand le texte ne le dit pas (meilleur que le nom donné à la source)
HOSTS = {"geves.fr": "GEVES", "sorghum-id.com": "Sorghum ID", "prometerre.ch": "Prométerre / Proconseil",
         "inn-ovin.fr": "Inn'Ovin", "idele.fr": "Idele (Institut de l'Élevage)", "arvalis.fr": "Arvalis",
         "terresinovia.fr": "Terres Inovia", "inrae.fr": "INRAE", "agroscope.admin.ch": "Agroscope",
         "cra.wallonie.be": "CRA-W (Wallonie)", "agriculture.wallonie.be": "Service public de Wallonie",
         "rd-agri.fr": "RD Agri (ACTA)", "civam.org": "Civam"}


def organisme_from_url(url: str) -> str | None:
    from urllib.parse import urlparse

    host = urlparse(url or "").netloc.lower().removeprefix("www.")
    if not host:
        return None
    for h, name in HOSTS.items():
        if host == h or host.endswith("." + h):
            return name
    m = re.match(r"([a-z-]+)\.chambres?-agriculture\.fr$", host)
    if m:
        return f"Chambre d'agriculture ({m.group(1)})"
    return host
DOC_TYPE_TERMS = {
    "experimentation": ["essai", "dispositif", "modalite", "repetition", "bloc", "temoin", "protocole",
                        "significati", "analyse de variance", "p <", "parcelles elementaires", "experimentation"],
    "retour_experience": ["temoignage", "retour d'experience", "retours d'experience", "eleveur", "agriculteur",
                          "sur mon exploitation", "dans notre ferme", "j'ai ", "nous avons choisi", "groupe d'agriculteurs"],
    "synthese": ["synthese", "revue bibliographique", "etat des connaissances", "bilan de", "dossier"],
    "guide_technique": ["guide", "fiche technique", "recommandation", "conseils", "itineraire technique", "mode d'emploi",
                        "conduite technique", "preconisation", "reperes techniques", "a retenir", "attention danger"],
}
NUM_WORDS = {"deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10}
SOIL_RE = re.compile(r"(sols? (?:est |sont )?(?:limono|argilo|sablo|limoneux|argileux|sableux|calcaires?|hydromorphes?|superficiels?|profonds?)[\w-]*"
                     r"|r(?:eserve )?u(?:tile)?\s*(?:de|=|:)?\s*\d+\s*mm|\d{3,4}\s*mm (?:de pluie|de precipitations|par an)"
                     r"|secheresse|canicule|climat (?:oceanique|continental|mediterraneen|semi-continental))")
REGIONS = ["pays de la loire", "bretagne", "normandie", "nouvelle-aquitaine", "occitanie", "grand est", "hauts-de-france",
           "auvergne-rhone-alpes", "bourgogne-franche-comte", "centre-val de loire", "ile-de-france", "provence", "corse",
           "maine-et-loire", "loire-atlantique", "vendee", "mayenne", "sarthe"]
FARM_RE = re.compile(r"((?:ferme|station) experimentale (?:de |des |du |d')[a-z' -]{3,40})")
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
MONEY_RE = re.compile(r"(€|\beuros?\b|marge brute|cout de production|€/ha|rentabilite|prix de revient)")


def _sentence_with(text: str, pattern: re.Pattern | str) -> str | None:
    pat = re.compile(pattern) if isinstance(pattern, str) else pattern
    for s in (s for line in text.splitlines() for s in split_sentences(line)):   # une ligne = au plus une phrase
        if pat.search(normalize(s)):
            return s[:300]
    return None


# année de publication : « publié en 2021 », « © 2021 »… et l'année accolée au genre du document en tête
# (« Fiche témoignage 2024 », « Guide technique 2022 », « Synthèse 2019 ») : c'est une date de sortie, pas d'essai
PUB_RE = re.compile(r"(?:publie\w*|parution|edition|mise a jour|redige\w*|©|\(c\)"
                    r"|(?:fiche|guide|synthese|bulletin|brochure|plaquette|note|lettre|dossier)(?:\s+[a-z]+){0,2}\s*[-:]?)"
                    r"\D{0,20}?(19[89]\d|20[0-4]\d)")
RESULT_RE = re.compile(r"\b(?:essais?|campagnes?|recoltes?|semis|annees?|experimentations?|suivis?|resultats?|en)"
                       r"\D{0,25}(19[89]\d|20[0-4]\d)(?:\s*[-/a]\s*(19[89]\d|20[0-4]\d))?")


def _original(text: str, t: str, start: int, end: int) -> str:
    """Le passage d'origine (majuscules, accents) correspondant à une position dans le texte normalisé."""
    return text[start:end] if len(text) == len(t) else t[start:end]


def _num(token: str) -> int | None:
    return int(token) if token.isdigit() else NUM_WORDS.get(token)


def qualify_rules(text: str, doc_date: str | None = None, keywords: list[str] | None = None,
                  themes_vocab: list[str] | None = None, title: str = "") -> Fiche:
    """Remplit une fiche à partir du texte des premières pages."""
    t = normalize(text)
    f = Fiche(document_id="")
    # organisme : le premier cité (souvent l'auteur, en tête de document)
    best = None
    for name, pat in ORGANISMES:
        m = re.search(pat, t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), name, pat)
    if best:
        name = best[1]
        if name == "Chambre d'agriculture":          # « Chambre d'agriculture de Saône-et-Loire » : on garde le territoire
            from sourcia.core.geo import REGIONS as GEO_REGIONS, _n

            m = re.search(r"chambres? d.agriculture (?:regionale )?(?:de la |de l.|du |des |de |d.)([a-z' -]{3,40})", t)
            if m:
                tail = f" {_n(m.group(1))} "
                places = [r for r in GEO_REGIONS] + [d for ds in GEO_REGIONS.values() for _, d in ds]
                hit = max((p for p in places if tail.startswith(f" {_n(p)} ")), key=len, default=None)
                if hit:
                    name = f"Chambre d'agriculture {'de ' if not hit[0] in 'AEIOUYÎÉ' else 'd’'}{hit}"
        f.organisme = Field_(value=name, evidence=_sentence_with(text, best[2]), confidence=0.5, method="regles")
    # deux années distinctes (demande du métier) :
    # - annee_publication : date donnée par la source, sinon « publié en 2021 », « © 2021 », « édition 2021 » ;
    # - annee (résultats) : années proches des mots d'essai (« essai 2017-2019 » → 2019), sinon la plus récente citée.
    this_year = date.today().year
    if doc_date and YEAR_RE.search(doc_date):
        f.annee_publication = Field_(value=int(YEAR_RE.search(doc_date).group(1)),
                                     evidence=f"date de la source : {doc_date}", confidence=0.8, method="source")
    else:
        m = PUB_RE.search(t)
        if m and int(m.group(1)) <= this_year:
            f.annee_publication = Field_(value=int(m.group(1)), evidence=_sentence_with(text, m.group(1)),
                                         confidence=0.6, method="regles")
    t_res = PUB_RE.sub(" ", t)                            # les mentions de publication ne sont pas des résultats
    near = [y for pair in RESULT_RE.findall(t_res) for y in pair if y]
    years = [int(y) for y in (near or YEAR_RE.findall(t_res)) if int(y) <= this_year]
    pub = f.get("annee_publication")
    if not near and pub:                                  # pas d'année d'essai explicite : on ne recopie pas la publication
        years = [y for y in years if y != pub]
    if years:
        y = max(years)
        f.annee = Field_(value=y, evidence=_sentence_with(text, str(y)), confidence=0.5 if near else 0.3, method="regles")
    # lieu : ferme expérimentale nommée, sinon région ou département cité
    m = FARM_RE.search(t)
    if m:
        f.lieu = Field_(value=_original(text, t, m.start(1), m.end(1)).strip(), evidence=_sentence_with(text, re.escape(m.group(1)[:30])), confidence=0.6, method="regles")
    else:
        for r in REGIONS:
            if r in t:
                i = t.index(r)
                f.lieu = Field_(value=_original(text, t, i, i + len(r)), evidence=_sentence_with(text, re.escape(r)), confidence=0.4, method="regles")
                break
    # contexte pédoclimatique
    ctx = list(dict.fromkeys(_original(text, t, m.start(), m.end()) for m in SOIL_RE.finditer(t)))
    if ctx:
        f.contexte_pedoclimatique = Field_(value=", ".join(ctx[:4]), evidence=_sentence_with(text, SOIL_RE),
                                           confidence=0.4, method="regles")
    # type de document : le vocabulaire le plus présent
    tt = normalize(title or "")
    scores = {k: sum(t.count(w) + 3 * tt.count(w) for w in ws) for k, ws in DOC_TYPE_TERMS.items()}   # le titre compte triple
    k, s = max(scores.items(), key=lambda x: x[1])
    if s >= 2:
        f.type = Field_(value=k, evidence=_sentence_with(text, "|".join(re.escape(w) for w in DOC_TYPE_TERMS[k])),
                        confidence=min(0.7, 0.3 + 0.05 * s), method="regles")
    # dispositif
    for field, pat in (("modalites", r"(\d+|" + "|".join(NUM_WORDS) + r") (?:modalites|traitements|variantes)"),
                       ("repetitions", r"(\d+|" + "|".join(NUM_WORDS) + r") (?:repetitions|blocs)")):
        m = re.search(pat, t)
        if m and _num(m.group(1)):
            setattr(f, field, Field_(value=_num(m.group(1)), evidence=_sentence_with(text, re.escape(m.group(0))),
                                     confidence=0.7, method="regles"))
    # un guide ou une synthèse n'a pas de « résultats » d'essai propres : son année est une date de publication
    if f.get("type") in ("guide_technique", "synthese") and f.get("annee") and \
            not re.search(r"essai|campagne|recolte|resultat|experimentation", normalize(f.annee.evidence or "")):
        if not f.get("annee_publication"):
            f.annee_publication = f.annee.model_copy(update={"confidence": 0.4})
        f.annee = Field_()
    # un document ne peut pas être publié avant ses propres résultats : l'année de publication trouvée est fausse
    if f.get("annee") and f.get("annee_publication") and f.get("annee_publication") < f.get("annee") \
            and f.annee_publication.method != "source":
        f.annee_publication = Field_()
    # chiffrage économique
    m = MONEY_RE.search(t)
    f.chiffrage_economique = (Field_(value=True, evidence=_sentence_with(text, MONEY_RE), confidence=0.6, method="regles")
                              if m else Field_(value=False, confidence=0.3, method="regles"))
    # thèmes : mots-clés de la source + vocabulaire du domaine trouvé dans le texte
    found = [w for w in (themes_vocab or []) if normalize(w) in t]
    f.themes = sorted(set((keywords or []) + found))[:12]
    f.passes.append("regles")
    return f
