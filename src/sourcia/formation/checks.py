"""Contrôles dans le CODE (un contenu bien formé n'est pas forcément juste).

1. Chaque point clé, définition ou élément de réponse doit être SOUTENU par le passage qu'il cite
   (mots porteurs de sens retrouvés ; un nombre doit y figurer à l'identique).
2. QCM : l'explication doit être soutenue par son passage ; la bonne réponse marquée doit être celle
   que l'explication justifie (sinon on corrige l'index) ; pas de question ambiguë ni en double.
Heuristiques lexicales : elles ne comprennent ni la paraphrase ni la négation. D'où la règle :
le formateur RELIT avant diffusion. Ce qui est retiré est listé dans le rapport, jamais caché.
"""
from __future__ import annotations

import re

from sourcia.core.text import tokenize

LETTERS = "ABCD"
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


CITE_PAREN_RE = re.compile(r"\s*\((?:[^()]*\[\d+\][^()]*|[^()]*,\s*p\.?\s*\d+)\)")   # « (Titre, [3]) », « (doc, p. 2) »
CITE_RE = re.compile(r"\s*(?:\[\d+(?:\s*[,;]\s*\d+)*\]|\[n\]|\(\s*(?:n°|passage)\s*\d+\s*\)|\bn°\s*\d+)")
LEAD_RE = re.compile(r"^\s*(?:[-–•]\s*)?(?:selon|d['’]apr[eè]s)\s*[,:]\s*", re.I)    # « Selon [3], … » → « Selon, … »
FRAME_RE = re.compile(r"^(?:(?:selon|d['’]apr[eè]s)\s+[^,]{3,80},\s*|(?:l[ae]s?|une?|des|ce|cette|ces)\s+[^.]{3,80}?\s+"
                      r"(?:a|ont|avait|avaient)?\s*(?:montr|indiqu|r[ée]v[ée]l|confirm|soulign|rapport|d[ée]montr|expliqu)\w*\s+que\s+)", re.I)
META_RE = re.compile(r"^(?:le|les|ce|ces|un|une)\s+(?:\w+\s+){0,4}?(?:passages?|documents?|textes?|sources?|extraits?)\b"
                     r"[^.]{0,60}?\b(?:montre|indique|souligne|illustre|propose|pr[ée]sente|explique|d[ée]crit|pr[ée]cise)", re.I)


# phrases à jeter après retrait des citations (vu le 09/11) : « Ce résultat est mentionné dans [2]. » → « …dans. »,
# consignes recopiées (« L'explication est UNE phrase… »), avertissement des exemples fictifs
DANGLING_RE = re.compile(r"\b(?:dans|sur|par|de|du|des|et|selon|voir)\s*[.;:]?\s*$", re.I)
ECHO_RE = re.compile(r"l['’]explication est|une phrase reprise|n['’]invente|10 mots au plus|25 mots au plus|"
                     r"document fictif|ne pas citer", re.I)
HEDGE_RE = re.compile(r"\b(?:non|pas)\s+(?:pr[ée]cis[ée]e?s?|mentionn[ée]e?s?|indiqu[ée]e?s?)\b|\bsuppos[ée]e?s?\b", re.I)


def clean(text: str) -> str:
    """Retire les citations écrites DANS le texte par le modèle (« (Titre, [3]) », « [2] ») : la source est
    gardée à part. Sans ça, le « 3 » de « [3] » et les mots du titre faussaient le contrôle (vu le 09/11).
    Retire aussi les phrases devenues vides (« Ce point est basé sur et. ») et les consignes recopiées."""
    from sourcia.core.text import split_sentences

    t = CITE_PAREN_RE.sub("", text or "")
    t = CITE_RE.sub("", t)
    t = re.sub(r"^\s*[-•*]\s+", "", " ".join(t.split()))
    t = LEAD_RE.sub("", t)
    kept = [LEAD_RE.sub("", x).strip() for x in split_sentences(t)
            if x.strip() and not DANGLING_RE.search(x.strip()) and not ECHO_RE.search(x)]
    kept = [re.sub(r"\s*[,;:]+\s*([.!?]?)$", r"\1", k) for k in kept]      # « …sèches,. » après retrait de « [1, 2] »
    kept = [k[:1].upper() + k[1:] for k in kept if k]
    return " ".join(kept).strip()


