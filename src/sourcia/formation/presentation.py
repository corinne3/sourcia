"""Présentation .pptx des supports, au modèle « Du champ à la classe » (python-pptx).

Diapos : titre (avec le parcours des séquences dessiné comme un sillon), une ou plusieurs diapos par séquence
(numéro dans un pot, objectif, un point par carte avec sa référence), les illustrations encadrées, les chiffres
clés en grand, les sources. Les références complètes (point, extrait exact, [S1, p. N]) sont dans les notes.
Polices : Century Gothic (titres) et Calibri (texte), présentes avec Microsoft Office ; ailleurs, le logiciel en
prend une proche. Un même PLAN des diapos sert à les dessiner et à les compter (``expected_slides``).
"""
from __future__ import annotations

import math
from pathlib import Path

TITRES, TEXTE = "Century Gothic", "Calibri"
COULEURS = {"craie": "F7F8F3", "blanc": "FFFFFF", "terre": "2A231C", "terre_douce": "5E5145", "trait": "DCD8C9",
            "sillon": "B9A98A", "bleuet": "2F4FB8", "colza": "F5C518", "colza_pale": "FDF3C4",
            "prairie": "2E7D4B", "prairie_pale": "E3F1E6", "prairie_texte": "1F5A35", "ble": "EFE3BE",
            "ble_texte": "6B5418"}
LARGEUR, HAUTEUR = 13.333, 7.5                      # pouces, format 16:9
ZONE_POINTS = (2.6, 6.75)                           # haut et bas de la zone des cartes sur une diapo de séquence
# Calibri 16 pt sur 11,5 pouces : environ 130 caractères par ligne mesurés sur un rendu PowerPoint (22/11) ;
# 105 garde une marge (mots longs, capitales). Avec 92, des diapos « (suite) » restaient à moitié vides.
CARACTERES_PAR_LIGNE = 105
ETIQUETTE = 14                                      # « S1, page 1 » au bout du texte, sur la même ligne
SOURCES_PAR_COLONNE = 6
CHIFFRES_PAR_DIAPO = 6


# ---------------------------------------------------------------------- plan des diapos
def card_height(text: str) -> float:
    """Hauteur d'une carte (pouces) d'après la longueur du texte : 16 pt, environ 0,32 pouce par ligne."""
    return 0.32 * max(1, math.ceil((len(text) + ETIQUETTE) / CARACTERES_PAR_LIGNE)) + 0.38


def _fill(points, cap=None) -> list[list]:
    """Remplit les diapos l'une après l'autre sans déborder ; ``cap(i, reste)`` limite le nombre de points."""
    pages, page, used = [], [], 0.0
    space = ZONE_POINTS[1] - ZONE_POINTS[0]
    for k, p in enumerate(points):
        h = card_height(p.texte) + 0.14
        full = cap is not None and len(page) >= cap(len(pages), len(points) - k + len(page))
        if page and (used + h > space or full):
            pages.append(page)
            page, used = [], 0.0
        page.append(p)
        used += h
    return pages + ([page] if page else [])


def paginate(points) -> list[list]:
    """Répartit les points en diapos qui ne débordent pas (au moins un point par diapo).

    Même nombre de diapos que le remplissage simple, mais des diapos équilibrées : 7 points sur 3 diapos font
    3 + 2 + 2, pas 3 + 3 + 1 (vu le 22/11 : des diapos « (suite) » avec une seule carte)."""
    greedy = _fill(points)
    n = len(greedy)
    if n < 2:
        return greedy
    balanced = _fill(points, cap=lambda i, rest: math.ceil(rest / max(1, n - i)))
    return balanced if len(balanced) == n else greedy


