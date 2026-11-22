"""Illustrations d'origine des documents, pour le corpus pédagogique (PyMuPDF).

Règles :
- seulement les images des PAGES CITÉES (points clés, synthèse) des documents cochés : chaque image garde le
  lien « S2, p. 4 » ; un document coché qui est lui-même une photo (``kind="image"``) est repris tel quel ;
- jamais les images d'un document privé (le document Word peut être partagé), sauf un PDF téléversé par le
  formateur dans son dossier (marque ``FOURNI``) : ce sont ses propres documents, dans son dossier protégé ;
- on écarte ce qui n'est pas une illustration : petites images (en pixels ou sur la page), bandeaux, LOGOS
  (même image sur plusieurs pages, ou petite image en haut ou en bas de page), fonds de page, décors (image
  presque unie, pâle ou en aplats), doublons ; 2 images par page au plus, ``max_total`` en tout ;
- la LÉGENDE vient du document (ligne « Figure… », « Tableau… », « Photo… » juste sous ou sur l'image),
  sinon « Illustration tirée de « titre » » (la page est dans la référence) : rien n'est inventé.

Les fichiers sont copiés dans ``<dossier du corpus>/illustrations/`` (chemins relatifs dans corpus.json).
"""
from __future__ import annotations

import hashlib
import re
import shutil
from collections import Counter
from pathlib import Path

# Seuils réglés sur 40 PDF réels du catalogue (Terres Inovia, Chambres, Arvalis, RFL…) le 20/11/2026
MIN_SIDE = 150            # pixels : en dessous, icône ou puce
MIN_SHOWN = 60            # points (1/72 de pouce) : image affichée trop petite sur la page
MIN_AREA = 0.03           # part de la page : en dessous, logo ou vignette (une figure utile fait 4 % ou plus)
MAX_AREA = 0.75           # part de la page : au-dessus, fond de page ou couverture décorative
MARGIN = 0.12             # haut et bas de page : une petite image y est un logo d'en-tête ou de pied de page
MARGIN_AREA = 0.06
MIN_CONTRAST = 15         # écart-type de la luminosité : en dessous, image unie, ombre ou filigrane pâle
MIN_COLORS = 9            # couleurs distinctes (16 niveaux par canal) : en dessous, aplat décoratif
TWO_TONE = 0.95           # deux couleurs couvrent 95 % de l'image (sans fond dominant) : décor en aplats
MAX_RATIO = 5.0           # bandeau, filet décoratif
PER_PAGE = 2
MAX_TOTAL = 12
CAPTION_GAP = 60          # points entre l'image et sa légende
MAX_SCAN_PAGES = 80       # pages parcourues pour repérer les logos
WORD_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}
CAPTION_RE = re.compile(r"^\s*(fig(ure)?\b|fig\.|tableau|photo|graphique|carte|sch[ée]ma|illustration)", re.I)


def _pymupdf():
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf      # anciennes versions de PyMuPDF
        except ImportError:
            return None
    return pymupdf


def cited_pages(cp) -> list[tuple[str, int, int | None]]:
    """(document, page, séquence) dans l'ordre du corpus : séquences d'abord, puis la synthèse (séquence None)."""
    out: dict[tuple[str, int], int | None] = {}
    for i, s in enumerate(cp.sequences, 1):
        for p in s.points:
            out.setdefault((p.reference.doc_id, p.reference.page), i)
    for x in (cp.synthese.paragraphes if cp.synthese else []):
        out.setdefault((x.reference.doc_id, x.reference.page), None)
    return [(d, pg, seq) for (d, pg), seq in out.items()]


def find_caption(page, rect) -> str | None:
    """Ligne de légende (« Figure 2 : … ») juste sous l'image, sinon juste au-dessus ; None si aucune."""
    if rect is None:
        return None
    best = None
    for b in page.get_text("blocks"):
        x0, y0, x1, y1, text = b[:5]
        text = " ".join(str(text).split())
        if not text or not CAPTION_RE.match(text) or min(x1, rect.x1) - max(x0, rect.x0) <= 0:
            continue
        gap = y0 - rect.y1 if y0 >= rect.y1 - 2 else rect.y0 - y1 if y1 <= rect.y0 + 2 else None
        if gap is not None and -2 <= gap <= CAPTION_GAP and (best is None or gap < best[0]):
            best = (gap, text)
    return best[1][:220] if best else None


def logo_xrefs(pdf) -> set[int]:
    """Images présentes sur au moins deux pages : logos, en-têtes, pieds de page."""
    pages: dict[int, set[int]] = {}
    for i, page in enumerate(pdf):
        if i >= MAX_SCAN_PAGES:
            break
        for img in page.get_images(full=True):
            pages.setdefault(img[0], set()).add(i)
    return {x for x, p in pages.items() if len(p) >= 2}