def is_hedged(text: str) -> bool:
    """« … inférieur à celui du maïs (non précisé dans le passage) » : le modèle avoue qu'il complète."""
    return bool(HEDGE_RE.search(text or ""))


def clean_choice(c: str) -> str:
    """« {A) Semis direct} », « B) Le maïs », « - C. Juin » → « Semis direct », « Le maïs », « Juin »."""
    c = (c or "").strip().strip("{}[]").strip()
    c = re.sub(r"^(?:[A-Da-d][).:]|[-•*])\s*", "", c)
    return c.strip().strip("{}").strip()


def is_meta(text: str) -> bool:
    """« Le passage [2] montre que… » : décrit le passage au lieu d'en donner l'information."""
    return bool(META_RE.match((text or "").strip()))


def support_all(text: str, passage: str, ignore: frozenset = frozenset()) -> float:
    """Score de la phrase la MOINS soutenue : un point de deux phrases dont la seconde est inventée ne passe pas."""
    from sourcia.core.text import split_sentences

    parts = [x for x in split_sentences(text) if len(tokenize(x)) >= 3] or [text]
    # on contrôle l'AFFIRMATION, pas le cadre : « Le témoignage d'un éleveur a montré que X » → « X »
    return min(support(claim(x), passage, ignore) for x in parts)


def claim(sentence: str) -> str:
    c = FRAME_RE.sub("", sentence.strip())
    return c if len(tokenize(c)) >= 3 else sentence


def best_source(text: str, passages: dict[int, str], cited: int | None, threshold: float,
                ignore: frozenset = frozenset(), fallback: dict[int, str] | None = None) -> tuple[int | None, float, bool]:
    """Le passage qui soutient le texte : celui cité s'il convient, sinon le meilleur des autres passages fournis
    (le petit modèle se trompe souvent de numéro), sinon le meilleur de ``fallback`` (tout le mini-corpus).
    ``ignore`` : mots du sujet, présents partout, qui ne prouvent rien. Renvoie (numéro, score, source corrigée ?)."""
    if is_hedged(text):
        return None, 0.0, False
    if cited in passages:
        sc = support_all(text, passages[cited], ignore)
        if sc >= threshold:
            return cited, sc, False
    for pool in (passages, fallback or {}):
        scored = sorted(((support_all(text, p, ignore), n) for n, p in pool.items() if n != cited), reverse=True)
        if scored and scored[0][0] >= threshold:
            return scored[0][1], scored[0][0], cited is not None
    return None, 0.0, False


# Cultures, fourrages et animaux : si la phrase en nomme un que le passage ne cite pas, c'est un mélange de sources
# (vu le 09/11 : « le sorgho a été testé en Bretagne en 2016 » à partir du passage sur les MÉTEILS de 2016).
ENTITIES = ["sorgho", "mais", "meteil", "luzerne", "trefle", "dactyle", "fetuque", "ray-grass", "ray grass", "prairie",
            "triticale", "pois", "vesce", "feverole", "colza", "ble", "orge", "avoine", "seigle", "tournesol", "soja",
            "betterave", "moha", "millet", "chanvre", "lin", "sainfoin", "lotier", "chicoree", "plantain",
            "vache", "bovin", "ovin", "brebis", "caprin", "chevre", "porc", "porcin", "volaille", "equin", "cheval"]
_ENT_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, ENTITIES), key=len, reverse=True)) + r")s?\b")


def entities(text: str) -> set[str]:
    from sourcia.core.text import normalize

    return {m.replace(" ", "-") for m in _ENT_RE.findall(normalize(text))}


