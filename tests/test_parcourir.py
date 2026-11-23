"""Parcourir le catalogue depuis un dossier : une liste filtrable au lieu d'une case de recherche vide."""
from __future__ import annotations

import pytest

from conftest import ROOT


# ---------------------------------------------------------------------- thèmes des fiches
def test_themes_ignore_the_word_mais_and_word_pieces():
    """Vu le 23/11 : 121 documents classés « maïs » à cause de la conjonction « mais », « foin » dans « sainfoin »."""
    from sourcia.qualify.pipeline import THEMES_VOCAB
    from sourcia.qualify.rules import themes_of

    assert themes_of("Les modèles s'améliorent mais gardent une part d'incertitude. Le sainfoin pousse.",
                     [], THEMES_VOCAB) == []
    assert themes_of("Le MAÏS ensilage et la production fourragère ; les foins de prairies.", [], THEMES_VOCAB) == \
        ["ensilage", "foin", "fourrage", "maïs", "prairie"]
    assert themes_of("Texte sans thème.", ["sorgho"], THEMES_VOCAB) == ["sorgho"]       # mots-clés de la source gardés


def test_themes_can_be_recomputed_without_the_model(demo_ctx, capsys, monkeypatch):
    from sourcia.cli import main

    doc = next(d for d in demo_ctx.store.canonical() if demo_ctx.qualifier.get(d.id))
    fiche = demo_ctx.qualifier.get(doc.id)
    fiche.themes = ["maïs", "thème faux"]
    organisme = fiche.organisme.value
    demo_ctx.qualifier.save()
    demo_ctx.store.save()                                                    # la commande relit les fichiers
    cfg = demo_ctx.settings
    path = ROOT / "config" / "test.yaml"
    monkeypatch.setenv("SOURCIA_DATA_DIR", str(cfg.data))
    main(["-c", str(path), "qualify", "--themes"])
    assert "Thèmes recalculés" in capsys.readouterr().out
    from sourcia.container import Context
    again = Context(cfg).qualifier.get(doc.id)
    assert "thème faux" not in again.themes and again.organisme.value == organisme     # le reste de la fiche gardé
