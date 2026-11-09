"""Régions et départements de France métropolitaine (découpage 2016) : pour l'alerte « contexte éloigné ».

On cherche la région d'un lieu à partir de son nom, d'un département cité ou d'un numéro « (49) »."""
from __future__ import annotations

import re

from sourcia.core.text import normalize

REGIONS: dict[str, list[tuple[str, str]]] = {
    "Auvergne-Rhône-Alpes": [("01", "Ain"), ("03", "Allier"), ("07", "Ardèche"), ("15", "Cantal"), ("26", "Drôme"),
                             ("38", "Isère"), ("42", "Loire"), ("43", "Haute-Loire"), ("63", "Puy-de-Dôme"), ("69", "Rhône"),
                             ("73", "Savoie"), ("74", "Haute-Savoie")],
    "Bourgogne-Franche-Comté": [("21", "Côte-d'Or"), ("25", "Doubs"), ("39", "Jura"), ("58", "Nièvre"), ("70", "Haute-Saône"),
                                ("71", "Saône-et-Loire"), ("89", "Yonne"), ("90", "Territoire de Belfort")],
    "Bretagne": [("22", "Côtes-d'Armor"), ("29", "Finistère"), ("35", "Ille-et-Vilaine"), ("56", "Morbihan")],
    "Centre-Val de Loire": [("18", "Cher"), ("28", "Eure-et-Loir"), ("36", "Indre"), ("37", "Indre-et-Loire"),
                            ("41", "Loir-et-Cher"), ("45", "Loiret")],
    "Corse": [("2A", "Corse-du-Sud"), ("2B", "Haute-Corse")],
    "Grand Est": [("08", "Ardennes"), ("10", "Aube"), ("51", "Marne"), ("52", "Haute-Marne"), ("54", "Meurthe-et-Moselle"),
                  ("55", "Meuse"), ("57", "Moselle"), ("67", "Bas-Rhin"), ("68", "Haut-Rhin"), ("88", "Vosges")],
    "Hauts-de-France": [("02", "Aisne"), ("59", "Nord"), ("60", "Oise"), ("62", "Pas-de-Calais"), ("80", "Somme")],
    "Île-de-France": [("75", "Paris"), ("77", "Seine-et-Marne"), ("78", "Yvelines"), ("91", "Essonne"), ("92", "Hauts-de-Seine"),
                      ("93", "Seine-Saint-Denis"), ("94", "Val-de-Marne"), ("95", "Val-d'Oise")],
    "Normandie": [("14", "Calvados"), ("27", "Eure"), ("50", "Manche"), ("61", "Orne"), ("76", "Seine-Maritime")],
    "Nouvelle-Aquitaine": [("16", "Charente"), ("17", "Charente-Maritime"), ("19", "Corrèze"), ("23", "Creuse"),
                           ("24", "Dordogne"), ("33", "Gironde"), ("40", "Landes"), ("47", "Lot-et-Garonne"),
                           ("64", "Pyrénées-Atlantiques"), ("79", "Deux-Sèvres"), ("86", "Vienne"), ("87", "Haute-Vienne")],
    "Occitanie": [("09", "Ariège"), ("11", "Aude"), ("12", "Aveyron"), ("30", "Gard"), ("31", "Haute-Garonne"), ("32", "Gers"),
                  ("34", "Hérault"), ("46", "Lot"), ("48", "Lozère"), ("65", "Hautes-Pyrénées"), ("66", "Pyrénées-Orientales"),
                  ("81", "Tarn"), ("82", "Tarn-et-Garonne")],
    "Pays de la Loire": [("44", "Loire-Atlantique"), ("49", "Maine-et-Loire"), ("53", "Mayenne"), ("72", "Sarthe"),
                         ("85", "Vendée")],
    "Provence-Alpes-Côte d'Azur": [("04", "Alpes-de-Haute-Provence"), ("05", "Hautes-Alpes"), ("06", "Alpes-Maritimes"),
                                   ("13", "Bouches-du-Rhône"), ("83", "Var"), ("84", "Vaucluse")],
}
ALIASES = {"paca": "Provence-Alpes-Côte d'Azur", "aura": "Auvergne-Rhône-Alpes", "idf": "Île-de-France",
           "bfc": "Bourgogne-Franche-Comté", "cvl": "Centre-Val de Loire"}


def _n(s: str) -> str:
    """Minuscules, sans accents, ponctuation → espaces (« (Saône-et-Loire), » → « saone et loire »)."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalize(s)).split())


COUNTRIES = {"belgique": "Belgique", "wallonie": "Belgique", "flandre": "Belgique", "suisse": "Suisse", "vaud": "Suisse",
             "fribourg": "Suisse", "luxembourg": "Luxembourg", "espagne": "Espagne", "italie": "Italie",
             "allemagne": "Allemagne", "quebec": "Canada", "canada": "Canada"}
_DEPTS = sorted(((num, name, r) for r, ds in REGIONS.items() for num, name in ds), key=lambda x: -len(x[1]))


def region_of(text: str) -> str | None:
    """Région citée ou déduite d'un département (nom ou numéro entre parenthèses) ; pays si hors de France.
    Les noms les plus LONGS d'abord : « Saône-et-Loire » ne doit pas être pris pour « Loire » (vu le 09/11)."""
    if not text:
        return None
    t = f" {_n(text)} "
    for r in sorted(REGIONS, key=len, reverse=True):                  # « Pays de la Loire » avant « Loire »
        if f" {_n(r)} " in t:
            return r
    for alias, r in ALIASES.items():
        if f" {alias} " in t:
            return r
    for num, name, r in _DEPTS:
        if f" {_n(name)} " in t:
            return r
    for num, name, r in _DEPTS:
        if re.search(rf"\({num}\)", text):
            return r
    for k, country in COUNTRIES.items():
        if f" {k} " in t:
            return country
    return None


def canonical_region(name: str | None) -> str | None:
    return region_of(name) if name else None