# Mots de liaison ou de style qui ne portent pas l'information (vu le 09/11 avec Gemini, qui reformule plus qu'un 3B :
# « doit être réalisée », « une fois que », « constitue une solution », « nécessite une vigilance particulière »)
GENERIC = {"doit", "doivent", "etre", "fois", "certain", "certaine", "contre", "necessite", "particuliere", "permet",
           "permettent", "solution", "constitue", "efficace", "realisee", "realise", "suffisamment", "important",
           "importante", "gestion", "atteindre", "optent", "opte", "pallier", "lor", "afin", "grace", "notamment",
           "egalement", "ainsi", "faut", "convient", "il", "elle", "cela", "leur", "dont", "tres", "plu", "bien"}
# Synonymes et abréviations ramenés à une forme commune, des deux côtés (phrase ET passage)
CANON = {"secheresse": "sec", "seche": "sec", "seches": "sec", "estival": "ete", "estivale": "ete", "estivaux": "ete",
         "conserve": "maintient", "conserver": "maintient", "maintenir": "maintient", "garde": "maintient",
         "tonne": "t", "hectare": "ha", "matiere": "ms", "implanter": "implant", "implantant": "implant",
         "implante": "implant", "implantee": "implant", "implantation": "implant", "rechauffe": "rechauff",
         "rechauffee": "rechauff", "paturer": "patur", "pature": "patur", "paturee": "patur", "recolte": "recolt",
         "recolter": "recolt", "recoltee": "recolt", "rendement": "produit", "production": "produit",
         "produire": "produit", "meilleur": "meilleur", "superieur": "meilleur", "optimale": "meilleur",
         "condition": "", "demontre": "", "performance": ""}


# Mots de SENS (ordre, comparaison, sens de variation) : ils changent le fait, ils doivent être dans la source
_POL_RE = re.compile(r"\b(avant|apres|inferieure?s?|superieure?s?|hausse|baisse|augment\w*|diminu\w*|"
                     r"plus tot|plus tard|jamais|interdit\w*)\b")


def _polarity(text: str) -> set[str]:
    from sourcia.core.text import normalize

    return {m[:6] for m in _POL_RE.findall(normalize(text))}


def _bag(text: str) -> set[str]:
    out = set()
    for w in tokenize(text):
        w = CANON.get(w, w)
        if w and w not in GENERIC:
            out.add(w)
    return out


def meaning_bag(text: str) -> set[str]:
    """Mots porteurs de sens + chiffres : sert à repérer deux formulations du même fait."""
    return _bag(text) | set(NUM_RE.findall(text or ""))


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _found(w: str, bag: set[str]) -> bool:
    return w in bag or (len(w) >= 7 and any(len(b) >= 7 and b[:6] == w[:6] for b in bag))


def support(sentence: str, passage: str, ignore: frozenset = frozenset()) -> float:
    """Part des mots porteurs de sens de la phrase retrouvés dans le passage. Les mots du SUJET (``ignore``) ne
    comptent pas : « le choix du sorgho fourrager est influencé par… » ne prouve rien parce qu'il cite le sorgho."""
    all_terms = _bag(sentence)
    if not all_terms:
        return 1.0
    s_terms = all_terms - {CANON.get(w, w) for w in ignore}
    if not s_terms:
        return 0.0                                      # la phrase ne dit rien de plus que le sujet
    nums = set(NUM_RE.findall(sentence))
    if nums and not nums <= set(NUM_RE.findall(passage)):
        return 0.0                                      # un chiffre inventé : hallucination classique
    if not entities(sentence) <= entities(passage):
        return 0.0                                      # une culture ou un animal absent du passage
    if not _polarity(sentence) <= _polarity(passage):
        return 0.0                                      # « AVANT le 15 mai » quand la source dit « après »
    p_terms = _bag(passage)
    ratio = sum(_found(w, p_terms) for w in s_terms) / len(s_terms)
    # Phrase ANCRÉE : ses chiffres sont tous dans le passage, ses cultures aussi. Le risque d'invention porte alors
    # sur la tournure, pas sur le fait : on accepte un peu plus de reformulation.
    return min(1.0, ratio + 0.15) if nums else ratio