def plan(sup, cp, corpus_dir: Path) -> list[tuple]:
    from sourcia.formation.supports import build_chiffres, cited_sources, items_of, make_ref, numbers

    slides: list[tuple] = [("titre",)]
    nums = numbers(cp)
    refs = []
    for i in sup.sequences:
        seq = cp.sequences[i - 1]
        refs += [make_ref(p.reference, nums) for p in seq.points]
        pages = paginate(seq.points) or [[]]
        slides += [("sequence", i, page, k) for k, page in enumerate(pages)]
        slides += [("image", i, ill) for ill in cp.illustrations if ill.sequence == i and (corpus_dir / ill.chemin).is_file()]
    if len(sup.sequences) == len(cp.sequences):
        slides += [("image", None, ill) for ill in cp.illustrations
                   if (not ill.sequence or ill.sequence > len(cp.sequences)) and (corpus_dir / ill.chemin).is_file()]
    chiffres = build_chiffres(items_of(cp, sup.sequences))
    for k in range(0, len(chiffres), CHIFFRES_PAR_DIAPO):
        slides.append(("chiffres", chiffres[k:k + CHIFFRES_PAR_DIAPO]))
    sources = cited_sources(cp, refs) or [b for b in cp.bibliographie if b.numero]
    per_slide = 2 * SOURCES_PAR_COLONNE
    for k in range(0, max(1, len(sources)), per_slide):
        slides.append(("sources", sources[k:k + per_slide], k == 0))
    return slides


def expected_slides(sup, cp, corpus_dir: Path) -> int:
    return len(plan(sup, cp, Path(corpus_dir)))


