"""Valutakurser för fliken Valuta – utan AI.

    python -m collector.fx

ECB:s referenskurser (alla ~30 valutor, ett anrop) räknas om till kronor per enhet.
Riksbankens KIX-index visar kronan mot en korg av handelspartners valutor. Kortens
valutapåslag tas från kreditkortsinsamlingen, och räntorna från ränteläget (macro.json),
så att sidan kan visa hur räntor och valuta hänger ihop. Skriver data/fx.json.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import re
from pathlib import Path

from .macro import get, fetch_riksbank

DATA = Path(__file__).resolve().parent.parent / "data"
START = dt.date(2016, 1, 1)
HISTORY = ["EUR", "USD", "GBP", "NOK", "DKK"]
NAMES = {
    "EUR": "Euro", "USD": "Amerikansk dollar", "GBP": "Brittiskt pund", "NOK": "Norsk krona", "DKK": "Dansk krona",
    "CHF": "Schweizisk franc", "PLN": "Polsk zloty", "CZK": "Tjeckisk koruna", "HUF": "Ungersk forint",
    "ISK": "Isländsk krona", "TRY": "Turkisk lira", "JPY": "Japansk yen", "CNY": "Kinesisk yuan", "THB": "Thailändsk baht",
    "AUD": "Australisk dollar", "CAD": "Kanadensisk dollar", "NZD": "Nyzeeländsk dollar", "HKD": "Hongkongdollar",
    "SGD": "Singaporedollar", "INR": "Indisk rupie", "IDR": "Indonesisk rupiah", "KRW": "Sydkoreansk won",
    "MXN": "Mexikansk peso", "BRL": "Brasiliansk real", "ZAR": "Sydafrikansk rand", "ILS": "Israelisk shekel",
    "MYR": "Malaysisk ringgit", "PHP": "Filippinsk peso", "RON": "Rumänsk leu", "BGN": "Bulgarisk lev",
}


def ecb_rates() -> dict[str, list[tuple[str, float]]]:
    """Kronor per enhet av varje valuta, per dag, ur ECB:s kurser (som anges per euro)."""
    r = get("https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A",
            params={"startPeriod": START.isoformat(), "format": "csvdata"})
    per_eur: dict[str, dict[str, float]] = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        if row.get("OBS_VALUE"):
            per_eur.setdefault(row["CURRENCY"], {})[row["TIME_PERIOD"]] = float(row["OBS_VALUE"])
    sek = per_eur.pop("SEK")
    out = {"EUR": sorted(sek.items())}
    for cur, series in per_eur.items():
        out[cur] = sorted((d, sek[d] / v) for d, v in series.items() if d in sek and v)
    return out


def thin(obs: list, step: int) -> list:
    """Var n:te observation (plus den sista) – räcker för diagram och håller filen liten."""
    return [o for i, o in enumerate(obs) if i % step == 0 or i == len(obs) - 1]


def change(obs: list, days: int) -> float | None:
    """Procentuell förändring mot närmaste observation för `days` dagar sedan."""
    if not obs:
        return None
    target = (dt.date.fromisoformat(obs[-1][0]) - dt.timedelta(days=days)).isoformat()
    old = next((v for d, v in reversed(obs) if d <= target), None)
    return None if not old else round((obs[-1][1] / old - 1) * 100, 2)


def rate_context() -> dict:
    """Räntor från ränteläget: styrräntor, 2-åriga statsobligationer och korta räntor, samt
    räntedifferenserna mot Sverige över tid."""
    path = DATA / "macro.json"
    if not path.exists():
        return {}
    s = json.loads(path.read_text())["series"]
    pick = ["se_policy", "eu_dfr", "us_fed_upper", "se_gvb2y", "eu_y2y", "us_t2y", "se_tb3m", "eu_y3m", "us_t3m"]
    latest = {k: s[k]["latest"]["value"] for k in pick if k in s}

    def diff(a, b):
        """a − b vid varje datum i a, med senast kända b."""
        if a not in s or b not in s:
            return []
        bo, out, j = s[b]["obs"], [], -1
        for d, v in s[a]["obs"]:
            while j + 1 < len(bo) and bo[j + 1][0] <= d:
                j += 1
            if j >= 0:
                out.append([d, round(v - bo[j][1], 3)])
        return out

    return {"latest": latest, "diff_se_eu_2y": diff("se_gvb2y", "eu_y2y"), "diff_se_us_2y": diff("se_gvb2y", "us_t2y"),
            "diff_se_eu_policy": diff("se_policy", "eu_dfr")}


def issuer(bank: dict) -> str:
    """Utgivarens namn utan korttyp (samma regel som kreditkortssidan)."""
    short = re.sub(r"\s*[(–].*$", "", bank["name"])
    short = re.sub(r",.*$", "", short)
    short = re.sub(r"\s+(betal|kreditkort|mastercard|visa|kort|gold|guld|platinum|classic)\b.*$", "", short, flags=re.I).strip()
    if short and not re.match(r"^(betal|visa|mastercard|kreditkort)", short, re.I) and "sparbank" not in (bank.get("legal_name") or "").lower():
        return short
    legal = re.sub(r",.*$", "", bank.get("legal_name") or "")
    legal = re.sub(r"\s*\(publ\)", "", legal, flags=re.I)
    return re.sub(r"\s+(AB|Aktiebolag)$", "", legal, flags=re.I).strip() or short or bank["name"]


def cards() -> list[dict]:
    """Kortens valutapåslag och uttagsavgifter, ett erbjudande per rad (sparbankerna slås ihop)."""
    path = DATA / "cards.json"
    if not path.exists():
        return []
    val = lambda p, k: (p["fields"].get(k) or {}).get("value")
    groups: dict[tuple, dict] = {}
    for b in json.loads(path.read_text())["banks"]:
        for p in b.get("products") or []:
            fx = val(p, "currency_fee_percent")
            if fx is None and val(p, "annual_fee_sek") is None:
                continue
            key = (p["name"].lower(), fx, val(p, "atm_fee_percent"), val(p, "atm_fee_min_sek"), val(p, "annual_fee_sek"))
            if key in groups:
                groups[key]["also"] += 1
                continue
            groups[key] = {"issuer": issuer(b["bank"]), "card": p["name"], "fx": fx, "atm_pct": val(p, "atm_fee_percent"),
                           "atm_min": val(p, "atm_fee_min_sek"), "annual": val(p, "annual_fee_sek"),
                           "type": val(p, "card_type"), "verified": p.get("status") == "verifierad", "also": 0,
                           "url": b["bank"].get("homepage")}
    return sorted(groups.values(), key=lambda c: (c["fx"] is None, c["fx"] or 0, c["issuer"]))


def main():
    rates = ecb_rates()
    date = rates["EUR"][-1][0]
    latest = {cur: round(obs[-1][1], 6) for cur, obs in rates.items() if obs and obs[-1][0] == date}
    out = {
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "date": date,
        "names": {k: v for k, v in NAMES.items() if k in latest},
        "latest": latest,
        "change_1y": {cur: change(rates[cur], 365) for cur in HISTORY},
        "history": {cur: [[d, round(v, 4)] for d, v in thin(rates[cur], 5)] for cur in HISTORY},
        "rates": rate_context(),
        "cards": cards(),
        "source_url": "https://data.ecb.europa.eu/main-figures/ecb-interest-rates-and-exchange-rates/exchange-rates",
    }
    try:
        kix = [(d, v) for d, v in fetch_riksbank("SEKKIX92") if d >= START.isoformat()]
        out["kix"] = {"latest": kix[-1], "change_1y": change(kix, 365), "obs": [[d, round(v, 2)] for d, v in thin(kix, 5)]}
    except Exception as e:  # KIX är ett tillägg – sidan klarar sig utan
        print(f"  ! KIX: {e}")
        old = DATA / "fx.json"
        if old.exists():
            out["kix"] = json.loads(old.read_text()).get("kix")
    (DATA / "fx.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"{len(latest)} valutor per {date}, EUR {latest['EUR']:.4f}, {len(out['cards'])} kort, "
          f"{(DATA / 'fx.json').stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
