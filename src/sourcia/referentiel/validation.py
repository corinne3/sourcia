"""Validation humaine (enseignant) à deux niveaux :

1. le RÉFÉRENTIEL extrait : une fois par diplôme et par version → tableau CSV « valide / corriger » ;
2. le RATTACHEMENT d'une formation (séquence → capacité) : proposé par l'IA, validé par l'enseignant ;
   un rattachement validé est mémorisé et réutilisé (« déjà validé ») pour les formations suivantes.
Les tableaux s'ouvrent dans Excel (séparateur « ; », encodage UTF-8 avec BOM).
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from sourcia.core.text import normalize
from sourcia.referentiel.models import Referentiel, normalize_code

def _read_csv(path: Path) -> list[dict]:
    """CSV rempli dans Excel : UTF-8, ou Windows-1252 (« CSV (séparateur : point-virgule) » d'Excel en français)."""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    delim = ";" if text.split("\n", 1)[0].count(";") >= text.split("\n", 1)[0].count(",") else ","
    return list(csv.DictReader(text.splitlines(), delimiter=delim))


OUI = ("oui", "o", "yes", "y", "x", "ok", "1", "vrai", "valide")


# ---------------------------------------------------------------------------- 1. le référentiel
def export_referentiel_csv(ref: Referentiel, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["code", "libelle_extrait", "variantes", "statut", "valide (oui/non)", "libelle_corrige", "commentaire"])
        for c in ref.capacites:
            w.writerow([c.code, c.libelle, " | ".join(c.variantes), c.statut, "", "", c.commentaire])
    return out


def import_referentiel_csv(ref: Referentiel, path: Path, valideur: str) -> tuple[Referentiel, dict]:
    stats = {"valides": 0, "corriges": 0, "rejetes": 0}
    rows = _read_csv(path)
    for r in rows:
        c = ref.get(r.get("code", ""))
        if c is None:
            continue
        ok = (r.get("valide (oui/non)") or "").strip().lower()
        if (r.get("libelle_corrige") or "").strip():
            c.libelle, c.statut = r["libelle_corrige"].strip(), "valide"
            stats["corriges"] += 1
        elif ok in OUI:
            c.statut = "valide"
            stats["valides"] += 1
        elif ok:
            c.statut = "a_revoir"
            stats["rejetes"] += 1
        c.commentaire = (r.get("commentaire") or c.commentaire).strip()
    if all(c.statut == "valide" for c in ref.capacites):
        ref.statut, ref.valide_par = "valide", f"{valideur} ({date.today():%d/%m/%Y})"
    return ref, stats


# ---------------------------------------------------------------------------- 2. les rattachements
class Rattachements:
    """Mémoire des rattachements validés : ``data/rattachements_valides.jsonl``."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.rows: list[dict] = []
        if self.path.exists():
            self.rows = [json.loads(l) for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    @staticmethod
    def key(diplome: str, version: str, code: str, titre: str) -> tuple:
        return (diplome, str(version), normalize_code(code), normalize(titre))

    def is_validated(self, diplome, version, code, titre) -> dict | None:
        k = self.key(diplome, version, code, titre)
        return next((r for r in self.rows if self.key(r["diplome"], r["version"], r["code"], r["sequence"]) == k), None)

    def add(self, diplome, version, code, titre, valideur, commentaire="") -> None:
        if not self.is_validated(diplome, version, code, titre):
            self.rows.append({"diplome": diplome, "version": str(version), "code": normalize_code(code), "sequence": titre,
                              "valide_par": valideur, "date": f"{date.today():%Y-%m-%d}", "commentaire": commentaire})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.rows), encoding="utf-8")


def export_rattachements_csv(form, out: Path) -> Path:
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["n", "sequence", "objectif", "code_propose", "libelle_capacite", "statut",
                    "valide (oui/non)", "code_corrige", "commentaire"])
        for i, s in enumerate(form.sequences, 1):
            w.writerow([i, s.titre, s.objectif, s.capacite or "", s.capacite_libelle or "", s.capacite_statut, "", "", ""])
    return out


def import_rattachements_csv(form, path: Path, store: Rattachements, ref: Referentiel | None, valideur: str) -> dict:
    stats = {"valides": 0, "corriges": 0, "refuses": 0, "codes_inconnus": []}
    rows = _read_csv(path)
    for r in rows:
        try:
            s = form.sequences[int(r["n"]) - 1]
        except (KeyError, ValueError, IndexError):
            continue
        ok = (r.get("valide (oui/non)") or "").strip().lower()
        new = (r.get("code_corrige") or "").strip()
        if new:
            cap = ref.get(new) if ref else None
            if ref and cap is None:
                stats["codes_inconnus"].append(new)
                continue
            s.capacite, s.capacite_libelle = normalize_code(new), cap.libelle if cap else s.capacite_libelle
            ok, stats["corriges"] = "oui", stats["corriges"] + 1
        if ok in OUI and s.capacite:
            s.capacite_statut = "valide"
            stats["valides"] += 1
            if ref:
                store.add(ref.id, ref.version, s.capacite, s.titre, valideur, r.get("commentaire", ""))
        elif ok:
            s.capacite_statut = "refuse"
            stats["refuses"] += 1
    store.save()
    return stats
