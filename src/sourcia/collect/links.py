"""Suivi des liens (M1) : repérer les documents déplacés ou morts, sans rien télécharger.

Pour chaque document du catalogue (sauf les documents privés), on demande seulement les en-têtes
de son adresse (``HEAD``, ou ``GET`` interrompu si le site refuse ``HEAD``) et on suit soi-même les
redirections. Règles :

- réponse 200 à la même adresse ............................ ``ok``
- redirection définitive (301, 308) puis réponse 200 ........ ``moved`` (nouvelle adresse dans ``new_url``)
- redirection temporaire (302, 303, 307) puis réponse 200 .. ``ok`` (l'adresse d'origine reste la bonne)
- 404 ou 410, ou page HTML à la place d'un PDF ............. ``dead`` tout de suite
- délai dépassé, erreur 5xx, connexion impossible… ......... ``unreachable`` ; ``dead`` après 3 échecs de suite
- un lien qui remarche revient à ``ok`` (ou ``moved``)

``url`` et ``id`` ne changent jamais : tout est noté dans ``Document.link`` (voir ``core/models.py``).
Un document déjà « déplacé » est vérifié à sa nouvelle adresse.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable
from urllib.parse import urljoin

from sourcia.collect.store import DocumentStore
from sourcia.collect.web import WebCollector, _short_error
from sourcia.core.models import Document, LinkCheck

REDIRECTS = {301, 302, 303, 307, 308}
PERMANENT = {301, 308}
GONE = {404, 410}
NO_HEAD = {403, 405, 501}            # serveurs qui refusent HEAD : on réessaie en GET (sans lire le contenu)
MAX_FAILURES = 3
MAX_HOPS = 5


class Blocked(Exception):
    """Adresse interdite par robots.txt : on ne la vérifie pas."""


def _follow(wc: WebCollector, url: str):
    """Suit les redirections. Renvoie (réponse finale, adresse finale, codes de redirection)."""
    hops: list[int] = []
    for _ in range(MAX_HOPS + 1):
        if not wc.allowed(url):
            raise Blocked(url)
        r = wc.probe(url, "HEAD")
        if r.status_code in NO_HEAD:
            r = wc.probe(url, "GET")
        location = r.headers.get("location") or r.headers.get("Location")
        if r.status_code in REDIRECTS and location:
            hops.append(r.status_code)
            url = urljoin(url, location)
            continue
        return r, url, hops
    raise RuntimeError(f"plus de {MAX_HOPS} redirections")


def check_document(wc: WebCollector, doc: Document, today: str | None = None) -> LinkCheck | None:
    """Vérifie le lien d'un document. Renvoie le nouveau suivi, ou None si le document n'est pas vérifiable
    (privé, adresse locale). Lève ``Blocked`` si robots.txt interdit l'adresse."""
    if doc.private or not doc.url.startswith(("http://", "https://")):
        return None
    today = today or date.today().isoformat()
    prev = doc.link
    target = prev.new_url if prev and prev.state == "moved" and prev.new_url else doc.url

    def failed(code: int | None, detail: str, dead_now: bool) -> LinkCheck:
        failures = (prev.failures if prev and prev.state in ("unreachable", "dead") else 0) + 1
        since = prev.since if prev and prev.state in ("unreachable", "dead") and prev.since else today
        dead = dead_now or failures >= MAX_FAILURES
        if dead and not dead_now:
            detail += f" ({failures} vérifications de suite depuis le {since})"
        return LinkCheck(state="dead" if dead else "unreachable", checked_at=today, http_status=code,
                         failures=failures, since=since, detail=detail)

    try:
        r, final, hops = _follow(wc, target)
    except Blocked:
        raise
    except Exception as exc:
        return failed(None, _short_error(exc), dead_now=False)
    code = r.status_code
    if code in GONE:
        return failed(code, f"HTTP {code} : le document n'existe plus à cette adresse", dead_now=True)
    if code != 200:
        return failed(code, f"HTTP {code}", dead_now=False)
    ctype = (r.headers.get("content-type") or r.headers.get("Content-Type") or "").lower()
    if doc.kind == "pdf" and "html" in ctype:
        where = f" (redirection vers {final})" if final != target else ""
        return failed(code, f"page HTML à la place du PDF{where}", dead_now=True)
    # redirection temporaire (302, 303, 307) : souvent un lien de téléchargement signé qui expire ;
    # l'adresse à garder reste celle d'origine. Seules 301 et 308 signalent un vrai déplacement.
    temporary = bool(hops) and not any(h in PERMANENT for h in hops)
    new_url = target if temporary else final
    if new_url != doc.url:
        how = f"redirection {'/'.join(map(str, hops))}" if hops and not temporary else (prev.detail if prev else None)
        return LinkCheck(state="moved", checked_at=today, http_status=code, new_url=new_url, detail=how)
    return LinkCheck(state="ok", checked_at=today, http_status=code,
                     detail=f"redirection temporaire vers {final}" if temporary else None)


