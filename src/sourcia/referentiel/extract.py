"""Extraction des capacités d'un référentiel à partir de ses PDF (sans modèle : expressions régulières).

Observé sur les référentiels de chlorofil.fr (CAPa MA 2024, bac pro CGEA 2024, BTSA ACS'Agri 2025) :
- les codes : C4.2, « C 6.1. », C5- , CP4 –, CG1.1 - ;
- plusieurs capacités sur une même ligne (« C5.1- … C5.2- … ») et des libellés sur deux lignes ;
- les capacités mères : « Capacité 5 correspondant au bloc de compétences B 5 : … » ;
- une capacité commence TOUJOURS par un verbe à l'infinitif → filtre très efficace contre le bruit
  (tableaux d'épreuves, « oral + », « Candidats en CCF ») ;
- CAPa : un même code a des libellés différents selon le support (ruminants, équins…) → « variantes ».
Le résultat est marqué « extrait automatiquement » : un enseignant le relit avant usage.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from sourcia.referentiel.models import Capacite, Referentiel, normalize_code

CODE_RE = re.compile(r"(?<![\w.’'])(C[PG]?)\s?(\d{1,2})(?:\s?\.\s?(\d{1,2}))?\s*(?:[-–—:.]+\s*)?(?=[A-ZÉÈÊÀÂÎ])")
PARENT_RE = re.compile(r"Capacit[ée]\s+(C[PG]?)?\s?(\d{1,2})\s+correspondant\s+au\s+bloc\s+de\s+comp[ée]tences\s+"
                       r"B\s?\d{1,2}\s*:\s*(.+?)(?=\n\s*\n|\n\s*C\s?\d)", re.S)
TRAILING_NOISE = re.compile(r"\s+(?:E\d+(?:\.\d+)?\b.*|CCF\b.*|Crit[èe]res\s*:.*|\d+\s*$)")
INFINITIVE = re.compile(r"^(?:S[’']|Se\s|D[’'])?[A-ZÉÈÊÀÂÎa-zéèêàâîôûç]+(?:er|ir|re|oir)\b")


STOP_RE = re.compile(r"\s(?:Liste des|Candidats|L[’']examen|Capacit[ée]s?\s(?:évaluées|attestées)|Savoirs|[ÉE]preuve|Modalit[ée]s?|Coeff)\b.*")


def _clean_label(raw: str) -> str:
    s = " ".join(raw.replace("\f", " ").split())
    s = STOP_RE.sub("", s)
    s = TRAILING_NOISE.sub("", s).strip(" -–—:;,.()")
    return s[:240]


def _plausible(label: str) -> bool:
    return len(label.split()) >= 2 and bool(INFINITIVE.match(label))


def capacities_from_text(text: str) -> list[Capacite]:
    text = text.replace("\r", "")
    found: dict[str, Capacite] = {}

    def add(code: str, label: str) -> None:
        if not _plausible(label):
            return
        c = found.get(code)
        if c is None:
            parent = code.rsplit(".", 1)[0] if "." in code else None
            found[code] = Capacite(code=code, libelle=label, parent=parent)
        elif SequenceMatcher(None, c.libelle.lower(), label.lower()).ratio() < 0.7 \
                and label not in c.variantes and not label.lower().startswith(c.libelle.lower()[:30]) and len(c.variantes) < 6:
            c.variantes.append(label)

    for m in PARENT_RE.finditer(text):
        add(normalize_code(f"{m.group(1) or 'C'}{m.group(2)}"), _clean_label(m.group(3)))
    matches = list(CODE_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[m.end():end]
        blank = re.search(r"\n\s*\n", chunk)            # un libellé s'arrête à la ligne vide
        if blank:
            chunk = chunk[: blank.start()]
        code = normalize_code(f"{m.group(1)}{m.group(2)}" + (f".{m.group(3)}" if m.group(3) else ""))
        add(code, _clean_label(chunk))
    # les mères absentes mais déduites des filles
    for c in list(found.values()):
        if c.parent and c.parent not in found:
            found[c.parent] = Capacite(code=c.parent, libelle=f"(capacité {c.parent} : libellé non trouvé)",
                                       statut="a_revoir")
    return sorted(found.values(), key=lambda c: _sort_key(c.code))


def _sort_key(code: str):
    m = re.match(r"([A-Z]+)(\d+)(?:\.(\d+))?", code)
    return (m.group(1), int(m.group(2)), int(m.group(3) or 0)) if m else (code, 0, 0)


def build(rid: str, nom: str, type_: str, files: list[Path], version: str = "", niveau: int | None = None,
          urls: dict[str, str] | None = None) -> Referentiel:
    from sourcia.collect.store import file_sha1
    from sourcia.core.models import Document
    from sourcia.extract.pdf import _pdf_pages

    caps: dict[str, Capacite] = {}
    sources = []
    for f in files:
        f = Path(f)
        pages, _, _ = _pdf_pages(f, 400)
        for c in capacities_from_text("\n".join(pages)):
            if c.code not in caps or caps[c.code].statut == "a_revoir":
                caps[c.code] = c
            elif SequenceMatcher(None, caps[c.code].libelle.lower(), c.libelle.lower()).ratio() < 0.7:
                caps[c.code].variantes = list(dict.fromkeys(caps[c.code].variantes + [c.libelle]))[:6]
        sources.append({"fichier": f.name, "url": (urls or {}).get(f.name, ""), "sha1": file_sha1(f)})
        _ = Document  # (import gardé pour la cohérence des types)
    if not version:
        years = [y for f in files for y in re.findall(r"(20\d\d)", Path(f).name)]
        version = max(years) if years else ""
    return Referentiel(id=rid, nom=nom, type=type_, niveau=niveau, version=version, sources=sources,
                       capacites=sorted(caps.values(), key=lambda c: _sort_key(c.code)))
