"""Ligne de commande SourcIA : une commande par étape, pour tester module par module.

Ordre normal :  add-site / add-folder / import-catalog  →  download  →  extract  →  qualify  →  index
                →  search / select  →  (eval)
Puis (M7) :     ``sourcia formation``  (support de formation à partir de la dernière sélection exportée)
Raccourci :     ``sourcia demo``  (exemples fictifs, tout le pipeline en une commande, sans Internet)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from sourcia import BUILD

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------- utilitaires
def _ctx(args):
    from sourcia.config import load_settings
    from sourcia.container import Context

    return Context(load_settings(args.config))


def _print_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _bar(i: int, n: int, label: str = "") -> None:
    if sys.stdout.isatty():
        print(f"\r  {i}/{n} {label[:60]:<60}", end="", flush=True)


def _load_cloud_keys(path: Path | None = None) -> None:
    """Lit les clés cloud du fichier .env (GEMINI_API_KEY…). Une variable déjà définie n'est jamais écrasée."""
    path = path or REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        key, sep, value = line.strip().partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if sep and value and not key.startswith("#") and key.startswith(("GEMINI_", "GOOGLE_", "AZURE_", "OPENAI_", "MISTRAL_")):
            os.environ.setdefault(key, value)


def _filters(args):
    from sourcia.select.funnel import Filters

    return Filters(annee_min=args.annee_min, annee_max=args.annee_max,
                   types=[t for t in (args.types or "").split(",") if t],
                   sources=[s for s in (args.sources or "").split(",") if s],
                   region=args.region, strict=args.strict)


# ---------------------------------------------------------------------------- commandes
def cmd_doctor(args) -> None:
    ctx = _ctx(args)
    s = ctx.settings
    print(f"SourcIA {BUILD} · configuration « {s.name} » (empreinte {s.fingerprint})")
    print(f"  données      : {s.data}")
    print(f"  modèle       : {s.llm.provider} / {s.llm.model}")
    print(f"  embeddings   : {s.embedder.kind} / {s.embedder.model if s.embedder.kind != 'hashing' else s.embedder.dim}")
    print(f"  reranker     : {s.search.reranker}")
    for mod, why in [("pymupdf", "lecture PDF rapide"), ("pypdf", "lecture PDF de repli"),
                     ("sentence_transformers", "embeddings sémantiques"), ("fastapi", "interface web / API"),
                     ("mcp", "serveur MCP"), ("litellm", "modèles cloud")]:
        try:
            __import__(mod)
            print(f"  ✅ {mod:<22} {why}")
        except ImportError:
            print(f"  ⚪ {mod:<22} absent ({why})")
    if s.llm.provider == "ollama":
        from sourcia.llm.ollama import OllamaClient

        try:
            models = OllamaClient(base_url=s.llm.base_url).list_models()
            ok = any(m.startswith(s.llm.model) for m in models)
            print(f"  {'✅' if ok else '⚠️ '} Ollama joignable ; modèle {s.llm.model} {'présent' if ok else 'ABSENT : ollama pull ' + s.llm.model}")
        except Exception as exc:
            print(f"  ⚠️  Ollama injoignable ({type(exc).__name__}) : la passe « modèle » échouera, les règles marchent")
    elif s.llm.provider == "litellm":
        key = "GEMINI_API_KEY" if s.llm.model.startswith("gemini") else None
        if key:
            print(f"  {'✅' if os.environ.get(key) else '❌'} clé {key} {'trouvée' if os.environ.get(key) else 'absente du fichier .env'}")
    st = ctx.store.stats()
    print(f"  documents    : {st}")
    print(f"  fiches       : {len(ctx.qualifier.fiches)}")
    from sourcia.search.index import SearchIndex

    idx = SearchIndex(ctx.settings).dir / "chunks.jsonl"
    print(f"  index        : {'présent' if idx.exists() else 'absent (sourcia index)'} ({idx.parent.name})")


def cmd_add_site(args) -> None:
    from sourcia.collect.web import WebCollector

    ctx = _ctx(args)
    if args.no_download:
        ctx.settings.collect.download_pdfs = False
    if args.max_pages:
        ctx.settings.collect.max_pages_per_site = args.max_pages
    wc = WebCollector(ctx.settings)
    print(f"Exploration de {args.url} (politesse : {ctx.settings.collect.delay_s} s entre deux requêtes, robots.txt respecté)…")
    docs, rep = wc.crawl(args.url, source=args.source, include=args.include, medias=args.medias)
    new = sum(ctx.store.add(d) for d in docs)
    ctx.store.save()
    print(f"  pages visitées : {rep.pages_visited} · PDF trouvés : {rep.pdfs_found} · nouveaux : {new}"
          f" · vidéos, photos, données : {rep.medias_found}"
          f" · bloqués par robots.txt : {rep.blocked_by_robots} · erreurs : {len(rep.errors)}")
    for e in rep.errors[:5]:
        print(f"    ⚠️ {e}")
    if docs and ctx.settings.collect.download_pdfs and not args.no_download:
        print("  Étape suivante : sourcia download")