def change_of(prev: LinkCheck | None, new: LinkCheck) -> str | None:
    """Ce qui a changé depuis la dernière vérification (pour le rapport), ou None."""
    before = prev.state if prev else None
    if new.state == "dead" and before != "dead":
        return "nouveau_mort"
    if new.state == "moved" and (before != "moved" or (prev and prev.new_url != new.new_url)):
        return "nouveau_deplace"
    if new.state in ("ok", "moved") and before in ("dead", "unreachable"):
        return "revenu"
    if new.state == "unreachable" and before != "unreachable":
        return "injoignable"
    return None


def check_links(wc: WebCollector, store: DocumentStore, docs: list[Document], today: str | None = None,
                progress: Callable[[int, int, Document], None] | None = None, save_every: int = 20) -> dict:
    """Vérifie une liste de documents, met à jour leur suivi, enregistre le catalogue. Renvoie le rapport."""
    today = today or date.today().isoformat()
    counts = {"ok": 0, "moved": 0, "dead": 0, "unreachable": 0}
    changes, blocked, skipped = [], 0, 0
    for i, doc in enumerate(docs, 1):
        if progress:
            progress(i, len(docs), doc)
        prev = doc.link
        try:
            new = check_document(wc, doc, today)
        except Blocked:
            blocked += 1
            continue
        if new is None:
            skipped += 1
            continue
        doc.link = new
        counts[new.state] += 1
        what = change_of(prev, new)
        if what:
            changes.append({"changement": what, "id": doc.id, "source": doc.source, "titre": doc.title,
                            "url": doc.url, "avant": prev.state if prev else None, "maintenant": new.state,
                            "nouvelle_url": new.new_url, "detail": new.detail})
        if i % save_every == 0:
            store.save()
    store.save()
    return {"date": datetime.now().isoformat(timespec="seconds"), "verifies": sum(counts.values()), "etats": counts,
            "bloques_robots": blocked, "ignores_prives": skipped, "changements": changes}



def relink_by_content(store: DocumentStore, today: str | None = None) -> list[tuple[Document, Document]]:
    """Document mort dont le contenu exact (même ``sha1``) existe à une autre adresse : « déplacé » vers elle.

    Cas typique : un site réorganise ses dossiers, l'ancienne adresse donne 404, et la collecte du jour
    télécharge le même fichier à sa nouvelle adresse. Renvoie les paires (ancien, nouveau)."""
    today = today or date.today().isoformat()
    alive: dict[str, Document] = {}
    for d in store:
        if d.sha1 and not (d.link and d.link.state == "dead"):
            alive.setdefault(d.sha1, d)
    pairs = []
    for d in store:
        new = alive.get(d.sha1) if d.sha1 and d.link and d.link.state == "dead" else None
        if new is not None and new.url != d.url:
            was = f" ; avant : {d.link.detail}" if d.link.detail else ""
            d.link = LinkCheck(state="moved", checked_at=today, new_url=new.url,
                               detail=f"même contenu retrouvé à une nouvelle adresse{was}")
            pairs.append((d, new))
    return pairs

_LABELS = {"nouveau_mort": "✗ mort", "nouveau_deplace": "↪ déplacé", "revenu": "✓ revenu", "injoignable": "… injoignable"}


def format_report(report: dict, max_lines: int = 30) -> str:
    """Résumé lisible : les états, puis ce qui a changé depuis la dernière vérification."""
    e = report["etats"]
    lines = [f"Résultat : {e['ok']} ok · {e['moved']} déplacés · {e['dead']} morts · {e['unreachable']} injoignables"
             f" · {report['bloques_robots']} bloqués (robots.txt) · {report['ignores_prives']} privés ignorés"]
    changes = sorted(report["changements"], key=lambda c: list(_LABELS).index(c["changement"]))
    if not changes:
        lines.append("Aucun changement depuis la dernière vérification.")
    else:
        lines.append(f"Changements depuis la dernière vérification ({len(changes)}) :")
        for c in changes[:max_lines]:
            where = f"→ {c['nouvelle_url']}" if c["changement"] == "nouveau_deplace" else f"← {c['url']}"
            detail = f"  ({c['detail']})" if c["detail"] and c["changement"] != "nouveau_deplace" else ""
            lines.append(f"  {_LABELS[c['changement']]:<14} [{c['source']}] {c['titre'][:60]}  {where[:110]}{detail}")
        if len(changes) > max_lines:
            lines.append(f"  … et {len(changes) - max_lines} autres (voir le rapport JSON)")
    return "\n".join(lines)