def placement(rect, page_rect) -> str | None:
    """Raison d'écarter une image d'après sa place sur la page, sinon None."""
    if rect is None:
        return None
    if min(rect.width, rect.height) < MIN_SHOWN:
        return "petites"
    area = rect.width * rect.height / max(1.0, page_rect.width * page_rect.height)
    if area < MIN_AREA:
        return "petites"
    if area > MAX_AREA:
        return "fonds de page"
    in_margin = rect.y1 <= page_rect.y0 + MARGIN * page_rect.height or rect.y0 >= page_rect.y1 - MARGIN * page_rect.height
    if in_margin and area < MARGIN_AREA:
        return "logos"
    return None


def looks_decorative(pymupdf, pdf, xref) -> bool:
    """Image presque unie, pâle (filigrane) ou en aplats de quelques couleurs : un décor, pas une illustration."""
    pix = pymupdf.Pixmap(pdf, xref)
    if pix.colorspace is None:                       # masque seul
        return True
    if pix.colorspace.n != 3 or pix.alpha:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        if pix.alpha:
            pix = pymupdf.Pixmap(pix, 0)
    # Échantillon d'environ 40 000 pixels, SANS réduire l'image : PyMuPDF garde l'image décodée en mémoire et
    # pix.shrink() la modifiait sur place, si bien que l'image enregistrée ensuite sortait à moitié de sa taille.
    s, n, pixels = pix.samples, pix.n, pix.width * pix.height
    if not pixels:
        return True
    step = max(1, pixels // 40000)
    lum, colors = [], Counter()
    for k in range(0, pixels, step):
        i = k * n
        r, g, b = s[i], s[i + 1], s[i + 2]
        lum.append(0.299 * r + 0.587 * g + 0.114 * b)
        colors[(r >> 4, g >> 4, b >> 4)] += 1
    total = len(lum)
    mean = sum(lum) / total
    sd = (sum((x - mean) ** 2 for x in lum) / total) ** 0.5
    top = [c / total for _, c in colors.most_common(2)] + [0.0]
    # deux grands aplats (arcs noir et crème des brochures) ; un graphique a UN fond dominant (le blanc)
    two_tone = top[0] < 0.85 and top[0] + top[1] >= TWO_TONE
    return sd < MIN_CONTRAST or len(colors) < MIN_COLORS or two_tone


def _save_image(pymupdf, pdf, img, dest_stem: Path) -> tuple[Path, bytes] | None:
    """Enregistre l'image dans un format que Word (et python-docx) sait lire.

    Un PNG sans transparence est gardé tel quel. Tout le reste passe par PyMuPDF : les JPEG des PDF sont souvent
    des JPEG « Adobe » (en CMJN, sans en-tête JFIF) que python-docx refuse (vu sur les fiches Arvalis le 20/11) ;
    on les ré-encode en JPEG standard ; les autres formats (JPEG 2000, transparence…) deviennent des PNG."""
    xref, smask = img[0], img[1]
    info = pdf.extract_image(xref)
    if not info or not info.get("image"):
        return None
    ext = str(info.get("ext", "")).lower()
    if ext == "png" and not smask:
        path = dest_stem.with_suffix(".png")
        path.write_bytes(info["image"])
        return path, info["image"]
    pix = pymupdf.Pixmap(pdf, xref)
    if pix.colorspace is None:                       # masque seul : pas une image à montrer
        return None
    if smask:                                        # transparence gardée
        try:
            pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(pdf, smask))
        except Exception:                            # masque d'une autre taille (vu sur Terres Inovia) : sans
            pass
    if pix.colorspace.n > 3:                         # CMJN → RVB
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if ext in ("jpeg", "jpg", "jpx") and not pix.alpha:          # photo : JPEG (plus léger qu'un PNG)
        path, data = dest_stem.with_suffix(".jpg"), pix.tobytes("jpg", jpg_quality=85)
    else:
        path, data = dest_stem.with_suffix(".png"), pix.tobytes("png")
    path.write_bytes(data)
    return path, data