def cmd_add_folder(args) -> None:
    from sourcia.collect.local import scan_folder

    ctx = _ctx(args)
    docs = scan_folder(Path(args.folder), source=args.source, private=not args.public)
    new = sum(ctx.store.add(d) for d in docs)
    ctx.store.save()
    print(f"{len(docs)} fichiers trouvés, {new} nouveaux ({'publics' if args.public else 'PRIVÉS : jamais envoyés à un modèle en ligne'}).")


def cmd_import_catalog(args) -> None:
    from sourcia.collect.catalog import import_catalog

    ctx = _ctx(args)
    mapping = dict(kv.split("=", 1) for kv in (args.map or "").split(",") if "=" in kv)
    docs, skipped = import_catalog(Path(args.file), args.source, mapping)
    new = sum(ctx.store.add(d) for d in docs)
    ctx.store.save()
    print(f"{len(docs)} documents lus ({skipped} lignes sans adresse ignorées), {new} nouveaux.")


def cmd_download(args) -> None:
    from sourcia.collect.web import WebCollector

    ctx = _ctx(args)
    wc = WebCollector(ctx.settings)
    todo = [d for d in ctx.store if d.kind == "pdf" and (d.status == "listed" or (args.retry and d.status == "error"))]
    if args.limit:
        todo = todo[: args.limit]
    ok = 0
    for i, d in enumerate(todo, 1):
        _bar(i, len(todo), d.title)
        wc.download(d, ctx.pdf_dir)
        ok += d.status == "downloaded"
        if i % 20 == 0:
            ctx.store.save()
    ctx.store.save()
    print(f"\n{ok}/{len(todo)} PDF téléchargés. Doublons de contenu : {len(ctx.store.duplicates())}.")
    for d in todo:                                     # dire POURQUOI un téléchargement a échoué
        if d.status == "error":
            print(f"  ✗ {d.error}  ←  {d.url[:110]}")


def cmd_extract(args) -> None:
    from sourcia.extract.pdf import extract

    ctx = _ctx(args)
    todo = [d for d in ctx.store.canonical() if (d.status == "downloaded" or args.force and d.status != "listed")
            or (d.kind in ("video", "image", "audio", "donnees") and d.status == "listed")]   # ressources : métadonnées
    ok = scanned = 0
    for i, d in enumerate(todo, 1):
        _bar(i, len(todo), d.title)
        try:
            r = extract(d, ctx.text_dir, ctx.settings.extract.max_pages)
            ok += 1
            scanned += r["scanned"]
        except Exception as exc:
            d.status, d.error = "error", f"extraction : {type(exc).__name__} {exc}"[:200]
    ctx.store.save()
    print(f"\n{ok}/{len(todo)} documents extraits ; {scanned} sans texte lisible (scannés).")


def cmd_qualify(args) -> None:
    ctx = _ctx(args)
    todo = [d for d in ctx.store.canonical() if d.status in ("extracted", "qualified")]
    if args.doc:
        todo = [d for d in todo if d.id in args.doc]
    if args.limit:
        todo = todo[: args.limit]
    t0 = time.perf_counter()
    n = 0
    for i, d in enumerate(todo, 1):
        _bar(i, len(todo), d.title)
        if ctx.qualifier.qualify(d, use_llm=args.llm, force=args.force):
            n += 1
        if i % 20 == 0:
            ctx.qualifier.save()
            ctx.store.save()
    ctx.qualifier.save()
    ctx.store.save()
    dt = time.perf_counter() - t0
    print(f"\n{n} fiches ({'règles + modèle' if args.llm else 'règles seules'}) en {dt:.1f} s"
          f" ({dt / max(1, n):.2f} s par document).")
    if args.doc and n:
        for d in todo:
            cmd_fiche_print(ctx, d.id)


