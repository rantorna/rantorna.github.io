"""Hämtar sidor och PDF:er och gör om dem till ren text.

Vanlig HTTP först. Om sidan ser ut att kräva JavaScript (lite text) eller
blockerar enkla klienter används en headless-webbläsare som reserv.
"""
from __future__ import annotations

import io
import re
import threading
from dataclasses import dataclass, field
from urllib.parse import urljoin, urldefrag

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 rantorna-bot (+https://rantorna.github.io/om.html)"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.5"}
MIN_TEXT = 600  # färre tecken än så => troligen JS-renderad sida


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


def get(url: str, allow_browser: bool = True) -> Page:
    try:
        r = client().get(url)
        ctype = r.headers.get("content-type", "")
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            return pdf_to_page(str(r.url), r.content)
        page = html_to_page(str(r.url), r.text)
        if len(page.text) >= MIN_TEXT or not allow_browser:
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
    try:
        robots = client().get(root + "/robots.txt").text
        queue += re.findall(r"(?im)^sitemap:\s*(\S+)", robots)
    except Exception:
        pass
    if not queue:
        queue = [root + "/sitemap.xml"]
    while queue and len(urls) < limit and len(seen) < 40:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
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
