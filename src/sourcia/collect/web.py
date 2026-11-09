"""Collecte web (M1) : trouver les PDF d'un site, poliment.

Stratégie (les plans de site sont souvent incomplets, constat du kick-off) :
1. plans de site : ceux déclarés dans robots.txt, puis /sitemap.xml (et les index de plans) ;
2. exploration : pages HTML du même site, en largeur, jusqu'à ``max_pages_per_site`` ;
3. on garde les liens vers des PDF, avec le texte du lien comme titre provisoire.

Politesse : robots.txt respecté, un délai entre deux requêtes, un User-Agent explicite.
"""
from __future__ import annotations

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
        (ex. ``"fourrage|prairie|sorgho"``)."""
        host = urlparse(start_url).netloc
        root = f"{urlparse(start_url).scheme}://{host}"
        source = source or host.removeprefix("www.")
        report = CrawlReport(site=source)
        inc = re.compile(include, re.I) if include else None
        pdfs: dict[str, str] = {}
        media: dict[str, tuple] = {}
        queue: deque[str] = deque([start_url])
        seen: set[str] = {start_url}
        with span("collect.crawl", site=source):
            self.allowed(start_url)
            for sm in self.sitemaps(root):                    # 1. plans de site
                for url in self._sitemap_urls(sm, report, depth=0):
                    if PDF_RE.search(url):
                        pdfs.setdefault(url, "")
                    elif urlparse(url).netloc == host and url not in seen:
                        seen.add(url)
                        queue.append(url)
            while queue and report.pages_visited < self.cfg.max_pages_per_site \
                    and len(pdfs) < self.cfg.max_pdfs_per_site:             # 2. exploration
                url = queue.popleft()
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
                    pdfs.setdefault(url, "")
                    continue
                if r.status_code != 200 or "html" not in ctype:
                    continue
                if medias:
                    for murl, mtitle, mkind in parse_media(r.text, url):
                        media.setdefault(murl, (mtitle, mkind, url, _page_title(r.text)))
                for link, text in parse_links(r.text, url):
                    if PDF_RE.search(link):
                        if not pdfs.get(link):
                            pdfs[link] = text
                    elif urlparse(link).netloc == host and link not in seen and not SKIP_RE.search(link):
                        seen.add(link)
                        queue.append(link)
        docs = []
        for url, text in list(pdfs.items())[: self.cfg.max_pdfs_per_site]:
            if inc and not (inc.search(url) or inc.search(text or "")):
                continue
            docs.append(Document(id=doc_id_for(url), url=url, source=source, title=text or _title_from_url(url)))
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
    return " ".join(m.group(1).split())[:200] if m else ""


def _title_from_url(url: str) -> str:
    name = Path(urlparse(url).path).stem
    return re.sub(r"[-_]+", " ", name).strip()