def cmd_fiche_print(ctx, doc_id: str) -> None:
    from sourcia.core.models import Fiche

    doc = ctx.store.get(doc_id)
    fi = ctx.qualifier.get(doc_id)
    if not doc or not fi:
        print(f"Pas de fiche pour {doc_id}.")
        return
    print(f"\n📄 {doc.title}  [{doc.id}]  {doc.url}")
    print(f"   passes : {', '.join(fi.passes)} · coût : {fi.cout_s} s")
    for name in Fiche.FIELDS:
        f = getattr(fi, name)
        val = "—" if f.value is None else f.value
        print(f"   {name:<24} {str(val)[:60]:<60} conf. {f.confidence:.2f} ({f.method})")
        if f.evidence and args_show_evidence:
            print(f"   {'':<24} ↳ « {f.evidence[:160]} »")
    if fi.themes:
        print(f"   thèmes : {', '.join(fi.themes)}")
    if fi.resume:
        print(f"   résumé : {fi.resume}")
    for a in fi.alertes:
        print(f"   ⚠️ {a}")


args_show_evidence = True


def cmd_fiche(args) -> None:
    ctx = _ctx(args)
    q = args.doc_id.lower()
    ids = [d.id for d in ctx.store if d.id.startswith(args.doc_id) or q in (d.title or "").lower()
           or (d.local_path and q in Path(d.local_path).name.lower())]
    if not ids:
        sys.exit(f"Aucun document ne correspond à « {args.doc_id} ».")
    for i in ids[:5]:
        cmd_fiche_print(ctx, i)


def cmd_index(args) -> None:
    ctx = _ctx(args)
    from sourcia.search.index import SearchIndex

    idx = SearchIndex(ctx.settings, ctx.embedder if not args.no_dense else None)
    docs = [d for d in ctx.store.canonical() if d.status != "error"]
    t0 = time.perf_counter()
    r = idx.build(docs)
    print(f"Index construit en {time.perf_counter() - t0:.1f} s : {r}")


def cmd_search(args) -> None:
    ctx = _ctx(args)
    hits = ctx.index.search(args.query, k=args.k, mode=args.mode)
    if not hits:
        print("Aucun résultat (index vide ? lancer sourcia index).")
    for i, h in enumerate(hits, 1):
        d = ctx.store.get(h.doc_id)
        print(f"{i:>3}. {d.title[:80] if d else h.doc_id}  ({d.source if d else ''})  rangs={h.ranks}")
        print(f"      p.{h.page} « {h.passage[:150]} »")


def cmd_select(args) -> None:
    ctx = _ctx(args)
    t0 = time.perf_counter()
    structured = None
    if getattr(args, "demande_fichier", None) or not args.demande:
        from sourcia.select.funnel import select_demande

        structured = _demande_from_args(args)
        args.demande = structured.sujet
        sel = select_demande(ctx.selector, structured, llm_top=args.llm_top)
    else:
        sel = ctx.selector.select(args.demande, _filters(args), n=args.n, llm_top=args.llm_top)
    ctx.qualifier.save()
    ctx.store.save()
    print(f"{len(sel)} documents sélectionnés en {time.perf_counter() - t0:.1f} s pour : {args.demande}\n")
    for i, c in enumerate(sel, 1):
        print(f"{i:>3}. [{c.score:.2f}] {c.document.title[:90]}  ({c.document.source})")
        print(f"      {c.justification[:400]}")
    if args.export:
        from sourcia.export.exporters import export

        paths = export(sel, args.demande, ctx.settings.path("exports", ".keep").parent, args.export.split(","),
                       structured=structured.model_dump() if structured else None)
        print("\nFichiers écrits :")
        for p in paths:
            print(f"  {p}")


def cmd_stats(args) -> None:
    from collections import Counter

    ctx = _ctx(args)
    fiches = list(ctx.qualifier.fiches.values())
    out = {"documents": ctx.store.stats(), "fiches": len(fiches)}
    if fiches:
        from sourcia.core.models import Fiche

        out["champs_remplis"] = {f: sum(fi.get(f) is not None for fi in fiches) for f in Fiche.FIELDS}
        out["types"] = Counter(str(fi.get("type")) for fi in fiches)
        out["alertes"] = Counter(a.split(" :")[0].split("(")[0].strip() for fi in fiches for a in fi.alertes).most_common(8)
        out["cout_moyen_s"] = round(sum(fi.cout_s for fi in fiches) / len(fiches), 3)
    _print_json(out)


def _eval_file(args, name: str) -> Path:
    """Fichier fourni, sinon data/eval/<name> (le vrai jeu du métier), sinon l'exemple fictif."""
    if args.file:
        return Path(args.file)
    real = REPO_ROOT / "data" / "eval" / name
    return real if real.exists() else REPO_ROOT / "data" / "samples" / "eval" / name


