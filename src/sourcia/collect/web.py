"""Collecte web (M1) : trouver les PDF d'un site, poliment.

Stratégie (les plans de site sont souvent incomplets, constat du kick-off) :
1. plans de site : ceux déclarés dans robots.txt, puis /sitemap.xml (et les index de plans) ;
2. exploration : pages HTML du même site, en largeur, jusqu'à ``max_pages_per_site`` ;
3. on garde les liens vers des PDF, avec le texte du lien comme titre provisoire.

Politesse : robots.txt respecté, un délai entre deux requêtes, un User-Agent explicite.
"""
from __future__ import annotations

import html
import re
import time
import urllib.robotparser
from collections import deque
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urldefrag, urljoin, urlparse

import requests

from sourcia.collect.store import file_sha1
from sourcia.collect.media import parse_media
from sourcia.core.models import Document, doc_id_for
from sourcia.observability.tracing import span

PDF_RE = re.compile(r"\.pdf($|\?)", re.I)
SKIP_RE = re.compile(r"\.(jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|pptx?|mp4|mp3|css|js|ico)($|\?)", re.I)
# texte de lien qui ne dit rien du document (« Télécharger », « Feuilleter la brochure »…) : on prend le titre de la page
GENERIC_LINK_RE = re.compile(r"^\W*(t[ée]l[ée]charger|feuilleter|voir|lire|consulter|ouvrir|acc[ée]der|cliquez|ici\b"
                             r"|en savoir plus|pdf\b|download|document\b|fichier\b)", re.I)


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
        if self._in_title:
            self.title += data


def parse_links(html: str, base_url: str) -> list[tuple[str, str]]:
    p = _LinkParser()
    try:
        p.feed(html)
    except Exception:
        pass
    out = []
    for href, text in p.links:
        if not href or href.startswith(("mailto:", "javascript:", "tel:")):
            continue
        out.append((urldefrag(urljoin(base_url, href))[0], text))
    return out


def parse_sitemap(xml: str) -> tuple[list[str], list[str]]:
    """Renvoie (adresses de pages, adresses de sous-plans)."""
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    if "<sitemapindex" in xml:
        return [], locs
    return locs, []


@dataclass
class CrawlReport:
    site: str
    pages_visited: int = 0
    pdfs_found: int = 0
    pdfs_new: int = 0
    downloaded: int = 0
    errors: list[str] = field(default_factory=list)
    blocked_by_robots: int = 0
    medias_found: int = 0
    start_page_empty: bool = False       # page de départ sans lien vers le site : collecte impossible en l'état


