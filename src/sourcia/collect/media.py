"""Ressources non textuelles (critère « types de ressources » du métier) : données, photos, vidéos, audio.

- Nature (``Document.kind``) devinée d'après l'adresse ou l'extension ;
- sur une page web : vidéos (liens et lecteurs intégrés YouTube, Vimeo, Dailymotion, .mp4…) et photos
  (balises <img> avec un texte alternatif parlant ; logos et pictogrammes ignorés) ;
- ces ressources sont indexées et qualifiées sur leurs MÉTADONNÉES (titre, texte alternatif, page d'origine,
  description du catalogue) ; un fichier audio ou vidéo local peut être transcrit si faster-whisper est installé.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "dai.ly", "canal-u.tv", "peertube")
EXT_KIND = {
    ".pdf": "pdf", ".txt": "texte", ".md": "texte", ".html": "page", ".htm": "page",
    ".csv": "donnees", ".tsv": "donnees", ".xlsx": "donnees", ".xls": "donnees", ".json": "donnees", ".geojson": "donnees",
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".gif": "image",
    ".mp4": "video", ".webm": "video", ".mov": "video", ".mkv": "video",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".ogg": "audio",
}
NOISE_IMG = re.compile(r"logo|icon|icone|picto|sprite|banner|bandeau|avatar|pixel|spacer|arrow|fleche", re.I)


def kind_of(url_or_path: str, hint: str | None = None) -> str:
    h = (hint or "").lower()
    if any(w in h for w in ("donn", "dataset", "jeu de", "data")):
        return "donnees"
    if "vid" in h:
        return "video"
    if "photo" in h or "image" in h:
        return "image"
    if "audio" in h or "podcast" in h:
        return "audio"
    u = url_or_path.lower().split("?")[0]
    if any(host in urlparse(u).netloc for host in VIDEO_HOSTS):
        return "video"
    m = re.search(r"\.[a-z0-9]{2,7}$", u)
    return EXT_KIND.get(m.group(0), "page") if m else "page"


class _MediaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items: list[tuple[str, str, str]] = []      # (url, titre, nature)
        self._a: str | None = None
        self._txt: list[str] = []
        self._caption = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._a, self._txt = a.get("href"), []
        elif tag == "img" and a.get("src"):
            alt = " ".join((a.get("alt") or a.get("title") or "").split())
            if len(alt) >= 15 and not NOISE_IMG.search(a["src"] + " " + alt):
                self.items.append((a["src"], alt, "image"))
        elif tag in ("iframe", "video", "source") and a.get("src"):
            if kind_of(a["src"]) == "video" or tag != "iframe":
                self.items.append((a["src"], a.get("title") or "", "video"))

    def handle_endtag(self, tag):
        if tag == "a" and self._a:
            if kind_of(self._a) in ("video", "audio", "donnees"):
                self.items.append((self._a, " ".join("".join(self._txt).split()), kind_of(self._a)))
            self._a = None

    def handle_data(self, data):
        if self._a is not None:
            self._txt.append(data)


def parse_media(html: str, base_url: str) -> list[tuple[str, str, str]]:
    p = _MediaParser()
    try:
        p.feed(html)
    except Exception:
        return []
    out, seen = [], set()
    for url, title, kind in p.items:
        full = urljoin(base_url, url.strip()).split("#")[0]
        if full.startswith(("http://", "https://")) and full not in seen:
            seen.add(full)
            out.append((full, title, kind))
    return out


def describe_table(path) -> str:
    """Description textuelle d'un jeu de données (colonnes, lignes, exemples) pour l'indexer et le qualifier."""
    import csv
    from pathlib import Path

    p = Path(path)
    if p.suffix.lower() in (".csv", ".tsv"):
        text = p.read_text(encoding="utf-8-sig", errors="ignore")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(text.splitlines(), dialect))
        if not rows:
            return "Jeu de données vide."
        head, body = rows[0], rows[1:]
        ex = "; ".join(f"{h} = {body[0][i]}" for i, h in enumerate(head) if body and i < len(body[0]))[:600]
        return (f"Jeu de données « {p.stem} » : {len(body)} lignes, {len(head)} colonnes.\n"
                f"Colonnes : {', '.join(head)}.\nExemple de ligne : {ex}.")
    if p.suffix.lower() == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            return f"Jeu de données « {p.stem} » (tableur ; installer openpyxl pour le décrire)."
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets[:5]:
            rows = list(ws.iter_rows(max_row=3, values_only=True))
            head = [str(c) for c in (rows[0] if rows else []) if c is not None]
            parts.append(f"Feuille « {ws.title} » : colonnes {', '.join(head)}.")
        return f"Jeu de données « {p.stem} ».\n" + "\n".join(parts)
    return f"Jeu de données « {p.stem} »."


def transcribe(path) -> str | None:
    """Transcription locale (facultative) d'un fichier audio ou vidéo avec faster-whisper. None si indisponible."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(path), language="fr")
    return " ".join(s.text.strip() for s in segments)