def cmd_eval(args) -> None:
    from sourcia.evaluation import bench

    ctx = _ctx(args)
    if args.what == "trouver":
        r = bench.eval_find(ctx, _eval_file(args, "demandes.jsonl"), n=args.n, llm_top=args.llm_top)
        print(f"{r['demandes']} demandes, {r['n']} documents proposés par demande\n")
        print(f"{'méthode':<12} {'rappel@N':>9} {'MRR':>6}")
        for m, v in r["modes"].items():
            print(f"{m:<12} {v['rappel@N']:>9.2f} {v['MRR']:>6.2f}")
    elif args.what == "qualifier":
        r = bench.eval_qualify(ctx, _eval_file(args, "qualification_reference.csv"), use_llm=args.llm)
        print(f"{r['documents']} documents comparés à la référence humaine ({'règles + modèle' if args.llm else 'règles seules'})\n")
        print(f"{'champ':<24} {'réf.':>5} {'justes':>7} {'FAUSSES':>8} {'absentes':>9} {'exactitude':>11}")
        for f, s in r["champs"].items():
            ex = f"{s['exactitude']:.2f}" if s["reference"] else "—"          # rien à comparer dans la référence
            print(f"{f:<24} {s['reference']:>5} {s['juste']:>7} {s['fausse']:>8} {s['absente']:>9} {ex:>11}")
        for e in r["erreurs"][:10]:
            print(f"  ✗ {e['document']} {e['champ']} : attendu « {e['attendu']} », obtenu « {e['obtenu']} »")
    else:
        p = bench.qualification_template(ctx, Path(args.file or REPO_ROOT / "data/eval/a_remplir_par_le_metier.csv"), n=args.n)
        print(f"Tableau à remplir écrit : {p}")
        return
    if args.out:
        Path(args.out).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"\nRésultats complets : {args.out}")


def cmd_demo(args) -> None:
    """Tout le pipeline sur les exemples FICTIFS de data/samples, sans Internet."""
    from sourcia.collect.catalog import read_rows
    from sourcia.collect.local import scan_folder
    from sourcia.extract.pdf import extract
    from sourcia.search.index import SearchIndex

    ctx = _ctx(args)
    samples = REPO_ROOT / "data" / "samples"
    meta = {r["fichier"]: r for r in read_rows(samples / "catalogue.csv")} if (samples / "catalogue.csv").exists() else {}
    docs = scan_folder(samples / "documents", source="exemple", private=False)
    for d in docs:
        m = meta.get(Path(d.local_path).name, {})
        d.source = m.get("source") or d.source
        d.title = m.get("titre") or d.title
        d.private = str(m.get("prive", "")).lower() in ("oui", "true", "1")
        ctx.store.add(d)
    ctx.store.save()
    print(f"1. Collecte    : {len(docs)} documents d'exemple (fictifs)")
    for d in ctx.store.canonical():
        if d.status == "downloaded":
            extract(d, ctx.text_dir, ctx.settings.extract.max_pages)
    print("2. Extraction  : ok")
    for d in ctx.store.canonical():
        ctx.qualifier.qualify(d, use_llm=False)
    ctx.qualifier.save()
    ctx.store.save()
    print(f"3. Qualification (règles) : {len(ctx.qualifier.fiches)} fiches")
    idx = SearchIndex(ctx.settings, ctx.embedder)
    print(f"4. Index       : {idx.build(ctx.store.canonical())}")
    ctx.__dict__.pop("index", None)
    ctx.__dict__.pop("selector", None)
    print("5. Sélection   : sourcia select \"" + args.demande + "\"\n")
    args.n, args.llm_top, args.export = 10, 0, "json,md"
    args.annee_min = args.annee_max = args.types = args.sources = args.region = None
    args.strict = False
    cmd_select(args)
    print("\n6. Formation (appelle le modèle) : sourcia formation --sequences 2 --quiz 2"
          "\n   ou, diplômante : sourcia formation --demande-fichier config/demandes/btsa_sorgho_c4.yaml")


def _latest_selection(ctx) -> Path | None:
    files = sorted(ctx.settings.path("exports", ".keep").parent.glob("selection-*.json"))
    return files[-1] if files else None