class WebCollector:
    def __init__(self, settings, fetch: Callable[[str], requests.Response] | None = None):
        self.cfg = settings.collect
        self.settings = settings
        self.session = requests.Session()
        self.session.headers["User-Agent"] = self.cfg.user_agent
        self._fetch = fetch or (lambda url: self.session.get(url, timeout=self.cfg.timeout_s))
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # ------------------------------------------------------------------ politesse
    def _wait(self, host: str) -> None:
        dt = time.monotonic() - self._last.get(host, 0)
        if dt < self.cfg.delay_s:
            time.sleep(self.cfg.delay_s - dt)
        self._last[host] = time.monotonic()

    def get(self, url: str):
        self._wait(urlparse(url).netloc)
        return self._fetch(url)

    def allowed(self, url: str) -> bool:
        if not self.cfg.respect_robots:
            return True
        root = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if root not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.get(root + "/robots.txt")
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self._robots[root] = rp
            except Exception:
                self._robots[root] = None
        rp = self._robots[root]
        return True if rp is None else rp.can_fetch(self.cfg.user_agent, url)

    def sitemaps(self, root: str) -> list[str]:
        rp = self._robots.get(root)
        declared = list(rp.site_maps() or []) if rp else []
        return declared or [root + "/sitemap.xml"]

    # ------------------------------------------------------------------ exploration
    def crawl(self, start_url: str, source: str | None = None, include: str | None = None,
              medias: bool = False) -> tuple[list[Document], CrawlReport]:
        """Trouve les PDF d'un site à partir d'une adresse de départ.

        ``include`` : expression régulière facultative pour ne garder que certaines pages ou PDF
        (ex. ``"fourrage|prairie|sorgho"``). Les pages dont l'adresse ou le texte du lien la contient
        sont visitées en premier : avec une limite de pages, l'exploration va d'abord au plus pertinent
        (un plan de site de plusieurs milliers d'adresses est souvent trié par ordre alphabétique).
        Un PDF est gardé si le filtre se retrouve dans son adresse, le texte de son lien, ou l'adresse
        ou le titre de la page où il a été trouvé (``meta`` : ``page``, ``titre_page``, ``texte_lien``)."""
        host = urlparse(start_url).netloc
        root = f"{urlparse(start_url).scheme}://{host}"
        source = source or host.removeprefix("www.")
        report = CrawlReport(site=source)
        inc = re.compile(include, re.I) if include else None
        pdfs: dict[str, dict] = {}                         # adresse du PDF → texte du lien, page, titre de la page
        media: dict[str, tuple] = {}
        first: deque[str] = deque()                        # pages qui passent le filtre : visitées d'abord
        queue: deque[str] = deque([start_url])
        seen: set[str] = {start_url}
        refused: set[str] = set()                          # PDF interdits par robots.txt (comptés une fois)

        def enqueue(url: str, text: str = "") -> None:
            seen.add(url)
            (first if inc and (inc.search(url) or inc.search(text)) else queue).append(url)

        def add_pdf(url: str, text: str = "", page: str | None = None, page_title: str = "") -> None:
            if url in refused:
                return
            if url not in pdfs and not self.allowed(url):                # robots.txt : PDF interdit
                refused.add(url)
                report.blocked_by_robots += 1
                return
            info = pdfs.setdefault(url, {"texte_lien": "", "page": None, "titre_page": ""})
            # on garde le meilleur contexte : un vrai texte de lien plutôt qu'un « Télécharger »
            better = text and (not info["texte_lien"] or (_generic_link(info["texte_lien"]) and not _generic_link(text)))
            if better or (page and not info["page"]):
                info.update(texte_lien=text or info["texte_lien"], page=page, titre_page=page_title)

        with span("collect.crawl", site=source):
            self.allowed(start_url)
            for sm in self.sitemaps(root):                    # 1. plans de site
                for url in self._sitemap_urls(sm, report, depth=0):
                    if PDF_RE.search(url):
                        add_pdf(url)
                    elif urlparse(url).netloc == host and url not in seen:
                        enqueue(url)
            while (first or queue) and report.pages_visited < self.cfg.max_pages_per_site \
                    and len(pdfs) < self.cfg.max_pdfs_per_site:             # 2. exploration
                url = first.popleft() if first else queue.popleft()
                if not self.allowed(url):
                    report.blocked_by_robots += 1
                    continue
                try:
                    r = self.get(url)
                except Exception as exc:
                    report.errors.append(f"{url} : {type(exc).__name__}")
                    continue
                report.pages_visited += 1
                ctype = r.headers.get("content-type", "")
                if "pdf" in ctype:
                    add_pdf(url)
                    continue
                if r.status_code != 200:
                    report.errors.append(f"{url} : HTTP {r.status_code}")      # lien mort ou page en erreur
                    continue
                if "html" not in ctype:
                    continue
                raw_title = _page_title(r.text)
                if medias:
                    for murl, mtitle, mkind in parse_media(r.text, url):
                        media.setdefault(murl, (mtitle, mkind, url, raw_title))
                links = parse_links(r.text, url)
                if url == start_url and not any(urlparse(link).netloc == host for link, _ in links):
                    report.start_page_empty = True                 # ex. idele.fr : « JavaScript est nécessaire »
                    report.errors.append(f"{url} : aucun lien vers {host} sur la page de départ"
                                         " (protection anti-robots ou site en JavaScript ?)")
                for link, text in links:
                    if PDF_RE.search(link):
                        add_pdf(link, text, url, _clean_title(raw_title))
                    elif urlparse(link).netloc == host and link not in seen and not SKIP_RE.search(link):
                        enqueue(link, text)
        docs = []
        for url, info in list(pdfs.items())[: self.cfg.max_pdfs_per_site]:
            text, page, page_title = info["texte_lien"], info["page"], info["titre_page"]
            if inc and not any(inc.search(x) for x in (url, text, page, page_title) if x):
                continue
            title = text if text and not _generic_link(text) else (page_title or text or _title_from_url(url))
            meta = {"page": page, "titre_page": page_title, "texte_lien": text} if page else {}
            docs.append(Document(id=doc_id_for(url), url=url, source=source, title=title, meta=meta))
        report.pdfs_found = len(docs)
        for murl, (mtitle, mkind, page, ptitle) in media.items():
            if inc and not (inc.search(murl) or inc.search(mtitle or "") or inc.search(ptitle or "")):
                continue
            docs.append(Document(id=doc_id_for(murl), url=murl, source=source, kind=mkind,
                                 title=mtitle or ptitle or _title_from_url(murl),
                                 meta={"page": page, "titre_page": ptitle}))
        report.medias_found = len(docs) - report.pdfs_found
        return docs, report

    def _sitemap_urls(self, url: str, report: CrawlReport, depth: int) -> list[str]:
        if depth > 2:
            return []
        try:
            r = self.get(url)
            if r.status_code != 200:
                return []
            pages, subs = parse_sitemap(r.text)
        except Exception as exc:
            report.errors.append(f"plan de site {url} : {type(exc).__name__}")
            return []
        for sub in subs[:50]:
            pages += self._sitemap_urls(sub, report, depth + 1)
        return pages

    # ------------------------------------------------------------------ téléchargement
    def download(self, doc: Document, directory: Path) -> Document:
        if not self.cfg.download_pdfs or doc.local_path:
            return doc
        target = directory / f"{doc.id}.pdf"
        try:
            r = self.get(doc.url)
            data = r.content
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}")
            if len(data) > self.cfg.max_pdf_mb * 1e6:
                raise RuntimeError(f"trop gros ({len(data) / 1e6:.0f} Mo)")
            if not data.startswith(b"%PDF"):
                raise RuntimeError("pas un PDF")
            directory.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            doc.local_path, doc.sha1, doc.status, doc.error = str(target), file_sha1(target), "downloaded", None
        except Exception as exc:
            doc.status, doc.error = "error", f"téléchargement : {_short_error(exc)}"
        return doc


