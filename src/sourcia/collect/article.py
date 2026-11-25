"""Texte d'un article web (M1) : le corps de l'article seul, sans menus, encadrés ni « articles liés ».

Pourquoi : sur une page d'article, le bloc principal contient aussi les résumés d'autres articles
(« Sur le même sujet »), l'agenda, des publicités. Si on gardait tout, la qualification pourrait
prendre comme preuve une phrase d'un AUTRE article. On garde donc l'élément ``<article>`` (ou
``<main>``) qui contient le plus de texte, sans ses parties annexes.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

# éléments jamais gardés, et classes CSS des parties annexes (articles liés, partage, commentaires…)
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "button",
             "iframe", "template", "select"}
SKIP_CLASS_RE = re.compile(r"related|sharer|share|social|comment|sidebar|breadcrumb|newsletter|card|teaser"
                           r"|cookie|menu|pager|pagination|tags\b|items-news|\bagenda\b", re.I)
# titre d'une liste d'autres articles en fin de page : le texte s'arrête là (ex. chambres-agriculture.fr)
RELATED_HEADING_RE = re.compile(r"^(dans le même thème|sur le même (sujet|thème)|à lire aussi|a lire aussi|lire aussi"
                                r"|voir aussi|articles? liés?|actualités liées|ces articles peuvent vous intéresser"
                                r"|vous aimerez aussi|nos autres actualités)\b", re.I)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
             "track", "wbr"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "li", "ul", "ol", "table", "tr", "h1", "h2", "h3", "h4",
              "h5", "h6", "blockquote", "figure", "figcaption", "dl", "dt", "dd", "pre"}


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool, int | None]] = []   # (balise, ignorée, n° de conteneur)
        self.containers: list[list[str]] = [[]]               # 0 = toute la page ; puis chaque <article>/<main>

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if tag == "br":
                self._add("\n")
            return
        cls = dict(attrs).get("class") or ""
        skip = bool(self.stack and self.stack[-1][1]) or tag in SKIP_TAGS or bool(SKIP_CLASS_RE.search(cls))
        idx = None
        if tag in ("article", "main") and not skip:
            idx = len(self.containers)
            self.containers.append([])
        self.stack.append((tag, skip, idx))
        if tag in BLOCK_TAGS:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in BLOCK_TAGS:
            self._add("\n")
        for i in range(len(self.stack) - 1, -1, -1):          # HTML mal fermé : on remonte jusqu'à la balise
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self._add(data)

    def _add(self, text: str) -> None:
        if self.stack and self.stack[-1][1]:
            return
        idx = next((i for _, _, i in reversed(self.stack) if i is not None), 0)
        self.containers[idx].append(text)


def _tidy(parts: list[str]) -> str:
    lines = [" ".join(line.split()) for line in "".join(parts).splitlines()]
    words = 0
    for i, line in enumerate(lines):                   # « Dans le même thème… » : la suite parle d'autres articles
        if words >= 50 and RELATED_HEADING_RE.match(line):
            lines = lines[:i]
            break
        words += len(line.split())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def main_text(page: str) -> str:
    """Texte du corps de l'article : le conteneur (<article>, <main>, sinon la page) le plus fourni."""
    p = _ArticleParser()
    try:
        p.feed(page or "")
        p.close()
    except Exception:
        pass
    texts = [_tidy(c) for c in p.containers]
    candidates = texts[1:] if any(len(t.split()) >= 50 for t in texts[1:]) else texts
    return max(candidates, key=lambda t: len(t.split()), default="")


_DATE_PATTERNS = [
    r'<meta[^>]+(?:property|name|itemprop)="(?:og:)?(?:article:published_time|datePublished|dcterms\.date|DC\.date|date)"'
    r'[^>]*content="(\d{4}-\d{2}-\d{2})',
    r'<meta[^>]+content="(\d{4}-\d{2}-\d{2})[^"]*"[^>]+(?:property|name)="(?:og:)?article:published_time"',
    r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})',
    r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2})',
]


_MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
           "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}
_FR_DATE_RE = re.compile(r"(?:publié(?:e)? le|date de publication\s*:?)\s+(?:(\d{1,2})(?:er)?\s+)?("
                         + "|".join(_MONTHS) + r")\s+(\d{4})", re.I)


def published_date(page: str) -> str | None:
    """Date de publication déclarée par la page : AAAA-MM-JJ, ou AAAA si seuls le mois et l'année sont écrits.

    D'abord les balises standard (``article:published_time``, ``datePublished``, ``<time>``), sinon la
    mention écrite en français (« Publié le 25 mars 2019 », « Date de publication octobre 2022 »).
    Une date de mise à jour n'est pas une date de publication : elle est ignorée."""
    for pat in _DATE_PATTERNS:
        m = re.search(pat, page or "", re.I)
        if m:
            return m.group(1)
    text = " ".join(html.unescape(re.sub(r"(?s)<[^>]+>", " ", page or "")).split())
    m = _FR_DATE_RE.search(text)
    if not m:
        return None
    day, month, year = m.group(1), _MONTHS[m.group(2).lower()], m.group(3)
    return f"{year}-{month:02d}-{int(day):02d}" if day else year
