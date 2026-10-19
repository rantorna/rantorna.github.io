"""Hämtar sidor och PDF:er och gör om dem till ren text.

Vanlig HTTP först. Om sidan ser ut att kräva JavaScript (lite text) eller
blockerar enkla klienter används en headless-webbläsare som reserv.
"""
from __future__ import annotations

import io
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 rantorna-bot (+https://rantorna.github.io/om.html)"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.5"}
ROBOT = "rantorna-bot"   # namnet som regler i robots.txt matchas mot
MAX_DELAY = 10           # sekunder; högre Crawl-delay än så kortas till detta
MIN_TEXT = 600  # färre tecken än så => troligen JS-renderad sida
PCT = re.compile(r"\d+(?:[.,]\d+)?\s?%")
RATE_WORD = re.compile(r"ränta|räntan|sparränta|räntesats", re.I)


def _rates_missing(text: str) -> bool:
    return bool(RATE_WORD.search(text)) and not PCT.search(text)


COLLAPSED = re.compile(r'aria-expanded="false"[^>]*>(?:(?!</button>|</a>).){0,300}?ränt', re.I | re.S)


def _collapsed_rates(html: str) -> bool:
    """En hopfälld knapp/ruta som handlar om räntor ("Aktuella räntor för FIX-konton")."""
    return bool(COLLAPSED.search(html)) or bool(re.search(r"<details(?![^>]*\bopen\b)[^>]*>\s*<summary[^>]*>[^<]*ränt", html, re.I))


@dataclass
class Page:
    url: str
    title: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)  # (url, länktext)
    kind: str = "html"  # html | pdf
    via: str = "http"  # http | browser
    error: str | None = None


_client: httpx.Client | None = None
_local = threading.local()  # en webbläsare per tråd (Playwrights sync-API är inte trådsäkert)
_all_browsers: list = []


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30)
    return _client


def _clean_url(base: str, href: str) -> str | None:
    if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None
    url, _ = urldefrag(urljoin(base, href))
    return url if url.startswith("http") else None


def html_to_page(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        u = _clean_url(url, a["href"])
        if u:
            links.append((u, " ".join(a.get_text(" ").split())[:120]))
    title = (soup.title.get_text(strip=True) if soup.title else "")[:200]
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "template"]):
        tag.decompose()
    # Behåll tabellstruktur så att räntetabeller går att läsa.
    for tr in soup.find_all("tr"):
        cells = [" ".join(c.get_text(" ").split()) for c in tr.find_all(["td", "th"])]
        tr.replace_with(soup.new_string("\n| " + " | ".join(cells) + " |\n"))
    text = soup.get_text("\n")
    return Page(url=url, title=title, text=normalize_text(text), links=links)


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace(" ", " ").replace(" ", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out, blank = [], False
    for line in lines:
        if not line:
            if not blank and out:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    return "\n".join(out).strip()


def pdf_to_page(url: str, data: bytes) -> Page:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages[:40])
    except Exception as e:  # trasig PDF
        return Page(url=url, kind="pdf", error=f"pdf: {e}")
    return Page(url=url, title=url.rsplit("/", 1)[-1], text=normalize_text(text), kind="pdf")


def _browser_get(url: str) -> Page:
    from playwright.sync_api import sync_playwright

    if getattr(_local, "browser", None) is None:
        _local.pw = sync_playwright().start()
        _local.browser = _local.pw.chromium.launch()
        _all_browsers.append((_local.pw, _local.browser))
    ctx = _local.browser.new_context(user_agent=UA, locale="sv-SE")
    page = ctx.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2500)
        # Klicka bort cookie-banners om de täcker innehållet (neka icke-nödvändiga).
        for label in ["Endast nödvändiga", "Neka", "Avvisa", "Reject", "Godkänn nödvändiga"]:
            try:
                page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=800)
                break
            except Exception:
                pass
        # Fäll ut dragspel/FAQ så att villkoren hamnar i texten.
        page.evaluate(
            "document.querySelectorAll('details').forEach(d=>d.open=true);"
            "document.querySelectorAll('button[aria-expanded=\"false\"]').forEach(b=>{try{b.click()}catch(e){}});"
        )
        page.wait_for_timeout(800)
        p = html_to_page(page.url, page.content())
        p.via = "browser"
        return p
    finally:
        ctx.close()


SOFT_404 = re.compile(r"sidan (hittades|finns) inte|page not found|sidan kunde inte hittas|404", re.I)


# ---------- robots.txt (RFC 9309) ----------
# Regler följs för rantorna-bot. Kan filen inte hämtas för att den saknas eller servern svarar
# 4xx finns inga regler och allt får läsas. Svarar servern 5xx eller går den inte att nå, läser
# vi ingenting på den webbplatsen i den här körningen (sidorna från förra körningen står kvar).

