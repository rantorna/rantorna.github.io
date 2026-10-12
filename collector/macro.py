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
    "treasury": ("U.S. Department of the Treasury", "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics"),
}


def get(url: str, **kw) -> httpx.Response:
    """GET med väntan vid 429/5xx (Riksbanken begränsar hårt utan nyckel)."""
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


FETCHERS = {"riksbank": fetch_riksbank, "swestr": fetch_swestr, "ecb": fetch_ecb, "nyfed": fetch_nyfed,
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
    previous = {}
    path = DATA / "macro.json"
    if path.exists():
        previous = json.loads(path.read_text()).get("series", {})
    out = {}
    for sid, (region, group, name, tenor, src, key) in SERIES.items():
        try:
            obs = FETCHERS[src](key)
            if not obs:
                raise ValueError("inga observationer")
            if (dt.date.today() - dt.date.fromisoformat(obs[-1][0])).days > 30:
                raise ValueError(f"senaste värdet är från {obs[-1][0]} – serien verkar ha upphört")
            out[sid] = {"region": region, "group": group, "name": name, "tenor_months": tenor,
                        "source": SOURCES[src][0], "source_url": SOURCES[src][1], "key": key,
                        "latest": summarize(obs), "obs": thin(obs)}
            print(f"  {sid}: {obs[-1]} ({len(obs)} obs)", flush=True)
        except Exception as e:  # behåll gårdagens värden hellre än att tappa serien
            print(f"  ! {sid}: {e}", flush=True)
            if sid in previous:
                out[sid] = previous[sid] | {"stale": True}
    path.write_text(json.dumps({"generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                                "series": out}, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(out)}/{len(SERIES)} serier, {path.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