def _demande_from_args(args, base=None):
    """Demande structurée : fichier YAML (--demande-fichier), puis options de la ligne de commande par-dessus."""
    from sourcia.core.demande import Demande

    if getattr(args, "demande_fichier", None):
        d = Demande.load(Path(args.demande_fichier))
    elif base is not None:
        d = base
    else:
        sujet = getattr(args, "sujet", None) or getattr(args, "demande", None)
        if not sujet:
            sys.exit("Donner un sujet, ou une demande structurée : --demande-fichier config/demandes/<exemple>.yaml")
        d = Demande(sujet=sujet)
    over = {}
    if getattr(args, "n", None) and getattr(args, "cmd", "") == "select":
        over["nombre_sources"] = args.n
    for name in ("profil", "apprenants", "niveau", "experience", "modalite", "duree_min", "diplome", "region",
                 "annee_min", "nombre_sources"):
        v = getattr(args, name, None)
        if v is not None:
            over[name] = v
    for name in ("sorties", "ressources", "capacites", "supports", "fichiers_personnels"):
        v = getattr(args, name, None)
        if v:
            over[name] = [x for x in v.split(",") if x] if isinstance(v, str) else v
    if getattr(args, "notes", None):
        over["notes_personnelles"] = Path(args.notes).read_text(encoding="utf-8") if Path(args.notes).exists() else args.notes
    if over.get("diplome"):
        over["diplomante"] = True
    if getattr(args, "sujet", None) and getattr(args, "demande_fichier", None):
        over["sujet"] = args.sujet
    return d.model_copy(update=over) if over else d


def cmd_demande(args) -> None:
    """Écrit un modèle de demande structurée (YAML commenté) à remplir."""
    src = REPO_ROOT / "config" / "demandes" / "modele.yaml"
    out = Path(args.fichier)
    if out.exists() and not args.force:
        sys.exit(f"{out} existe déjà (--force pour l'écraser).")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Modèle écrit : {out}\nÀ remplir, puis : sourcia select --demande-fichier {out} --export json")


def cmd_formation(args) -> None:
    """M7 : créer le support de formation à partir d'une sélection, piloté par la demande structurée."""
    from sourcia.core.demande import Demande
    from sourcia.formation.builder import FormationBuilder
    from sourcia.formation.render import load, write
    from sourcia.select.funnel import select_demande

    ctx = _ctx(args)
    base, doc_ids = None, []
    if args.reprendre:
        old = load(Path(args.reprendre))
        base, doc_ids = old.demande, [i for i in old.doc_ids if i not in old.personnel_ids]
        print(f"Reprise de {Path(args.reprendre).name} : même demande, mêmes sources, blocs personnels conservés")
    elif args.selection or (not args.demande_fichier and not args.sujet and _latest_selection(ctx)):
        path = Path(args.selection) if args.selection else _latest_selection(ctx)
        data = json.loads(path.read_text(encoding="utf-8"))
        doc_ids = [r["id"] for r in data["documents"] if r.get("id")]
        base = Demande.model_validate(data["demande_structuree"]) if data.get("demande_structuree") \
            else Demande(sujet=data["demande"])
        print(f"Sélection lue : {path.name} ({len(doc_ids)} documents)")
    d = _demande_from_args(args, base)
    if not doc_ids:
        sel = select_demande(ctx.selector, d)
        ctx.qualifier.save()
        doc_ids = [c.document.id for c in sel]
        print(f"Sélection : {len(doc_ids)} documents pour « {d.sujet} »")
    if not doc_ids:
        sys.exit("Aucune source sélectionnée (index vide ? lancer sourcia index).")
    print(f"Demande : {d.profil} · {d.apprenants}/{d.niveau} · {'diplômante ' + str(d.diplome) + ' ' + ','.join(d.capacites) if d.diplomante else 'non diplômante'}"
          f" · sorties : {', '.join(d.sorties)}")
    print(f"Modèle : {ctx.settings.llm.provider} / {ctx.settings.llm.model} (compter 1 à 3 min par appel en local)")
    form = FormationBuilder(ctx).build(d, doc_ids, n_seq=args.sequences, n_quiz=args.quiz, log=print)
    paths = write(form, ctx, ctx.settings.path("formations", ".keep").parent, reprendre=Path(args.reprendre) if args.reprendre else None)
    n_q = sum(len(s.quiz) for s in form.sequences)
    n_p = sum(len(s.points) for s in form.sequences)
    n_r = sum(len(s.retires) for s in form.sequences) + len(form.retires)
    alerts = [o["alerte"] for o in form.niveau.get("objectifs", []) if o.get("alerte")]
    if form.niveau.get("lisibilite", {}).get("alerte"):
        alerts.append(form.niveau["lisibilite"]["alerte"])
    print(f"\n{len(form.sequences)} séquences · {n_p} points clés · {n_q} questions · {len(form.glossaire)} termes"
          f" · {n_r} éléments retirés par les contrôles · {form.appels_modele} appels au modèle · {form.duree_s} s")
    if form.couverture:
        ok = sum(bool(c["sequences"]) for c in form.couverture)
        print(f"Référentiel : {ok}/{len(form.couverture)} capacités visées couvertes (rattachements à valider : rattachements.csv)")
    for a in alerts[:6]:
        print(f"  ⚠️ niveau : {a}")
    for r in form.remarques[:6]:
        print(f"  📝 {r}")
    print("Fichiers :")
    for p in paths:
        print(f"  {p}")