@dataclass
class _Robots:
    parser: RobotFileParser | None   # None = inga regler
    blocked: bool = False            # webbplatsen nåddes inte – läs inget
    delay: float = 0.0
    text: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)
    last: float = 0.0


_robots: dict[str, _Robots] = {}
_robots_lock = threading.Lock()


def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}".lower()


def robots(url: str) -> _Robots:
    origin = _origin(url)
    with _robots_lock:
        if origin in _robots:
            return _robots[origin]
    try:
        r = client().get(origin + "/robots.txt")
        if r.status_code >= 500:
            rb = _Robots(None, blocked=True)
        elif r.status_code >= 400 or "html" in r.headers.get("content-type", "") and "<html" in r.text[:500].lower():
            rb = _Robots(None)  # saknas (eller en felsida som serveras som 200)
        else:
            p = RobotFileParser()
            p.parse(r.text.splitlines())
            d = p.crawl_delay(ROBOT) or 0
            rb = _Robots(p, delay=min(float(d), MAX_DELAY), text=r.text)
    except Exception:
        rb = _Robots(None, blocked=True)
    with _robots_lock:
        return _robots.setdefault(origin, rb)


def allowed(url: str) -> bool:
    rb = robots(url)
    if rb.blocked:
        return False
    return rb.parser is None or rb.parser.can_fetch(ROBOT, url)


def _wait_turn(url: str) -> None:
    """Håller webbplatsens Crawl-delay mellan våra hämtningar."""
    rb = robots(url)
    if not rb.delay:
        return
    with rb.lock:
        wait = rb.last + rb.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        rb.last = time.monotonic()


def _soft_404(page: Page) -> bool:
    """En kort sida som säger att den inte finns, fast servern svarade 200."""
    return len(page.text) < 2500 and bool(SOFT_404.search(page.title + " " + page.text[:600]))


def get(url: str, allow_browser: bool = True, rich: bool = False) -> Page:
    """rich=True: hämta även via webbläsaren och behåll versionen med flest räntor
    (för huvudsidan med räntor, där tabeller ofta laddas med JavaScript)."""
    if not allowed(url):
        why = "webbplatsen svarar inte" if robots(url).blocked else "robots.txt tillåter inte automatisk läsning"
        return Page(url=url, error=why)
    _wait_turn(url)
    page = _get(url, allow_browser)
    if rich and allow_browser and page.via != "browser":
        try:
            bp = _browser_get(url)
            if not bp.error and len(PCT.findall(bp.text)) > len(PCT.findall(page.text)):
                page = bp
        except Exception:
            pass
    if not page.error and _soft_404(page):
        page.error = "sidan finns inte (soft 404)"
    return page


def _get(url: str, allow_browser: bool = True) -> Page:
    try:
        r = client().get(url)
        ctype = r.headers.get("content-type", "")
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            return pdf_to_page(str(r.url), r.content)
        page = html_to_page(str(r.url), r.text)
        if not allow_browser:
            return page
        if len(page.text) >= MIN_TEXT and not _rates_missing(page.text) and not _collapsed_rates(r.text):
            return page
        # Sidan talar om ränta men visar ingen procentsats – troligen ritas
        # räntan upp med JavaScript. Prova webbläsaren och behåll den bästa.
        try:
            bp = _browser_get(url)
            if not bp.error and len(PCT.findall(bp.text)) > len(PCT.findall(page.text)):
                return bp
        except Exception:
            pass
        if len(page.text) >= MIN_TEXT:
            return page
    except Exception as e:
        if not allow_browser:
            return Page(url=url, error=str(e)[:200])
    try:
        return _browser_get(url)
    except Exception as e:
        return Page(url=url, error=f"browser: {str(e)[:200]}")


def sitemap_urls(homepage: str, limit: int = 5000) -> list[str]:
    """Samlar URL:er från robots.txt/sitemap.xml (inkl. sitemap-index)."""
    root = re.match(r"https?://[^/]+", homepage).group(0)
    queue, seen, urls = [], set(), []
    queue += re.findall(r"(?im)^sitemap:\s*(\S+)", robots(root).text)
    if not queue:
        queue = [root + "/sitemap.xml"]
    while queue and len(urls) < limit and len(seen) < 40:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        if not allowed(sm):
            continue
        try:
            body = client().get(sm).text
        except Exception:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
        if "<sitemapindex" in body:
            queue += locs
        else:
            urls += locs
    return urls[:limit]


def close():
    """Stänger webbläsaren i den aktuella tråden."""
    if getattr(_local, "browser", None) is not None:
        try:
            _local.browser.close()
            _local.pw.stop()
        except Exception:
            pass
        _local.browser = _local.pw = None