def _short_error(exc: Exception) -> str:
    """Message court et lisible (« site injoignable (délai dépassé) » plutôt que 300 caractères de requests)."""
    name, text = type(exc).__name__, str(exc)
    if "Timeout" in name or "timed out" in text:
        return "site injoignable (délai dépassé)"
    if "ConnectionError" in name or "Max retries" in text or "NameResolution" in text:
        return "site injoignable (connexion impossible)"
    if "SSL" in name or "SSL" in text:
        return "erreur de certificat du site"
    return text[:160]


def _page_title(html_text: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html_text or "")
    return " ".join(html.unescape(m.group(1)).split())[:200] if m else ""     # « d&#039;agriculture » → « d'agriculture »


def _generic_link(text: str) -> bool:
    """Texte de lien qui ne dit rien du document (« Télécharger », « Feuilleter la brochure », « PDF »…)."""
    return len(text.strip()) < 4 or bool(GENERIC_LINK_RE.match(text))


def _clean_title(title: str) -> str:
    """Titre de page sans le nom du site (« Atlas du maïs fourrage | ARVALIS » → « Atlas du maïs fourrage »)."""
    return re.split(r"\s+[|–—]\s+", title, maxsplit=1)[0].strip()


def _title_from_url(url: str) -> str:
    name = Path(urlparse(url).path).stem
    return re.sub(r"[-_]+", " ", name).strip()
