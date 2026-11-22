"""Export Word du corpus pédagogique : ``corpus.json`` → ``corpus_pedagogique.docx``.

Le document est construit UNIQUEMENT à partir du corpus (ni catalogue ni modèle) : un corpus.json corrigé à la
main ou reçu d'un autre membre de l'équipe peut être remis en Word à tout moment.

Références vérifiables : chaque point clé et chaque paragraphe de synthèse est suivi de [S1, p. 3], lien qui
ouvre le document à la page citée (``#page=N`` pour un PDF), puis de l'EXTRAIT EXACT du document, en italique.
Seules les adresses web (http, https) sont affichées : un chemin local (file://) ne sert à rien à un lecteur
et montrerait l'arborescence du poste ; un document privé n'a jamais d'adresse.

Nécessite python-docx (``pip install -e ".[word]"``), chargé seulement au moment de l'export.
"""
from __future__ import annotations

import re
from pathlib import Path

from sourcia.formation.render import STATUT_LABEL

LINK_COLOR = "0563C1"
GREY = (0x59, 0x59, 0x59)
# caractères interdits dans un fichier Word (XML) : certains PDF en laissent dans le texte extrait
# (vu sur 1 texte réel sur 593 : \x00, \x10…) et python-docx refusait alors tout le document
XML_FORBIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def word_safe(value):
    """Copie sans caractères interdits dans Word (chaînes, listes, dictionnaires)."""
    if isinstance(value, str):
        return XML_FORBIDDEN.sub("", value)
    if isinstance(value, list):
        return [word_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: word_safe(v) for k, v in value.items()}
    return value


def _docx():
    try:
        import docx
    except ImportError as exc:                       # message clair plutôt qu'une trace
        raise ImportError("export Word : python-docx manque (pip install -e \".[word]\")") from exc
    return docx


def web_url(url: str | None) -> str | None:
    """L'adresse si elle est publique (http/https), sinon None."""
    return url if url and url.lower().startswith(("http://", "https://")) else None


def same_text(a: str, b: str) -> bool:
    """Même phrase, aux espaces, à la casse et à la ponctuation finale près."""
    def norm(s):
        return " ".join((s or "").split()).rstrip(" .;:!?").lower()
    return norm(a) == norm(b)


def add_hyperlink(paragraph, text: str, url: str, size=None):
    """Lien cliquable dans un paragraphe (python-docx n'a pas de fonction pour ça)."""
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), LINK_COLOR)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    props.append(color)
    props.append(underline)
    if size is not None:
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(int(size.pt * 2)))
        props.append(sz)
    run.append(props)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    link.append(run)
    paragraph._p.append(link)
    return link


