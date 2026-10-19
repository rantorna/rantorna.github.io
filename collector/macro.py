"""Det allmänna ränteläget ur officiella källor – ingen AI inblandad.

    python -m collector.macro

Skriver data/macro.json. Källor: Riksbanken (SWEA + SWESTR), ECB Data Portal,
New York Fed (EFFR, SOFR, Feds målintervall) och US Treasury (avkastningskurvan).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import time
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parent.parent / "data"
START = dt.date(2019, 1, 1)
DAILY_DAYS = 400  # äldre än så glesas ut till en observation per vecka
UA = {"User-Agent": "rantorna (+https://rantorna.github.io/om.html)"}

# id: (region, grupp, namn, löptid i månader för kurvan eller None, källa, nyckel)
SERIES = {
    # Sverige
    "se_policy": ("SE", "styr", "Styrränta (Riksbanken)", None, "riksbank", "SECBREPOEFF"),
    "se_swestr": ("SE", "kort", "SWESTR (dagslåneränta)", 0, "swestr", "SWESTR"),
    "se_tb3m": ("SE", "kort", "Statsskuldväxel 3 mån", 3, "riksbank", "SETB3MBENCH"),
    "se_gvb2y": ("SE", "lång", "Statsobligation 2 år", 24, "riksbank", "SEGVB2YC"),
    "se_gvb5y": ("SE", "lång", "Statsobligation 5 år", 60, "riksbank", "SEGVB5YC"),
    "se_gvb10y": ("SE", "lång", "Statsobligation 10 år", 120, "riksbank", "SEGVB10YC"),
    "se_mb5y": ("SE", "lång", "Bostadsobligation 5 år", None, "riksbank", "SEMB5YCACOMB"),
    # Sverige – bolåneräntor (SCB, nya avtal resp. alla utestående lån, månadsvis)
    "se_mtg_new_var": ("SE", "bolån", "Nya bolån, rörlig (≤ 3 mån)", 3, "scb", "0100:1.1.1"),
    "se_mtg_new_3m1y": ("SE", "bolån", "Nya bolån, 3 mån–1 år", 12, "scb", "0100:1.1.2.1"),
    "se_mtg_new_1y2y": ("SE", "bolån", "Nya bolån, 1–2 år", 24, "scb", "0100:1.1.2.2.1.1"),
    "se_mtg_new_2y3y": ("SE", "bolån", "Nya bolån, 2–3 år", 36, "scb", "0100:1.1.2.2.1.2"),
    "se_mtg_new_3y5y": ("SE", "bolån", "Nya bolån, 3–5 år", 60, "scb", "0100:1.1.2.2.2"),
    "se_mtg_new_5y": ("SE", "bolån", "Nya bolån, över 5 år", 120, "scb", "0100:1.1.2.3"),
    "se_mtg_new_all": ("SE", "bolån", "Nya bolån, alla bindningstider", None, "scb", "0100:1"),
    "se_mtg_stock": ("SE", "bolån", "Alla utestående bolån", None, "scb", "0200:1"),
    # Sverige – lån till företag (SCB, nya och omförhandlade avtal, månadsvis)
    "se_corp_new_all": ("SE", "företag", "Nya lån till företag, alla", None, "scb_corp", "1:0100:1"),
    "se_corp_new_var": ("SE", "företag", "Nya lån till företag, rörlig (≤ 3 mån)", 3, "scb_corp", "1:0100:1.1.1"),
    "se_corp_new_1y5y": ("SE", "företag", "Nya lån till företag, 1–5 år", 36, "scb_corp", "1:0100:1.1.2.2"),
    "se_corp_kontokredit": ("SE", "företag", "Kontokredit till företag (utestående)", None, "scb_corp", "1:0200:1.2"),
    "se_soletrader_new_all": ("SE", "företag", "Nya lån till enskilda näringsidkare", None, "scb_corp", "2.1:0100:1"),
    # Sverige – bankernas inlåningsräntor (SCB, utestående avtal, månadsvis)
    "se_dep_hh_all": ("SE", "inlåning", "Hushållens inlåning i bank, alla konton", None, "scb_dep", "2:0200:1"),
    "se_dep_hh_free": ("SE", "inlåning", "Hushållens inlåning, konton utan villkor", None, "scb_dep", "2:0200:3"),
    "se_dep_hh_fixed": ("SE", "inlåning", "Hushållens inlåning, bundet upp till 2 år", 24, "scb_dep", "2:0200:211"),
    "se_dep_corp_all": ("SE", "inlåning", "Företagens inlåning i bank, alla konton", None, "scb_dep", "1:0200:1"),
    # Sverige – konsumtionslån till hushåll (SCB, banker och andra MFI, månadsvis)
    "se_consumer_new": ("SE", "konsumtion", "Nya konsumtionslån till hushåll", None, "scb_purpose", "0300:1.1"),
    "se_consumer_stock": ("SE", "konsumtion", "Alla utestående konsumtionslån", None, "scb_purpose", "0400:1.1"),
    # Sverige – officiella räntor och inflation
    "se_slr": ("SE", "officiell", "Statslåneränta", None, "riksgalden", "slr"),
    "se_ref": ("SE", "officiell", "Referensränta", None, "riksbank_ref", "SECBREFEFF"),
    "se_drojsmal": ("SE", "officiell", "Dröjsmålsränta", None, "derived", "se_ref+8"),
    "se_skv_bas": ("SE", "officiell", "Skattekontot, basränta", None, "skv", "bas"),
    "se_skv_intakt": ("SE", "officiell", "Skattekontot, intäktsränta (skattefri)", None, "skv", "intakt"),
    "se_skv_kost_lag": ("SE", "officiell", "Skattekontot, låg kostnadsränta", None, "skv", "kost_lag"),
    "se_skv_kost_hog": ("SE", "officiell", "Skattekontot, hög kostnadsränta", None, "skv", "kost_hog"),
    "se_isk_schablon": ("SE", "officiell", "ISK/KF, schablonränta för året", None, "isk", "schablon"),
    "se_isk_skatt": ("SE", "officiell", "ISK/KF, skatt på kapitalunderlaget", None, "isk", "skatt"),
    "se_isk_grund": ("SE", "officiell", "ISK/KF/PEPP, skattefri grundnivå (kr)", None, "isk", "grund"),
    "se_csn": ("SE", "officiell", "CSN studielån", None, "csn", "studielan"),
    "se_csn_aterkrav": ("SE", "officiell", "CSN, ränta på återkrav", None, "csn", "aterkrav"),
    "se_kpif": ("SE", "inflation", "Inflation, KPIF (12 mån)", None, "scb_kpif", "000007ZM"),
    # Euroområdet
    "eu_dfr": ("EU", "styr", "Inlåningsränta (ECB)", None, "ecb", "FM/D.U2.EUR.4F.KR.DFR.LEV"),
    "eu_estr": ("EU", "kort", "€STR (dagslåneränta)", 0, "ecb", "EST/B.EU000A2X2A25.WT"),
    "eu_y3m": ("EU", "kort", "Statspapper AAA 3 mån", 3, "ecb", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_3M"),
    "eu_y2y": ("EU", "lång", "Statsobligation AAA 2 år", 24, "ecb", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y"),
    "eu_y5y": ("EU", "lång", "Statsobligation AAA 5 år", 60, "ecb", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y"),
    "eu_y10y": ("EU", "lång", "Statsobligation AAA 10 år", 120, "ecb", "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y"),
    # USA
    "us_fed_upper": ("US", "styr", "Styrränta (Fed, övre gräns)", None, "nyfed_target", "effr"),
    "us_effr": ("US", "kort", "EFFR (dagslåneränta)", 0, "nyfed", "unsecured/effr"),
    "us_sofr": ("US", "kort", "SOFR", None, "nyfed", "secured/sofr"),
    "us_t3m": ("US", "kort", "Statsskuldväxel 3 mån", 3, "treasury", "3 Mo"),
    "us_t2y": ("US", "lång", "Statsobligation 2 år", 24, "treasury", "2 Yr"),
    "us_t5y": ("US", "lång", "Statsobligation 5 år", 60, "treasury", "5 Yr"),
    "us_t10y": ("US", "lång", "Statsobligation 10 år", 120, "treasury", "10 Yr"),
    "us_t30y": ("US", "lång", "Statsobligation 30 år", 360, "treasury", "30 Yr"),
}

SOURCES = {
    "riksbank": ("Riksbanken", "https://www.riksbank.se/sv/statistik/rantor-och-valutakurser/"),
    "swestr": ("Riksbanken", "https://www.riksbank.se/sv/statistik/rantor-och-valutakurser/swestr/"),
    "ecb": ("ECB", "https://data.ecb.europa.eu/"),
    "nyfed": ("Federal Reserve Bank of New York", "https://www.newyorkfed.org/markets/reference-rates"),
    "nyfed_target": ("Federal Reserve Bank of New York", "https://www.newyorkfed.org/markets/reference-rates/effr"),
    "riksgalden": ("Riksgälden", "https://www.riksgalden.se/var-verksamhet/statslanerantan/statslanerantan-per-vecka/"),
    "riksbank_ref": ("Riksbanken", "https://www.riksbank.se/sv/statistik/rantor-och-valutakurser/referensranta-och-diskonto/"),
    "derived": ("Räntelagen (referensräntan + 8 procentenheter)", "https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/rantelag-1975635_sfs-1975-635/"),
    "skv": ("Skatteverket", "https://www.skatteverket.se/rantesatser"),
    "isk": ("Skatteverket", "https://www.skatteverket.se/privat/skatter/vardepapper/investeringssparkontoisk"),
    "csn": ("CSN", "https://www.csn.se/betala-tillbaka/betala-tillbaka-studielan/ranta-och-avgifter.html"),
    "scb_dep": ("SCB", "https://www.scb.se/hitta-statistik/statistik-efter-amne/finansmarknad/finansmarknadsstatistik/"),
    "scb_purpose": ("SCB", "https://www.scb.se/hitta-statistik/statistik-efter-amne/finansmarknad/finansmarknadsstatistik/"),
    "scb_corp": ("SCB", "https://www.scb.se/hitta-statistik/statistik-efter-amne/finansmarknad/finansmarknadsstatistik/"),
    "scb_kpif": ("SCB", "https://www.scb.se/hitta-statistik/statistik-efter-amne/priser-och-konsumtion/konsumentprisindex/"),
    "scb": ("SCB", "https://www.scb.se/hitta-statistik/statistik-efter-amne/finansmarknad/finansmarknadsstatistik/"),
    "treasury": ("U.S. Department of the Treasury", "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics"),
}


def get(url: str, **kw) -> httpx.Response:
    """GET med väntan vid 429/5xx (Riksbanken begränsar hårt utan nyckel). Följer robots.txt."""
    from .fetch import allowed
    if not allowed(url):
        raise PermissionError(f"robots.txt tillåter inte {url}")
    for attempt in range(8):
        r = httpx.get(url, headers=UA, timeout=60, follow_redirects=True, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(min(90, 15 * (attempt + 1)))
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def fetch_riksbank(key):
    today = dt.date.today()
    r = get(f"https://api.riksbank.se/swea/v1/Observations/{key}/{START}/{today}")
    time.sleep(13)
    return [(o["date"], float(o["value"])) for o in r.json() if o.get("value") is not None]


def fetch_swestr(key):
    r = get(f"https://api.riksbank.se/swestr/v1/all/{key}", params={"fromDate": START.isoformat()})
    time.sleep(13)
    return [(o["date"], float(o["rate"])) for o in r.json() if o.get("rate") is not None]


def fetch_ecb(key):
    r = get(f"https://data-api.ecb.europa.eu/service/data/{key}",
            params={"format": "csvdata", "startPeriod": START.isoformat(), "detail": "dataonly"})
    rows = csv.DictReader(io.StringIO(r.text))
    return [(row["TIME_PERIOD"], float(row["OBS_VALUE"])) for row in rows if row.get("OBS_VALUE")]


def _nyfed(path):
    r = get(f"https://markets.newyorkfed.org/api/rates/{path}/search.json",
            params={"startDate": START.isoformat(), "endDate": dt.date.today().isoformat()})
    return r.json()["refRates"]


def fetch_nyfed(key):
    return sorted((x["effectiveDate"], float(x["percentRate"])) for x in _nyfed(key))


def fetch_nyfed_target(key):
    return sorted((x["effectiveDate"], float(x["targetRateTo"])) for x in _nyfed(f"unsecured/{key}")
                  if x.get("targetRateTo") is not None)


_scb_cache: dict[str, list] = {}


def fetch_scb(key):
    """SCB tabell RantaT04N: bolåneräntor till hushåll (MFI + bostadskreditinstitut)."""
    if not _scb_cache:
        q = {"query": [
            {"code": "Referenssektor", "selection": {"filter": "item", "values": ["1"]}},
            {"code": "Motpartssektor", "selection": {"filter": "item", "values": ["2c"]}},
            {"code": "Avtal", "selection": {"filter": "item", "values": ["0100", "0200"]}},
            {"code": "Tid", "selection": {"filter": "all", "values": ["*"]}},
        ], "response": {"format": "json"}}
        r = httpx.post("https://api.scb.se/OV0104/v1/doris/sv/ssd/FM/FM5001/FM5001C/RantaT04N",
                       json=q, headers=UA, timeout=120)
        r.raise_for_status()
        for row in r.json()["data"]:
            _, _, avtal, bind, month = row["key"]
            v = row["values"][0]
            if v in ("..", "", None) or month < f"{START.year}M01":
                continue
            date = f"{month[:4]}-{month[5:]}-01"
            _scb_cache.setdefault(f"{avtal}:{bind}", []).append((date, float(v)))
    return sorted(_scb_cache.get(key, []))


# ---------- officiella räntor ----------

PREV: dict = {}  # förra körningens serier – sidor utan historik byggs upp en observation i taget
MONTHS = {m: i + 1 for i, m in enumerate(["januari", "februari", "mars", "april", "maj", "juni", "juli",
                                          "augusti", "september", "oktober", "november", "december"])}


def _num(s: str) -> float:
    return float(s.replace("\xa0", "").replace(" ", "").replace(",", "."))


def _sv_date(s: str) -> str:
    d, m, y = s.split()
    return dt.date(int(y), MONTHS[m.lower()], int(d)).isoformat()


def _page_text(url: str) -> str:
    import html as _html
    import re as _re

    t = get(url).text
    t = _re.sub(r"<(script|style)[^>]*>.*?</\1>", "", t, flags=_re.S)
    t = _html.unescape(_re.sub(r"<[^>]+>", " ", t))
    return " ".join(t.replace("\xa0", " ").split())


def _accumulate(sid: str, date: str, value: float) -> list:
    """Lägg till observationen i förra körningens historik (sidan visar bara nuläget)."""
    obs = {d: v for d, v in (PREV.get(sid, {}).get("obs") or [])}
    obs[date] = value
    return sorted(obs.items())


def fetch_riksgalden(key):
    r = get("https://www.riksgalden.se/globalassets/dokument_sve/statslaneranta/statslanerantor.csv")
    rows = csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";")
    next(rows)
    out = [(d, _num(v)) for d, v, *_ in rows if d[:4].isdigit() and d >= START.isoformat() and v.strip()]
    return sorted(out)


def fetch_riksbank_ref(key):
    obs = fetch_riksbank(key)
    # Referensräntan sätts halvårsvis; behåll bara datumen då den ändrades, plus senaste dagen.
    out = [o for i, o in enumerate(obs) if i == 0 or o[1] != obs[i - 1][1]]
    return out + ([obs[-1]] if obs and out[-1] != obs[-1] else [])


_skv: dict = {}


def fetch_skv(key):
    import re as _re

    if not _skv:
        t = _page_text("https://www.skatteverket.se/rantesatser")
        m = _re.search(r"Basräntan på skattekontot är ([\d,]+) procent från och med (\d{1,2} \w+ \d{4})", t)
        if not m:
            raise ValueError("Skatteverket: hittar inte basräntan på sidan")
        date = _sv_date(m.group(2))
        _skv["bas"] = (date, _num(m.group(1)))
        if (mi := _re.search(r"(?:intäktsräntan (?:är|blir)|är intäktsräntan) ([\d,]+) procent", t)):
            _skv["intakt"] = (date, _num(mi.group(1)))
        if (mk := _re.search(r"låga kostnadsräntan ([\d,]+) procent och den höga kostnadsräntan ([\d,]+) procent", t)):
            _skv["kost_lag"] = (date, _num(mk.group(1)))
            _skv["kost_hog"] = (date, _num(mk.group(2)))
    if key not in _skv:
        raise ValueError(f"Skatteverket: hittar inte {key}")
    return _accumulate({"bas": "se_skv_bas", "intakt": "se_skv_intakt", "kost_lag": "se_skv_kost_lag",
                        "kost_hog": "se_skv_kost_hog"}[key], *_skv[key])


_isk: dict = {}


def fetch_isk(key):
    """Schablonränta, skatt och skattefri grundnivå för det senaste inkomståret som Skatteverket beskriver."""
    import re as _re

    if not _isk:
        t = _page_text("https://www.skatteverket.se/privat/skatter/vardepapper/investeringssparkontoisk")
        hits = _re.findall(r"schablonintäkten för inkomståret (\d{4}) blir ([\d,]+) procent.{0,400}?din skatt blir ([\d,]+) procent"
                           r".{0,200}?grundnivån på ([\d  ]+) kronor", t)
        if not hits:
            raise ValueError("Skatteverket: hittar inte schablonintäkten för ISK")
        year, schablon, skatt, grund = max(hits, key=lambda h: h[0])
        date = f"{year}-01-01"
        _isk.update(schablon=(date, _num(schablon)), skatt=(date, _num(skatt)), grund=(date, _num(grund)))
    return _accumulate({"schablon": "se_isk_schablon", "skatt": "se_isk_skatt", "grund": "se_isk_grund"}[key], *_isk[key])


_csn: dict = {}


def fetch_csn(key):
    import re as _re

    if not _csn:
        t = _page_text("https://www.csn.se/betala-tillbaka/betala-tillbaka-studielan/ranta-och-avgifter.html")
        m = _re.search(r"för (\d{4}) är räntan ([\d,]+) procent", t)
        if not m:
            raise ValueError("CSN: hittar inte räntan på sidan")
        _csn["studielan"] = (f"{m.group(1)}-01-01", _num(m.group(2)))
        if (ma := _re.search(r"Under (\d{4}) är räntan ([\d,]+) procent på det belopp", t)):
            _csn["aterkrav"] = (f"{ma.group(1)}-01-01", _num(ma.group(2)))
    if key not in _csn:
        raise ValueError(f"CSN: hittar inte {key}")
    return _accumulate({"studielan": "se_csn", "aterkrav": "se_csn_aterkrav"}[key], *_csn[key])


_scb_corp: dict = {}


def fetch_scb_corp(key):
    """SCB RantaT01N: utlåningsräntor till icke-finansiella företag och företagarhushåll."""
    if not _scb_corp:
        q = {"query": [
            {"code": "Referenssektor", "selection": {"filter": "item", "values": ["1"]}},
            {"code": "Motpartssektor", "selection": {"filter": "item", "values": ["1", "2.1"]}},
            {"code": "Avtal", "selection": {"filter": "item", "values": ["0100", "0200"]}},
            {"code": "Rantebindningstid", "selection": {"filter": "item", "values": ["1", "1.1.1", "1.1.2.2", "1.2"]}},
            {"code": "Tid", "selection": {"filter": "all", "values": ["*"]}},
        ], "response": {"format": "json"}}
        r = httpx.post("https://api.scb.se/OV0104/v1/doris/sv/ssd/FM/FM5001/FM5001C/RantaT01N", json=q, headers=UA, timeout=120)
        r.raise_for_status()
        for row in r.json()["data"]:
            _, motpart, avtal, bind, month = row["key"]
            v = row["values"][0]
            if v in ("..", "", None) or month < f"{START.year}M01":
                continue
            _scb_corp.setdefault(f"{motpart}:{avtal}:{bind}", []).append((f"{month[:4]}-{month[5:]}-01", float(v)))
    return sorted(_scb_corp.get(key, []))


_scb_dep: dict = {}


def fetch_scb_dep(key):
    """SCB RantaT05: bankernas inlåningsräntor från hushåll och företag."""
    if not _scb_dep:
        q = {"query": [{"code": "Avtal", "selection": {"filter": "item", "values": ["0200"]}},
                       {"code": "Tid", "selection": {"filter": "all", "values": ["*"]}}], "response": {"format": "json"}}
        r = httpx.post("https://api.scb.se/OV0104/v1/doris/sv/ssd/FM/FM5001/FM5001C/RantaT05", json=q, headers=UA, timeout=120)
        r.raise_for_status()
        for row in r.json()["data"]:
            _, motpart, avtal, kind, month = row["key"]
            v = row["values"][0]
            if v in ("..", "", None) or month < f"{START.year}M01":
                continue
            _scb_dep.setdefault(f"{motpart}:{avtal}:{kind}", []).append((f"{month[:4]}-{month[5:]}-01", float(v)))
    return sorted(_scb_dep.get(key, []))


_scb_purpose: dict = {}


def fetch_scb_purpose(key):
    """SCB RantaT03N: utlåningsräntor till hushåll efter ändamål (konsumtion)."""
    if not _scb_purpose:
        q = {"query": [
            {"code": "Referenssektor", "selection": {"filter": "item", "values": ["1"]}},
            {"code": "Motpartssektor", "selection": {"filter": "item", "values": ["2b"]}},
            {"code": "Avtal", "selection": {"filter": "item", "values": ["0300", "0400"]}},
            {"code": "Andamal", "selection": {"filter": "item", "values": ["1.1"]}},
            {"code": "Tid", "selection": {"filter": "all", "values": ["*"]}},
        ], "response": {"format": "json"}}
        r = httpx.post("https://api.scb.se/OV0104/v1/doris/sv/ssd/FM/FM5001/FM5001C/RantaT03N", json=q, headers=UA, timeout=120)
        r.raise_for_status()
        for row in r.json()["data"]:
            _, _, avtal, purpose, month = row["key"]
            v = row["values"][0]
            if v in ("..", "", None) or month < f"{START.year}M01":
                continue
            _scb_purpose.setdefault(f"{avtal}:{purpose}", []).append((f"{month[:4]}-{month[5:]}-01", float(v)))
    return sorted(_scb_purpose.get(key, []))


def fetch_scb_kpif(key):
    q = {"query": [{"code": "ContentsCode", "selection": {"filter": "item", "values": [key]}},
                   {"code": "Tid", "selection": {"filter": "all", "values": ["*"]}}], "response": {"format": "json"}}
    r = httpx.post("https://api.scb.se/OV0104/v1/doris/sv/ssd/PR/PR0101/PR0101G/KPIF2020", json=q, headers=UA, timeout=120)
    r.raise_for_status()
    out = []
    for row in r.json()["data"]:
        month, v = row["key"][0], row["values"][0]
        if month >= f"{START.year}M01" and v not in ("..", ""):
            out.append((f"{month[:4]}-{month[5:]}-01", float(v)))
    return sorted(out)


_treasury_cache: dict[str, list] = {}


def fetch_treasury(col):
    if not _treasury_cache:
        rows = []
        for year in range(START.year, dt.date.today().year + 1):
            r = get("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                    f"daily-treasury-rates.csv/{year}/all",
                    params={"type": "daily_treasury_yield_curve", "field_tdr_date_value": year, "_format": "csv"})
            rows += list(csv.DictReader(io.StringIO(r.text)))
        for row in rows:
            m, d, y = row["Date"].split("/")
            date = f"{y}-{m}-{d}"
            for k, v in row.items():
                if k != "Date" and v not in ("", "N/A", None):
                    _treasury_cache.setdefault(k, []).append((date, float(v)))
    return sorted(_treasury_cache.get(col, []))


def fetch_forecast() -> dict:
    """Riksbankens räntebana och marknadens förväntningar (terminsprissättning) ur de penningpolitiska
    rapporterna. Varje rapport ("policy round") är en egen årgång; vi tar den senaste och den förra."""
    r = get("https://api.riksbank.se/monetary_policy_data/v1/forecasts")
    data = {x["external_id"]: x for x in r.json()["data"]}

    def vintage(sid, back=0):
        vs = sorted(data[sid]["vintages"], key=lambda v: v["metadata"]["policy_round_end_dtm"])
        v = vs[-1 - back]
        m = v["metadata"]
        return {"round": m["policy_round"], "published": m["policy_round_end_dtm"][:10], "cutoff": m["forecast_cutoff_date"],
                "obs": [[o["dt"], o["value"]] for o in v["observations"] if o["dt"] > m["forecast_cutoff_date"] and o["value"] is not None]}

    return {"policy": vintage("SEQRATENAYNA"), "market": vintage("SEDMENAYNA"), "policy_prev": vintage("SEQRATENAYNA", 1),
            "source_url": "https://www.riksbank.se/sv/penningpolitik/penningpolitiska-rapporter-och-beslut/"}


FETCHERS = {"riksgalden": fetch_riksgalden, "riksbank_ref": fetch_riksbank_ref, "skv": fetch_skv, "isk": fetch_isk,
            "csn": fetch_csn, "scb_kpif": fetch_scb_kpif, "scb_corp": fetch_scb_corp, "scb_purpose": fetch_scb_purpose, "scb_dep": fetch_scb_dep, "scb": fetch_scb, "riksbank": fetch_riksbank, "swestr": fetch_swestr, "ecb": fetch_ecb, "nyfed": fetch_nyfed,
            "nyfed_target": fetch_nyfed_target, "treasury": fetch_treasury}


def thin(obs):
    """Dagliga värden senaste DAILY_DAYS dagarna, därefter sista observationen per vecka."""
    cutoff = (dt.date.today() - dt.timedelta(days=DAILY_DAYS)).isoformat()
    out, week = [], {}
    for d, v in obs:
        if d >= cutoff:
            out.append((d, v))
        else:
            y, w, _ = dt.date.fromisoformat(d).isocalendar()
            week[(y, w)] = (d, v)
    return sorted(week.values()) + out


def value_at(obs, date):
    """Senaste värde på eller före datumet."""
    best = None
    for d, v in obs:
        if d <= date:
            best = v
        else:
            break
    return best


def summarize(obs):
    last_d, last_v = obs[-1]
    ref = dt.date.fromisoformat(last_d)
    ago = lambda days: value_at(obs, (ref - dt.timedelta(days=days)).isoformat())
    prev = obs[-2][1] if len(obs) > 1 else None
    ch = lambda v0: None if v0 is None else round(last_v - v0, 4)
    return {"date": last_d, "value": last_v, "chg_1d": ch(prev), "chg_1m": ch(ago(30)),
            "chg_3m": ch(ago(91)), "chg_1y": ch(ago(365))}


def main():
    previous, prev_forecast = {}, None
    path = DATA / "macro.json"
    if path.exists():
        old = json.loads(path.read_text())
        previous, prev_forecast = old.get("series", {}), old.get("forecast")
    PREV.update(previous)
    out = {}
    for sid, (region, group, name, tenor, src, key) in SERIES.items():
        try:
            if src == "derived":  # dröjsmålsränta = referensränta + 8 procentenheter (räntelagen)
                base, add = key.split("+")
                obs = [(d, round(v + float(add), 4)) for d, v in out[base]["obs"]]
            else:
                obs = FETCHERS[src](key)
            if not obs:
                raise ValueError("inga observationer")
            # Månadsstatistik publiceras med eftersläpning; officiella räntor ändras sällan (datumet är när de började gälla).
            max_age = {"scb": 110, "scb_kpif": 110, "scb_corp": 110, "scb_purpose": 110, "scb_dep": 110}.get(src, None if src in ("skv", "isk", "csn", "riksbank_ref", "derived") else 30)
            if max_age and (dt.date.today() - dt.date.fromisoformat(obs[-1][0])).days > max_age:
                raise ValueError(f"senaste värdet är från {obs[-1][0]} – serien verkar ha upphört")
            out[sid] = {"region": region, "group": group, "name": name, "tenor_months": tenor,
                        "source": SOURCES[src][0], "source_url": SOURCES[src][1], "key": key,
                        "latest": summarize(obs), "obs": thin(obs)}
            print(f"  {sid}: {obs[-1]} ({len(obs)} obs)", flush=True)
        except Exception as e:  # behåll gårdagens värden hellre än att tappa serien
            print(f"  ! {sid}: {e}", flush=True)
            if sid in previous:
                out[sid] = previous[sid] | {"stale": True}
    try:
        forecast = fetch_forecast()
        print(f"  räntebana {forecast['policy']['round']} ({forecast['policy']['published']})", flush=True)
    except Exception as e:  # behåll förra prognosen hellre än ingen
        print(f"  ! räntebana: {e}", flush=True)
        forecast = prev_forecast
    path.write_text(json.dumps({"generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                                "series": out, "forecast": forecast}, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(out)}/{len(SERIES)} serier, {path.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