def _terms(text: str) -> set[str]:
    return {w for w in tokenize(text) if len(w) >= 4}


def _match(word: str, bag: set[str]) -> bool:
    return any(word[:4] == w[:4] for w in bag)


def choice_scores(enonce: str, choix: list[str], explication: str) -> list[float]:
    """Part de chaque proposition reprise par l'explication. Les CHIFFRES comptent (« 70 % », « 9,5 t MS/ha ») :
    avant le 09/11, une proposition purement chiffrée avait 0 et la question était retirée à tort."""
    stem, expl = _terms(enonce), _terms(explication)
    expl_nums = {x.replace(",", ".") for x in NUM_RE.findall(explication)}
    stem_nums = {x.replace(",", ".") for x in NUM_RE.findall(enonce)}
    out = []
    for c in choix:
        words = {w for w in _terms(c) if not _match(w, stem) and not NUM_RE.fullmatch(w)}
        nums = {x.replace(",", ".") for x in NUM_RE.findall(c)} - stem_nums
        total = len(words) + len(nums)
        hit = sum(_match(w, expl) for w in words) + len(nums & expl_nums)
        out.append(hit / total if total else 0.0)
    return out


def check_question(q, passages: dict[int, str], threshold: float, ignore: frozenset = frozenset(),
                   fallback: dict[int, str] | None = None) -> tuple[bool, str | None]:
    """Renvoie (garder ?, remarque). Corrige l'index en place si l'explication en désigne nettement un autre."""
    q.explication = clean(q.explication)
    q.choix = [clean_choice(c) for c in q.choix]
    q.enonce = clean(q.enonce) or q.enonce
    if len({c.lower() for c in q.choix}) != 4 or not all(q.choix):
        return False, "propositions vides ou en double après nettoyage"
    for c in q.choix:                                      # « Sorgho (50%)}, {B) Triticale (40%)… » : 4 choix en un
        if re.search(r"\}\s*,\s*\{|\b[A-D]\)\s", c) or len(c.split()) > 12:
            return False, "propositions mal formées (trop longues, ou plusieurs propositions dans une seule)"
    n, _, moved = best_source(q.explication, passages, q.source, threshold, ignore, fallback)
    if n is None:
        return False, "explication non retrouvée dans les passages"
    text = (passages | (fallback or {}))[n]
    if not entities(q.enonce) <= entities(text):          # « date limite du MÉTEIL » expliquée par un passage SORGHO
        return False, "la question porte sur une culture ou un animal absent du passage qui la justifie"
    note_src = f"source corrigée [{q.source}] → [{n}]" if moved else None
    q.source = n
    scores = choice_scores(q.enonce, q.choix, q.explication)
    best = max(range(4), key=lambda j: scores[j])
    if scores[best] < 0.5:                                  # aucune proposition reprise par l'explication
        return False, "la bonne réponse n'apparaît pas dans l'explication (ex. « Juin » pour « après le 15 mai »)"
    top = [j for j, s in enumerate(scores) if scores[best] - s < 1e-9]
    if len(top) > 1:
        return False, f"ambiguë (l'explication justifie {', '.join(LETTERS[j] for j in top)})"
    if best != q.bonne_reponse and scores[best] - scores[q.bonne_reponse] >= 0.25:
        old = q.bonne_reponse
        q.bonne_reponse = best
        return True, "; ".join(x for x in [note_src, f"réponse corrigée de {LETTERS[old]} en {LETTERS[best]} "
                                           "(cohérence avec l'explication)"] if x)
    return True, note_src


def same_choices(a, b) -> bool:
    return {c.strip().lower() for c in a.choix} == {c.strip().lower() for c in b.choix}