def cmd_valider_formation(args) -> None:
    """Importe les rattachements validés par l'enseignant (rattachements.csv) et régénère le support."""
    from sourcia.formation.render import load, write
    from sourcia.referentiel.models import ReferentielStore
    from sourcia.referentiel.validation import Rattachements, import_rattachements_csv

    ctx = _ctx(args)
    folder = Path(args.dossier)
    form = load(folder)
    if not form.referentiel:
        sys.exit("Cette formation n'est pas rattachée à un référentiel.")
    ref = ReferentielStore(ctx.settings.referentiels_dir).get(form.referentiel["id"])
    store = Rattachements(ctx.settings.path("rattachements_valides.jsonl"))
    stats = import_rattachements_csv(form, folder / "rattachements.csv", store, ref, args.par)
    write(form, ctx, folder.parent, reprendre=folder)
    print(f"Validés : {stats['valides']} · corrigés : {stats['corriges']} · refusés : {stats['refuses']}"
          + (f" · codes inconnus ignorés : {', '.join(stats['codes_inconnus'])}" if stats["codes_inconnus"] else ""))
    print(f"Support mis à jour : {folder / 'support_formateur.md'}")


def cmd_referentiel(args) -> None:
    """M8 : liste | voir | construire | verifier | valider | importer."""
    from sourcia.referentiel import catalogue as cat
    from sourcia.referentiel.models import ReferentielStore
    from sourcia.referentiel.validation import export_referentiel_csv, import_referentiel_csv

    ctx = _ctx(args)
    folder = ctx.settings.referentiels_dir
    store = ReferentielStore(folder)
    if args.action == "liste":
        known = {e["id"]: e for e in cat.load_catalogue(folder)}
        for rid in sorted(set(known) | set(store.ids())):
            r = store.get(rid)
            state = f"{len(r.capacites)} capacités, version {r.version}, {r.statut}" if r else "pas encore construit"
            print(f"  {rid:<16} {known.get(rid, {}).get('nom', r.nom if r else ''):<70} {state}")
        return
    if not args.id:
        sys.exit("Préciser l'identifiant du référentiel (voir : sourcia referentiel liste).")
    if args.action == "voir":
        r = store.get(args.id) or sys.exit(f"{args.id} : pas encore construit (sourcia referentiel construire {args.id}).")
        print(f"{r.nom} — version {r.version} — niveau {r.niveau} — {r.statut}")
        for c in r.capacites:
            ind = "  " if c.parent else ""
            print(f"  {ind}{c.code:<7} {c.libelle}" + (f"  [{len(c.variantes)} variante(s)]" if c.variantes else "")
                  + ("" if c.statut == "extrait_automatiquement" else f"  ({c.statut})"))
    elif args.action == "construire":
        r = cat.fetch_and_build(ctx.settings, folder, args.id, files=[Path(f) for f in (args.fichiers or [])])
        print(f"{r.id} : {len(r.capacites)} capacités extraites (version {r.version}) → {folder / (r.id + '.yaml')}")
        print(f"Étape suivante : faire relire → sourcia referentiel valider {r.id}")
    elif args.action == "verifier":
        rep = cat.check_versions(ctx.settings, folder, args.id)
        print(f"inchangés : {len(rep['inchanges'])} · modifiés : {len(rep['modifies'])} · nouveaux : {len(rep['nouveaux'])}"
              f" · injoignables : {len(rep['injoignables'])}")
        for u in rep["modifies"] + rep["nouveaux"]:
            print(f"  ⚠️ {u}  → nouvelle version possible : sourcia referentiel construire {args.id} --fichiers <pdf>")
    elif args.action == "valider":
        r = store.get(args.id) or sys.exit("référentiel non construit")
        out = export_referentiel_csv(r, REPO_ROOT / "data" / "eval" / f"referentiel_{args.id}_a_valider.csv")
        print(f"Tableau pour l'enseignant : {out}\nPuis : sourcia referentiel importer {args.id} --csv {out} --par \"Nom\"")
    elif args.action == "importer":
        r = store.get(args.id) or sys.exit("référentiel non construit")
        r, stats = import_referentiel_csv(r, Path(args.csv), args.par or "enseignant")
        r.save(folder / f"{r.id}.yaml")
        print(f"validées : {stats['valides']} · corrigées : {stats['corriges']} · rejetées : {stats['rejetes']} · statut : {r.statut}")


