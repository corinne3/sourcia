"""Évaluation : l'outil fait-il mieux que l'existant ? Le métier fournit la référence.

1. TROUVER : ``data/eval/demandes.jsonl``, une demande de formateur par ligne :
   {"id": "d1", "demande": "...", "filtres": {"annee_min": 2015}, "attendus": ["url ou morceau de titre", ...]}
   → rappel@N (part des documents attendus retrouvés), rang moyen du premier attendu (MRR),
     comparé à des références : titres seuls (≈ moteur par mots-clés), BM25, sens seul, hybride, sélection.
2. QUALIFIER : ``data/eval/qualification_reference.csv``, des documents qualifiés à la main
   (colonnes de la fiche ; « l'Excel » du métier) → exactitude champ par champ, couverture, VALEURS FAUSSES.
   Une valeur fausse est pire qu'une valeur absente : c'est l'indicateur à surveiller.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from sourcia.core.models import Fiche
from sourcia.core.text import normalize, tokenize
from sourcia.select.funnel import Filters


def _matches(doc, expected: str) -> bool:
    e = normalize(expected.strip())
    return e in (doc.id, normalize(doc.url)) or (len(e) > 8 and e in normalize(doc.title or ""))


def load_requests(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def eval_find(ctx, path: Path, n: int = 50, modes=("titres", "bm25", "dense", "hybrid", "selection"),
              llm_top: int = 0) -> dict:
    reqs = load_requests(path)
    out = {"demandes": len(reqs), "n": n, "modes": {}}
    for mode in modes:
        if mode == "dense" and ctx.index.vectors is None:
            continue
        recalls, rr, rows = [], [], []
        for r in reqs:
            if mode == "selection":
                f = Filters(**r.get("filtres", {}))
                docs = [c.document for c in ctx.selector.select(r["demande"], f, n=n, llm_top=llm_top)]
            else:
                hits = (_title_search(ctx, r["demande"], n) if mode == "titres"
                        else ctx.index.search(r["demande"], k=n, mode=mode))
                docs = [ctx.store.get(h.doc_id) for h in hits if ctx.store.get(h.doc_id)]
            exp = r.get("attendus", [])
            found = [next((i for i, d in enumerate(docs) if _matches(d, e)), None) for e in exp]
            hit = [i for i in found if i is not None]
            recalls.append(len(hit) / len(exp) if exp else 0.0)
            rr.append(1 / (min(hit) + 1) if hit else 0.0)
            rows.append({"id": r.get("id"), "rappel": round(recalls[-1], 3), "rangs": [None if i is None else i + 1 for i in found]})
        out["modes"][mode] = {"rappel@N": round(sum(recalls) / max(1, len(recalls)), 3),
                              "MRR": round(sum(rr) / max(1, len(rr)), 3), "detail": rows}
    return out


def _title_search(ctx, query: str, n: int):
    """Référence « moteur par mots-clés » : BM25 sur les seuls titres et mots-clés."""
    from sourcia.search.bm25 import BM25
    from sourcia.search.index import DocHit

    docs = list(ctx.store)
    bm = BM25().fit([d.id for d in docs], [f"{d.title} {' '.join(d.keywords)}" for d in docs])
    return [DocHit(doc_id=i, score=s, passage="", page=0, ranks={}) for i, s in bm.search(query, n) if s > 0]


def _same(field: str, got, ref: str) -> bool:
    ref = ref.strip()
    if field in ("annee", "annee_publication", "modalites", "repetitions"):
        try:
            return int(float(ref)) == int(got)
        except (TypeError, ValueError):
            return False
    if field == "chiffrage_economique":
        return (normalize(ref) in ("oui", "true", "vrai", "1")) == bool(got)
    if field == "type":
        return normalize(ref).replace(" ", "_").replace("'", "_") == normalize(str(got))
    a, b = set(tokenize(str(got))), set(tokenize(ref))
    return bool(a and b) and len(a & b) / len(b) >= 0.5


def eval_qualify(ctx, path: Path, use_llm: bool = False) -> dict:
    """Compare les fiches automatiques à la référence humaine."""
    with open(path, encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        ref_rows = list(csv.DictReader(fh, dialect=csv.Sniffer().sniff(sample, delimiters=",;\t")))
    stats = {f: {"reference": 0, "juste": 0, "fausse": 0, "absente": 0} for f in Fiche.FIELDS}
    n_docs, details = 0, []
    for row in ref_rows:
        doc = ctx.store.get(row.get("document_id", "")) or next(
            (d for d in ctx.store if (row.get("url") and d.url == row.get("url"))
             or (row.get("fichier") and d.local_path and Path(d.local_path).stem == Path(row["fichier"]).stem)), None)
        if doc is None:
            continue
        fiche = ctx.qualifier.qualify(doc, use_llm=use_llm, force=True)
        if fiche is None:
            continue
        n_docs += 1
        for f in Fiche.FIELDS:
            ref = (row.get(f) or "").strip()
            if not ref:
                continue
            s = stats[f]
            s["reference"] += 1
            got = fiche.get(f)
            if got is None:
                s["absente"] += 1
            elif _same(f, got, ref):
                s["juste"] += 1
            else:
                s["fausse"] += 1
                details.append({"document": doc.id, "champ": f, "attendu": ref, "obtenu": got,
                                "preuve": getattr(fiche, f).evidence})
    ctx.qualifier.save()
    for s in stats.values():
        r = s["reference"] or 1
        s["exactitude"] = round(s["juste"] / r, 3)
        s["taux_valeurs_fausses"] = round(s["fausse"] / r, 3)
    return {"documents": n_docs, "passe_modele": use_llm, "champs": stats, "erreurs": details[:50]}


def qualification_template(ctx, out: Path, n: int = 40) -> Path:
    """Prépare le tableau à remplir par le métier (« l'Excel ») sur un échantillon de documents."""
    docs = [d for d in ctx.store if d.status in ("extracted", "qualified")][:n]
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["document_id", "url", "titre", *Fiche.FIELDS, "commentaire"])
        for d in docs:
            w.writerow([d.id, d.url, d.title] + [""] * (len(Fiche.FIELDS) + 1))
    return out
