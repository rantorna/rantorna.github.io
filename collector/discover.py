"""Hittar en banks sidor om sparkonton och villkor – utan bankspecifik kod.

1. Kandidater från sitemap, startsidor och länkar ett steg bort.
2. Grov poängsättning på URL och länktext.
3. Claude väljer de mest relevanta (om LLM finns), annars toppen av listan.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

from . import fetch, llm, segments

POS = {
    "sparkonto": 6, "sparkonton": 6, "spar": 3, "spara": 3, "ranta": 4, "rantor": 4,
    "inlaning": 5, "fastranta": 5, "fastrantekonto": 6, "savings": 4, "saving": 3,
    "deposit": 3, "rantekonto": 5, "kapitalkonto": 4, "e-kapitalkonto": 5, "placeringskonto": 4,
    "villkor": 2, "prislista": 2, "allmanna-villkor": 3, "bundet": 3, "insattningsgaranti": 3,
}
NEG = {
    "lan": -4, "bolan": -5, "privatlan": -5, "billan": -5, "kredit": -3, "kort": -3,
    "forsakring": -5, "fond": -3, "fonder": -3, "pension": -4, "aktie": -3, "aktier": -3,
    "foretag": -4, "business": -4, "jobb": -6, "karriar": -6, "press": -5, "nyheter": -4,
    "news": -4, "investor": -6, "ir": -3, "blogg": -3, "blog": -3, "en": -2, "fi": -2,
    "no": -2, "dk": -2, "de": -2, "cookie": -6, "integritet": -4, "kontakt": -2,
    "login": -6, "logga-in": -6, "app": -1, "faktura": -3, "handla": -3, "shop": -4,
    "ordlista": -5, "kunskap": -3, "guide": -2, "fragor": -2, "faq": -2, "form-builder": -8,
    "step": -4, "pressrum": -5, "pressmeddelanden": -5, "rantehistorik": -2, "barn": -2,
    "anvandarvillkor": -4, "tidigare": -5, "easycredit": -4, "kids": -3, "teens": -3, "pro": -2, "cashback": -4, "membership": -4, "rewards": -4,
}
LOCALE = re.compile(r"^/([a-z]{2}(?:-[a-z]{2})?)(?:/|$)", re.I)
APP_HOSTS = re.compile(r"^(online|app|login|secure|internetbank|ib)\.", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def score(url: str, label: str = "") -> int:
    path = _norm(urlparse(url).path + " " + label)
    tokens = [t for t in re.split(r"[^a-z0-9-]+", path) if t]
    parts = set(tokens) | {p for t in tokens for p in t.split("-")}
    pos = POS | segments.cur().pos
    neg = {k: v for k, v in NEG.items() if k not in segments.cur().pos}
    s = sum(pos.get(p, 0) for p in parts) + sum(neg.get(p, 0) for p in parts)
    if url.lower().endswith(".pdf"):
        s += 1
    depth = len([x for x in urlparse(url).path.split("/") if x])
    s += 2 if depth <= 3 else 0
    return s


def canonical(url: str) -> str:
    """Utan query/fragment – samma sida med spårningsparametrar ska bara räknas en gång."""
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}{u.path}"


def same_site(url: str, homepage: str) -> bool:
    """Samma domän, inte inloggningsappen, och samma språk-/landsprefix som
    startsidan (klarna.com/se/ men inte klarna.com/ie/)."""
    def base(u):
        host = urlparse(u).netloc.lower().removeprefix("www.")
        return ".".join(host.split(".")[-2:])
    if base(url) != base(homepage) or APP_HOSTS.match(urlparse(url).netloc):
        return False
    home_loc = LOCALE.match(urlparse(homepage).path)
    if home_loc:
        loc = LOCALE.match(urlparse(url).path)
        return bool(loc) and loc.group(1).lower() == home_loc.group(1).lower()
    return True


def candidates(bank: dict, log=print) -> dict[str, str]:
    """Returnerar {url: etikett} för troliga spar-/villkorssidor."""
    home = bank["homepage"]
    found: dict[str, str] = {}
    for u in fetch.sitemap_urls(home):
        if same_site(u, home):
            found.setdefault(canonical(u), "")
    log(f"  sitemap: {len(found)} url:er")
    seeds = list(dict.fromkeys(bank.get("start_urls", []) + [home]))
    for s in seeds:
        p = fetch.get(s)
        if p.error:
            log(f"  ! {s}: {p.error}")
            continue
        found.setdefault(p.url, p.title)
        for u, label in p.links:
            u = canonical(u)
            if same_site(u, home) and not found.get(u):
                found[u] = label
    # Ett steg till från de bästa länkarna (fångar undersidor som inte finns i sitemap).
    top = sorted(found, key=lambda u: -score(u, found[u]))[:6]
    for u in top:
        if u in seeds or score(u, found[u]) < 4:
            continue
        p = fetch.get(u, allow_browser=False)
        for v, label in p.links:
            v = canonical(v)
            if same_site(v, home) and not found.get(v):
                found[v] = label
    return found


def choose(bank: dict, found: dict[str, str], max_pages: int = 8, log=print) -> list[str]:
    ranked = sorted(found, key=lambda u: -score(u, found[u]))
    shortlist = [u for u in ranked if score(u, found[u]) > 0][:60]
    forced = list(bank.get("start_urls", []))
    if not shortlist:
        return forced[:max_pages]
    if llm.available() and not llm.limit_hit:
        listing = "\n".join(f"{i}. {u}  [{found[u][:80]}]" for i, u in enumerate(shortlist))
        try:
            res = llm.json_call(
                task="choose_pages",
                system=segments.cur().choose_system,
                user=f"Bank: {bank['name']}\nKandidater:\n{listing}\n\nVälj högst {max_pages} index, viktigast först.",
                schema={
                    "type": "object",
                    "properties": {"indices": {"type": "array", "items": {"type": "integer"}}},
                    "required": ["indices"],
                    "additionalProperties": False,
                },
                cheap=True,
            )
        except llm.LLMError:
            res = {"indices": list(range(len(shortlist)))}
        picked = [shortlist[i] for i in res.get("indices", []) if 0 <= i < len(shortlist)]
    else:
        picked = shortlist
    out = list(dict.fromkeys(forced + picked))[:max_pages]
    log(f"  valda sidor: {len(out)}")
    return out


def linked_terms(pages: list[fetch.Page], home: str, already: set[str], limit: int = 4) -> list[str]:
    """PDF:er och villkorssidor som de valda sidorna länkar till."""
    cands = {}
    for p in pages:
        for u, label in p.links:
            if u in already or not same_site(u, home) and not u.lower().endswith(".pdf"):
                continue
            if re.search(segments.cur().terms_re, _norm(u + " " + label), re.I) and (
                u.lower().endswith(".pdf") or "villkor" in _norm(u + label)
            ):
                if score(u, label) > 0:
                    cands[u] = score(u, label)
    return sorted(cands, key=lambda u: -cands[u])[:limit]
