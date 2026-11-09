import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def settings(tmp_path):
    from sourcia.config import load_settings

    s = load_settings(ROOT / "config" / "test.yaml")
    s.data_dir = str(tmp_path / "data")
    return s


@pytest.fixture
def ctx(settings):
    from sourcia.container import Context

    return Context(settings)


@pytest.fixture
def demo_ctx(ctx):
    """Contexte rempli avec les exemples fictifs : collecte, extraction, qualification (règles), index."""
    from sourcia.collect.catalog import read_rows
    from sourcia.collect.local import scan_folder
    from sourcia.extract.pdf import extract
    from sourcia.search.index import SearchIndex

    samples = ROOT / "data" / "samples"
    meta = {r["fichier"]: r for r in read_rows(samples / "catalogue.csv")}
    for d in scan_folder(samples / "documents", source="exemple", private=False):
        m = meta[Path(d.local_path).name]
        d.source, d.title, d.private = m["source"], m["titre"], m["prive"] == "oui"
        ctx.store.add(d)
    for d in ctx.store.canonical():
        extract(d, ctx.text_dir, 40)
        ctx.qualifier.qualify(d)
    SearchIndex(ctx.settings, ctx.embedder).build(ctx.store.canonical())
    return ctx


def doc_by_file(ctx, name):
    return next(d for d in ctx.store if Path(d.local_path).name == name)