class _Writer:
    def __init__(self, cp, base_dir: Path):
        docx = _docx()
        from docx.shared import Pt, RGBColor

        self.Pt, self.RGB = Pt, RGBColor
        self.cp = cp
        self.base_dir = Path(base_dir)
        self.doc = docx.Document()
        self.nums = {b.doc_id: b.numero for b in cp.bibliographie if b.numero}
        self.missing: list[str] = []
        self.figures = 0                             # numérotation des figures dans l'ordre du document

    # ------------------------------------------------------------------ petits outils
    def ref_label(self, ref) -> str:
        return f"[{self.nums.get(ref.doc_id, 'source')}, p. {ref.page}]"

    def add_ref(self, paragraph, ref) -> None:
        """« [S1, p. 3] » (cliquable si l'adresse est publique)."""
        paragraph.add_run(" ")
        url = web_url(ref.lien)
        if url:
            add_hyperlink(paragraph, self.ref_label(ref), url)
        else:
            paragraph.add_run(self.ref_label(ref))

    def add_extract(self, ref) -> None:
        if not ref.extrait:
            return
        p = self.doc.add_paragraph()
        p.paragraph_format.left_indent = self.Pt(18)
        p.paragraph_format.space_after = self.Pt(6)
        run = p.add_run(f"« {ref.extrait} »")
        run.italic = True
        run.font.size = self.Pt(9)
        run.font.color.rgb = self.RGB(*GREY)

    def add_item(self, texte: str, ref, style: str | None = "List Bullet") -> None:
        p = self.doc.add_paragraph(style=style)
        p.add_run(texte)
        self.add_ref(p, ref)
        if not same_text(texte, ref.extrait):     # point recopié mot pour mot : l'extrait serait un doublon
            self.add_extract(ref)

    def table(self, rows: list[tuple[str, ...]], header: tuple[str, ...] | None = None) -> None:
        cols = len(header or rows[0])
        t = self.doc.add_table(rows=0, cols=cols)
        t.style = "Table Grid"
        for i, row in enumerate(([header] if header else []) + rows):
            cells = t.add_row().cells
            for c, val in zip(cells, row):
                c.text = str(val)
                if header and i == 0:
                    for r in c.paragraphs[0].runs:
                        r.bold = True
        self.doc.add_paragraph()

    # ------------------------------------------------------------------ parties
    def title_page(self) -> None:
        cp, d = self.cp, self.cp.demande
        self.doc.core_properties.title = cp.titre
        self.doc.core_properties.subject = f"Corpus pédagogique : {d.sujet}"
        self.doc.add_heading(cp.titre, 0)
        p = self.doc.add_paragraph()
        p.add_run("Corpus pédagogique, construit à partir des seuls documents cochés. "
                  "Chaque information renvoie à sa source (document et page) avec l'extrait exact. À relire avant diffusion.").italic = True
        formation = "non diplômante"
        if d.diplomante:
            nom = cp.referentiel["nom"] if cp.referentiel else d.diplome
            formation = f"diplômante : {nom}" + (f" ({', '.join(d.capacites)})" if d.capacites else "")
        self.table([("Sujet", d.sujet), ("Demandeur", d.profil), ("Public", d.public_description()),
                    ("Formation", formation), ("Modalité", f"{d.modalite} ; {', '.join(d.supports)} ; {d.duree_min} min"),
                    ("Documents cochés", str(len(cp.doc_ids))), ("Créé le", cp.cree_le.replace("T", " à ") or "—")])

    def capacities(self) -> None:
        if not self.cp.capacites_visees:
            return
        self.doc.add_heading("Acquis visés", 1)
        cover = {c["code"]: c.get("sequences", []) for c in self.cp.couverture}
        self.table([(c["code"], c["libelle"], ", ".join(map(str, cover.get(c["code"], []))) or "non couverte")
                    for c in self.cp.capacites_visees], header=("Capacité", "Libellé", "Séquences"))

    def sequences(self) -> None:
        for i, s in enumerate(self.cp.sequences, 1):
            self.doc.add_heading(f"Séquence {i} : {s.titre}", 1)
            p = self.doc.add_paragraph()
            p.add_run("Objectif : ").bold = True
            p.add_run(f"{s.objectif} ({s.duree_min} min)")
            if s.capacite:
                p = self.doc.add_paragraph()
                p.add_run("Capacité : ").bold = True
                p.add_run(f"{s.capacite} – {s.capacite_libelle or ''} ")
                p.add_run(f"({STATUT_LABEL.get(s.capacite_statut, s.capacite_statut)})").italic = True
            if s.points:
                self.doc.add_heading("Points clés", 2)
                for pt in s.points:
                    self.add_item(pt.texte, pt.reference)
            else:
                self.doc.add_paragraph("Aucun point clé retenu par les contrôles : à compléter.").runs[0].italic = True
            for ill in [x for x in self.cp.illustrations if x.sequence == i]:
                self.add_figure(ill)
            if s.a_retenir:
                p = self.doc.add_paragraph()
                p.add_run("À retenir : ").bold = True
                p.add_run(s.a_retenir)

    def synthese(self) -> None:
        syn = self.cp.synthese
        if not syn:
            return
        self.doc.add_heading("Synthèse", 1)
        for x in syn.paragraphes:
            self.add_item(x.texte, x.reference, style=None)
        if syn.conclusion:
            p = self.doc.add_paragraph()
            p.add_run("Conclusion : ").bold = True
            p.add_run(syn.conclusion)

    def add_figure(self, ill) -> bool:
        """Image et sa légende « Figure n : … (S2, p. 4) » ; False si non insérée.
        Largeur : 4,5 pouces au plus, sans agrandir une petite image au-delà de sa taille à l'écran (96 points par
        pouce) ; la résolution d'origine (souvent 300 dpi dans les PDF) donnait des photos minuscules."""
        from docx.image.image import Image
        from docx.shared import Inches

        path = Path(ill.chemin)
        path = path if path.is_absolute() else self.base_dir / path
        try:
            px = Image.from_file(str(path)).px_width
            self.doc.add_picture(str(path), width=min(Inches(4.5), Inches(px / 96)))
            self.doc.paragraphs[-1].paragraph_format.keep_with_next = True     # image et légende sur la même page
        except Exception as exc:                     # fichier absent ou format non lu : on le dit, sans planter
            self.missing.append(f"illustration non insérée ({type(exc).__name__}) : {ill.chemin}")
            return False
        self.figures += 1
        p = self.doc.add_paragraph()
        from sourcia.formation.illustrations import caption_label

        p.add_run(caption_label(self.figures, ill.legende)).italic = True
        num = self.nums.get(ill.doc_id)
        p.add_run(f" ({num}, p. {ill.page})" if num else f" (p. {ill.page})").italic = True
        return True

    def illustrations(self) -> None:
        """Les illustrations qui ne sont rattachées à aucune séquence (synthèse, photos cochées)."""
        rest = [x for x in self.cp.illustrations if not x.sequence or x.sequence > len(self.cp.sequences)]
        if not rest:
            return
        heading = self.doc.add_heading("Illustrations", 1)
        if not sum(self.add_figure(ill) for ill in rest):    # aucune insérée : pas de titre vide
            heading._element.getparent().remove(heading._element)

    def bibliography(self) -> None:
        if not self.cp.bibliographie:
            return
        self.doc.add_heading("Bibliographie", 1)
        cited = [b for b in self.cp.bibliographie if b.citee]
        others = [b for b in self.cp.bibliographie if not b.citee]
        for b in cited:
            self.source(b)
        if others:
            self.doc.add_heading("Autres documents consultés (non cités)", 2)
            for b in others:
                self.source(b)

    def source(self, b) -> None:
        p = self.doc.add_paragraph()
        if b.numero:
            p.add_run(f"{b.numero}. ").bold = True
        lead = " ".join(x for x in [b.organisme, f"({b.annee})" if b.annee else None] if x)
        if lead:
            p.add_run(f"{lead}. ")
        p.add_run(b.titre).italic = True
        p.add_run(". ")
        url = web_url(b.url)
        if b.fourni_par_formateur:                   # PDF téléversé dans le dossier : cité, sans lien
            p.add_run("Document fourni par le formateur.")
        elif url:
            add_hyperlink(p, url, url)
        elif b.url is None:
            p.add_run("Document privé, non diffusé.")
        else:
            p.add_run("Fichier local.")
        if b.pages_citees:
            p.add_run(f" Pages citées : {', '.join(map(str, b.pages_citees))}.")

    def annexes(self) -> None:
        removed = list(dict.fromkeys([r for s in self.cp.sequences for r in s.retires] + self.cp.retires))
        notes = self.cp.remarques + [f"Séquence {i} : {r}" for i, s in enumerate(self.cp.sequences, 1)
                                     for r in s.remarques] + self.missing
        if removed:
            self.doc.add_heading("Annexe A : retiré par les contrôles", 1)
            self.doc.add_paragraph("Contenus proposés par le modèle mais non retrouvés dans leur source : "
                                   "absents du corpus.").runs[0].italic = True
            for r in removed:
                self.doc.add_paragraph(r, style="List Bullet")
        if notes:
            self.doc.add_heading("Annexe B : remarques", 1)
            for r in notes:
                self.doc.add_paragraph(r, style="List Bullet")

    def footer(self) -> None:
        p = self.doc.sections[0].footer.paragraphs[0]
        run = p.add_run("Corpus pédagogique généré par SourcIA à partir des sources citées. À relire avant diffusion.")
        run.font.size = self.Pt(8)


def corpus_to_docx(cp, path: Path, base_dir: Path | None = None) -> Path:
    """Écrit le document Word du corpus. ``base_dir`` : dossier où chercher les illustrations (chemins relatifs),
    par défaut celui du fichier Word (le dossier du corpus)."""
    path = Path(path)
    cp = type(cp).model_validate(word_safe(cp.model_dump()))     # copie nettoyée ; le corpus reste intact
    w = _Writer(cp, base_dir if base_dir is not None else path.parent)
    w.title_page()
    w.capacities()
    w.sequences()
    w.synthese()
    w.illustrations()
    w.bibliography()
    w.annexes()
    w.footer()
    path.parent.mkdir(parents=True, exist_ok=True)
    w.doc.save(str(path))
    return path