def extract_illustrations(cp, ctx, folder: Path, max_total: int = MAX_TOTAL) -> list:
    """Remplit ``cp.illustrations`` (et copie les images dans ``folder/illustrations``) ; renvoie la liste."""
    from sourcia.formation.corpus_pedagogique import FOURNI, Illustration

    folder = Path(folder)
    out_dir = folder / "illustrations"
    found: list[Illustration] = []
    seen: set[str] = set()
    skipped = {"petites": 0, "bandeaux": 0, "logos": 0, "fonds de page": 0, "décors": 0, "doublons": 0,
               "au-delà de la limite": 0}
    private: set[str] = set()
    errors: list[str] = []

    def keep(data: bytes) -> bool:
        h = hashlib.sha1(data).hexdigest()
        if h in seen:
            skipped["doublons"] += 1
            return False
        seen.add(h)
        return True

    pages = cited_pages(cp)
    pdf_pages = []
    for did, pg, seq in pages:
        doc = ctx.store.get(did)
        if doc is None:
            continue
        if doc.private and not doc.meta.get(FOURNI):
            private.add(doc.title or did)
        elif doc.kind == "pdf" and doc.local_path and Path(doc.local_path).exists():
            pdf_pages.append((doc, pg, seq))
    pymupdf = _pymupdf() if pdf_pages else None
    if pdf_pages and pymupdf is None:
        cp.remarques.append("illustrations des PDF non extraites : PyMuPDF manque (pip install -e \".[local]\")")
        pdf_pages = []

    opened: dict[str, tuple] = {}
    try:
        for doc, pg, seq in pdf_pages:
            if len(found) >= max_total:
                skipped["au-delà de la limite"] += 1
                continue
            try:
                if doc.id not in opened:
                    pdf = pymupdf.open(doc.local_path)
                    opened[doc.id] = (pdf, logo_xrefs(pdf))
                pdf, logos = opened[doc.id]
                if not 1 <= pg <= pdf.page_count:
                    continue
                page = pdf[pg - 1]
                k = 0
                for img in page.get_images(full=True):
                    xref, width, height = img[0], img[2], img[3]
                    if xref in logos:
                        skipped["logos"] += 1
                        continue
                    if min(width, height) < MIN_SIDE:
                        skipped["petites"] += 1
                        continue
                    if max(width, height) / max(1, min(width, height)) > MAX_RATIO:
                        skipped["bandeaux"] += 1
                        continue
                    rects = page.get_image_rects(xref)
                    rect = rects[0] if rects else None
                    why = placement(rect, page.rect)
                    if why:
                        skipped[why] += 1
                        continue
                    if k >= PER_PAGE or len(found) >= max_total:
                        skipped["au-delà de la limite"] += 1
                        continue
                    try:
                        if looks_decorative(pymupdf, pdf, xref):
                            skipped["décors"] += 1
                            continue
                    except Exception:                # pixels illisibles : on laisse _save_image décider
                        pass
                    out_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        saved = _save_image(pymupdf, pdf, img, out_dir / f"{doc.id}-p{pg}-{k + 1}")
                    except Exception as exc:         # une image illisible n'empêche pas les autres
                        errors.append(f"image de « {doc.title or doc.id} » p. {pg} non lue ({type(exc).__name__})")
                        continue
                    if saved is None:
                        continue
                    path, data = saved
                    if not keep(data):
                        path.unlink(missing_ok=True)
                        continue
                    k += 1
                    legend = find_caption(page, rect) or f"Illustration tirée de « {doc.title or doc.id} »"
                    found.append(Illustration(chemin=path.relative_to(folder).as_posix(), legende=legend,
                                              doc_id=doc.id, page=pg, sequence=seq))
            except Exception as exc:                 # PDF abîmé ou chiffré : on le dit, on continue
                errors.append(f"illustrations de « {doc.title or doc.id} » p. {pg} non lues ({type(exc).__name__})")
    finally:
        for pdf, _ in opened.values():
            pdf.close()

    # documents cochés qui sont eux-mêmes des photos
    for did in cp.doc_ids:
        doc = ctx.store.get(did)
        if doc is None or doc.kind != "image":
            continue
        if doc.private and not doc.meta.get(FOURNI):
            private.add(doc.title or did)
            continue
        src = Path(doc.local_path) if doc.local_path else None
        if not src or not src.exists() or src.suffix.lower() not in WORD_IMAGE_EXT:
            continue
        if len(found) >= max_total:
            skipped["au-delà de la limite"] += 1
            continue
        if not keep(src.read_bytes()):
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{doc.id}{src.suffix.lower()}"
        pm = _pymupdf() if src.suffix.lower() in (".jpg", ".jpeg") else None
        try:
            if pm is None:
                raise ValueError
            pix = pm.Pixmap(str(src))                # JPEG « Adobe » refusé par python-docx : ré-encodé
            if pix.colorspace is not None and pix.colorspace.n > 3:
                pix = pm.Pixmap(pm.csRGB, pix)
            dest = dest.with_suffix(".jpg")
            dest.write_bytes(pix.tobytes("jpg", jpg_quality=90))
        except Exception:
            shutil.copyfile(src, dest)
        found.append(Illustration(chemin=dest.relative_to(folder).as_posix(), legende=doc.title or src.stem,
                                  doc_id=doc.id, page=1))

    cp.illustrations = found
    if found or any(skipped.values()):
        ecartees = ", ".join(f"{n} {k}" for k, n in skipped.items() if n)
        cp.remarques.append(f"illustrations : {len(found)} retenue(s)" + (f" ; écartées : {ecartees}" if ecartees else ""))
    if private:
        cp.remarques.append("images des documents privés non reprises : " + ", ".join(sorted(private)))
    cp.remarques.extend(errors)
    return found