def cmd_serve(args) -> None:
    import uvicorn

    from sourcia.api.app import create_app

    print(f"Interface : http://{args.host}:{args.port}  (Ctrl+C pour arrêter)")
    uvicorn.run(create_app(args.config), host=args.host, port=args.port, log_level="warning")


def cmd_mcp(args) -> None:
    from sourcia.mcp_server.server import run

    run(args.config)


# ---------------------------------------------------------------------------- analyseur
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sourcia", description="Trouver et qualifier les sources de R&D pour un formateur.")
    p.add_argument("--config", "-c", default=None, help="fichier de configuration (défaut : config/local.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(fn=fn)
        return sp

    def demande_opts(sp):
        g = sp.add_argument_group("demande structurée (prioritaire sur le fichier)")
        g.add_argument("--demande-fichier", help="demande structurée YAML (modèle : sourcia demande <fichier>)")
        g.add_argument("--profil", choices=["enseignant", "formateur", "conseiller", "intervenant_exterieur", "autre"])
        g.add_argument("--apprenants", choices=["eleves", "apprentis", "etudiants", "salaries", "chefs_entreprise", "conseillers", "autre"])
        g.add_argument("--niveau", choices=["sans_diplome", "cap", "bac_pro", "bac", "bts", "licence", "master_ingenieur"])
        g.add_argument("--experience", choices=["debutant", "intermediaire", "confirme"])
        g.add_argument("--modalite", choices=["presentiel", "distanciel", "hybride"])
        g.add_argument("--supports", help="ecrit,oral,pratique")
        g.add_argument("--duree", dest="duree_min", type=int, help="durée totale en minutes")
        g.add_argument("--diplome", help="référentiel (sourcia referentiel liste) → formation diplômante")
        g.add_argument("--capacites", help="codes visés, ex. C4.2,C4.3 ou C4")
        g.add_argument("--ressources", help="resultats_rd,experimentation,temoignage,synthese,guide_technique,donnees,photo,video,audio")
        g.add_argument("--sorties", help="plan,points_cles,quiz,fiche_technique,synthese,cas_concret,glossaire,podcast,deroule_oral")
        g.add_argument("--notes", help="tes notes personnelles (texte, ou chemin d'un fichier .md/.txt)")
        g.add_argument("--fichiers-personnels", dest="fichiers_personnels", help="dossiers ou fichiers à ajouter (privés)")

    add("doctor", cmd_doctor, "vérifier l'installation et la configuration")

    sp = add("add-site", cmd_add_site, "M1 : trouver les PDF d'un site à partir de son adresse")
    sp.add_argument("url")
    sp.add_argument("--source", help="nom court de la source (défaut : nom du site)")
    sp.add_argument("--include", help="expression régulière : ne garder que les PDF dont l'adresse ou le lien la contient")
    sp.add_argument("--max-pages", type=int, help="pages HTML visitées au maximum")
    sp.add_argument("--no-download", action="store_true", help="lister seulement (pas de téléchargement)")
    sp.add_argument("--medias", action="store_true", help="collecter aussi vidéos, photos, jeux de données et audio des pages")

    sp = add("add-folder", cmd_add_folder, "M1 : ajouter un dossier de documents (privés par défaut)")
    sp.add_argument("folder")
    sp.add_argument("--source", default="prive")
    sp.add_argument("--public", action="store_true", help="documents publics (autorisés vers un modèle en ligne)")

    sp = add("import-catalog", cmd_import_catalog, "M1 : importer un catalogue CSV / JSON / liste d'adresses")
    sp.add_argument("file")
    sp.add_argument("--source", required=True)
    sp.add_argument("--map", help="correspondance de colonnes, ex. url=lien,title=intitule")

    sp = add("download", cmd_download, "M1 : télécharger les PDF listés")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--retry", action="store_true", help="réessayer les documents en erreur")

    sp = add("extract", cmd_extract, "M2 : extraire le texte des documents téléchargés")
    sp.add_argument("--force", action="store_true")

    sp = add("qualify", cmd_qualify, "M3 : remplir les fiches de qualification")
    sp.add_argument("--llm", action="store_true", help="ajouter la passe « modèle » (plus lente)")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--force", action="store_true", help="recalculer les fiches déjà en cache")
    sp.add_argument("--doc", nargs="*", help="seulement ces documents (identifiants) ; affiche la fiche")

    sp = add("fiche", cmd_fiche, "M3 : afficher la fiche d'un document (identifiant ou morceau de titre)")
    sp.add_argument("doc_id")

    sp = add("index", cmd_index, "M4 : construire l'index de recherche")
    sp.add_argument("--no-dense", action="store_true", help="sans embeddings (mots seuls, plus rapide)")

    sp = add("search", cmd_search, "M4 : rechercher (sans filtres ni qualification)")
    sp.add_argument("query")
    sp.add_argument("-k", type=int, default=10)
    sp.add_argument("--mode", choices=["hybrid", "bm25", "dense"], default="hybrid")

    def filters(sp):
        sp.add_argument("--annee-min", type=int)
        sp.add_argument("--annee-max", type=int)
        sp.add_argument("--types", help="ex. experimentation,retour_experience")
        sp.add_argument("--sources", help="ex. arvalis.fr,rdagri")
        sp.add_argument("--region", help="région du formateur (alerte si contexte éloigné)")
        sp.add_argument("--strict", action="store_true", help="exclure les documents dont la valeur filtrée est inconnue")

    sp = add("select", cmd_select, "M5 : sélectionner ≈ 50 documents justifiés pour une demande")
    sp.add_argument("demande", nargs="?", help="le sujet (ou --demande-fichier pour une demande structurée)")
    sp.add_argument("-n", type=int)
    sp.add_argument("--llm-top", type=int, default=0, help="qualifier par le modèle les N premiers candidats")
    sp.add_argument("--export", help="M6 : formats à écrire, ex. md,csv,txt,json,zip")
    filters(sp)
    demande_opts(sp)

    add("stats", cmd_stats, "statistiques de la collecte et des fiches")

    sp = add("eval", cmd_eval, "évaluation : trouver | qualifier | gabarit (tableau à remplir par le métier)")
    sp.add_argument("what", choices=["trouver", "qualifier", "gabarit"])
    sp.add_argument("--file")
    sp.add_argument("-n", type=int, default=50)
    sp.add_argument("--llm", action="store_true")
    sp.add_argument("--llm-top", type=int, default=0)
    sp.add_argument("--out", help="écrire le résultat complet en JSON")

    sp = add("demo", cmd_demo, "tout le pipeline sur les exemples fictifs (sans Internet)")
    sp.add_argument("demande", nargs="?", default="sorgho fourrager en conditions sèches")

    sp = add("demande", cmd_demande, "M0 : écrire un modèle de demande structurée (YAML) à remplir")
    sp.add_argument("fichier")
    sp.add_argument("--force", action="store_true")

    sp = add("formation", cmd_formation, "M7 : créer le support de formation (plan, points clés, QCM, fiche technique…)")
    sp.add_argument("selection", nargs="?", help="fichier selection-*.json (défaut : la dernière sélection exportée)")
    sp.add_argument("--sujet", help="nouvelle sélection sur ce sujet (sinon : la demande ou la dernière sélection)")
    sp.add_argument("--reprendre", help="dossier d'une formation : régénérer en gardant tes blocs personnels")
    sp.add_argument("--sequences", type=int, default=4, help="nombre de séquences au plus (hors capacités à couvrir)")
    sp.add_argument("--quiz", type=int, default=4, help="questions QCM par séquence (0 : aucune)")
    demande_opts(sp)

    sp = add("valider-formation", cmd_valider_formation, "M8 : importer les rattachements validés (rattachements.csv)")
    sp.add_argument("dossier")
    sp.add_argument("--par", required=True, help="nom de l'enseignant qui valide")

    sp = add("referentiel", cmd_referentiel, "M8 : référentiels des diplômes (liste, voir, construire, verifier, valider, importer)")
    sp.add_argument("action", choices=["liste", "voir", "construire", "verifier", "valider", "importer"])
    sp.add_argument("id", nargs="?")
    sp.add_argument("--fichiers", nargs="*", help="construire : PDF déjà téléchargés (sinon téléchargement depuis chlorofil.fr)")
    sp.add_argument("--csv", help="importer : tableau rempli par l'enseignant")
    sp.add_argument("--par", help="importer : nom de l'enseignant")

    sp = add("serve", cmd_serve, "M6 : interface web du formateur et API")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)

    add("mcp", cmd_mcp, "M6 : serveur MCP (pour un agent ou un autre outil)")
    return p


def main(argv: list[str] | None = None) -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")          # pas d'avertissement « HF_TOKEN » (modèles publics)
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    if hasattr(sys.stdout, "reconfigure"):
        try:                                   # Windows : accents et émojis dans la console
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    _load_cloud_keys()
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except ImportError as exc:
        sys.exit(f"Dépendance manquante : {exc}  →  pip install -e .[recommended]")
    except KeyboardInterrupt:
        sys.exit("\nInterrompu (le travail déjà fait est enregistré).")


if __name__ == "__main__":
    main()