# ---------------------------------------------------------------------- dessin
def presentation_pptx(sup, cp, corpus_dir: Path, path: Path) -> Path:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.dml import MSO_LINE_DASH_STYLE
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
    from pptx.util import Inches, Pt

    from sourcia.formation.illustrations import caption_label
    from sourcia.formation.supports import make_ref, numbers, source_line

    corpus_dir = Path(corpus_dir)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(LARGEUR), Inches(HAUTEUR)
    blank = prs.slide_layouts[6]
    nums = numbers(cp)
    rgb = {k: RGBColor.from_string(v) for k, v in COULEURS.items()}

    # --- outils
    def new_slide():
        s = prs.slides.add_slide(blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = rgb["craie"]
        return s

    def box(s, x, y, w, h, shape=MSO_SHAPE.RECTANGLE, fill=None, line=None, line_pt=1.0):
        sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
        if fill:
            sh.fill.solid()
            sh.fill.fore_color.rgb = rgb[fill]
        else:
            sh.fill.background()
        if line:
            sh.line.color.rgb = rgb[line]
            sh.line.width = Pt(line_pt)
        else:
            sh.line.fill.background()
        sh.shadow.inherit = False
        if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
            sh.adjustments[0] = min(0.5, 0.12 / max(h, 0.2))
        return sh

    def write(target, runs, size=16, color="terre", font=TEXTE, bold=False, italic=False, align=PP_ALIGN.LEFT,
              anchor=MSO_ANCHOR.TOP, margins=(0.12, 0.06)):
        """runs : texte, ou liste de (texte, réglages) ; écrit dans une forme ou une zone de texte."""
        tf = target.text_frame
        tf.clear()
        tf.word_wrap = True
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = Inches(margins[0])
        tf.margin_top = tf.margin_bottom = Inches(margins[1])
        para = tf.paragraphs[0]
        if align:
            para.alignment = align
        for text, opts in ([(runs, {})] if isinstance(runs, str) else runs):
            r = para.add_run()
            r.text = text
            f = r.font
            f.name = opts.get("font", font)
            f.size = Pt(opts.get("size", size))
            f.bold = opts.get("bold", bold)
            f.italic = opts.get("italic", italic)
            f.color.rgb = rgb[opts.get("color", color)]
        return tf

    def text(s, x, y, w, h, runs, **kw):
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        write(tb, runs, **kw)
        return tb

    def notes(s, lines):
        s.notes_slide.notes_text_frame.text = "\n".join(lines)

    def pot(s, x, y, d, label, size):
        c = box(s, x, y, d, d, MSO_SHAPE.OVAL, fill="colza_pale", line="colza", line_pt=2.25)
        write(c, label, size=size, font=TITRES, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
              margins=(0, 0))

    def footer(s, sources_line):
        if sources_line:
            text(s, 0.6, 6.95, 9.5, 0.35, sources_line, size=11, color="terre_douce")
        text(s, 10.3, 6.95, 2.45, 0.35, "SourcIA", size=11, color="sillon", font=TITRES, align=PP_ALIGN.RIGHT)

    def seq_title(i):
        return cp.sequences[i - 1].titre

    # --- diapos
    figures = 0                                      # « Figure n » dans l'ordre des diapos
    for spec in plan(sup, cp, corpus_dir):
        kind = spec[0]
        s = new_slide()
        if kind == "titre":
            d = cp.demande
            text(s, 0.9, 1.2, 11.5, 1.9, cp.titre, size=40, font=TITRES, bold=True, anchor=MSO_ANCHOR.BOTTOM)
            public = d.public_description()
            text(s, 0.9, 3.15, 11.5, 0.9, public[:1].upper() + public[1:], size=18, color="terre_douce")
            if cp.referentiel:
                caps = ", ".join(c["code"] for c in cp.capacites_visees)
                chip = box(s, 0.9, 4.1, 11.5, 0.55, MSO_SHAPE.ROUNDED_RECTANGLE, fill="colza_pale")
                write(chip, [(cp.referentiel["nom"], {"bold": True}), (f" : capacités {caps}" if caps else "", {})],
                      size=14, anchor=MSO_ANCHOR.MIDDLE, margins=(0.2, 0.04))
            # le parcours du cours : une pousse par séquence, sur un sillon
            seqs = sup.sequences[:8]
            step = 11.5 / max(1, len(seqs))
            y = 5.55
            line = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(0.9 + step / 2), Inches(y + 0.3),
                                          Inches(0.9 + step * (len(seqs) - 0.5)), Inches(y + 0.3))
            line.line.color.rgb = rgb["sillon"]
            line.line.width = Pt(2.5)
            line.line.dash_style = MSO_LINE_DASH_STYLE.DASH
            for k, i in enumerate(seqs):
                cx = 0.9 + step * k + step / 2
                pot(s, cx - 0.3, y, 0.6, str(i), 16)
                text(s, cx - step / 2 + 0.05, y + 0.68, step - 0.1, 0.7, seq_title(i), size=11,
                     color="terre_douce", align=PP_ALIGN.CENTER, margins=(0.02, 0))
            notes(s, ["Support préparé avec SourcIA à partir de sources vérifiées : chaque information renvoie à son "
                      "document et à sa page (voir les notes de chaque diapo).",
                      f"Séquences présentées : {', '.join(map(str, sup.sequences))}."])
        elif kind == "sequence":
            _, i, page, k = spec
            seq = cp.sequences[i - 1]
            pot(s, 0.6, 0.45, 1.0, str(i), 28)
            text(s, 1.85, 0.45, 10.9, 1.0, seq.titre + (" (suite)" if k else ""), size=28, font=TITRES, bold=True,
                 anchor=MSO_ANCHOR.MIDDLE)
            obj = box(s, 0.6, 1.7, 12.15, 0.7, MSO_SHAPE.ROUNDED_RECTANGLE, fill="prairie_pale")
            write(obj, [("Objectif : ", {"bold": True}), (seq.objectif.rstrip(". "), {}),
                        (f", capacité {seq.capacite}" if seq.capacite else "", {})],
                  size=16, color="prairie_texte", anchor=MSO_ANCHOR.MIDDLE, margins=(0.2, 0.04))
            y = ZONE_POINTS[0]
            lines, short = [f"Objectif : {seq.objectif}" + (f" (capacité {seq.capacite})" if seq.capacite else "")], []
            for p in page:
                r = make_ref(p.reference, nums)
                h = card_height(p.texte)
                box(s, 0.6, y, 12.15, h, MSO_SHAPE.ROUNDED_RECTANGLE, fill="blanc", line="trait")
                box(s, 0.6, y + 0.1, 0.08, h - 0.2, fill="prairie")
                card = text(s, 0.75, y, 11.9, h, [(p.texte, {}), (f"   {r.numero or 'Source'}, page {r.page}",
                                                                   {"size": 12, "bold": True, "color": "ble_texte"})],
                            size=16, anchor=MSO_ANCHOR.MIDDLE, margins=(0.15, 0.04))
                card.name = "Point clé"
                y += h + 0.14
                lines += [f"• {p.texte} {r.label()}", f"  Extrait : « {r.extrait} »"]
                short.append(f"{r.numero or 'source'} p. {r.page}")
            if not page:
                card = box(s, 0.6, y, 12.15, 0.8, MSO_SHAPE.ROUNDED_RECTANGLE, fill="blanc", line="trait")
                write(card, "Aucun point clé retenu pour cette séquence : à compléter.", size=16, italic=True,
                      color="terre_douce", anchor=MSO_ANCHOR.MIDDLE, margins=(0.25, 0.04))
            footer(s, ("Sources de la diapo : " + ", ".join(dict.fromkeys(short))) if short else "")
            notes(s, lines)
        elif kind == "image":
            _, i, ill = spec
            text(s, 0.6, 0.35, 12.1, 0.8, f"Séquence {i} : {seq_title(i)}" if i else "Illustration", size=22,
                 font=TITRES, bold=True, anchor=MSO_ANCHOR.MIDDLE)
            box_w, box_h, top = 11.3, 4.85, 1.35
            pic = s.shapes.add_picture(str(corpus_dir / ill.chemin), Inches(1.0), Inches(top), height=Inches(box_h))
            if pic.width > Inches(box_w):
                pic.height = int(pic.height * Inches(box_w) / pic.width)
                pic.width = Inches(box_w)
            pic.left = int((prs.slide_width - pic.width) / 2)
            pic.line.color.rgb = rgb["trait"]
            pic.line.width = Pt(1.5)
            num = nums.get(ill.doc_id)
            figures += 1
            caption = f"{caption_label(figures, ill.legende)} ({num + ', ' if num else ''}page {ill.page})"
            text(s, 1.0, 6.35, 11.3, 0.55, caption, size=14, italic=True, color="terre_douce", align=PP_ALIGN.CENTER)
            footer(s, "")
            notes(s, [caption, "Illustration d'origine du document cité."])
        elif kind == "chiffres":
            _, chiffres = spec
            text(s, 0.6, 0.35, 12.1, 0.9, "Les chiffres clés", size=30, font=TITRES, bold=True,
                 anchor=MSO_ANCHOR.MIDDLE)
            cols = 3                                   # même largeur de carte, même avec un seul chiffre
            w, h = (12.15 - 0.3 * (cols - 1)) / cols, 2.45
            for k, c in enumerate(chiffres):
                x, y = 0.6 + (k % cols) * (w + 0.3), 1.55 + (k // cols) * (h + 0.3)
                box(s, x, y, w, h, MSO_SHAPE.ROUNDED_RECTANGLE, fill="blanc", line="trait")
                box(s, x + 0.25, y, w - 0.5, 0.08, fill="colza")
                text(s, x + 0.1, y + 0.2, w - 0.2, 0.8, c.valeur, size=30, font=TITRES, bold=True, color="bleuet")
                text(s, x + 0.1, y + 1.0, w - 0.2, h - 1.45, c.phrase, size=12)
                text(s, x + 0.1, y + h - 0.45, w - 0.2, 0.35, f"{c.reference.numero or 'Source'}, page {c.reference.page}",
                     size=11, bold=True, color="ble_texte")
            footer(s, "")
            notes(s, [f"{c.valeur} : {c.phrase} {c.reference.label()}" for c in chiffres])
        elif kind == "sources":
            _, chunk, first = spec
            text(s, 0.6, 0.35, 12.1, 0.9, "Sources" if first else "Sources (suite)", size=30, font=TITRES, bold=True,
                 anchor=MSO_ANCHOR.MIDDLE)
            if not chunk:
                text(s, 0.6, 1.5, 12.1, 0.6, "Aucune source citée.", size=16, italic=True)
            for col in range(2):
                part = chunk[col * SOURCES_PAR_COLONNE:(col + 1) * SOURCES_PAR_COLONNE]
                if not part:
                    continue
                tb = s.shapes.add_textbox(Inches(0.6 + col * 6.2), Inches(1.45), Inches(5.95), Inches(5.3))
                tf = tb.text_frame
                tf.word_wrap = True
                tf.auto_size = MSO_AUTO_SIZE.NONE
                for k, b in enumerate(part):
                    para = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                    para.space_after = Pt(9)
                    head, _, rest = source_line(b).partition(". ")
                    for t, bold, color in ((head + ". ", True, "bleuet"), (rest, False, "terre")):
                        r = para.add_run()
                        r.text = t
                        r.font.name, r.font.size, r.font.bold = TEXTE, Pt(13), bold
                        r.font.color.rgb = rgb[color]
            footer(s, "")
            notes(s, [source_line(b) for b in chunk])
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    return path
