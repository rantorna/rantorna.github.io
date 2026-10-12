"""Kvalitetskontroll av insamlad data – regler som letar efter misstänkta värden.

    python -m collector.qa            # rapport per regel
    python -m collector.qa --verbose  # med alla träffar

Ändrar ingenting. Tanken är att det som hittas här leder till rättade regler
eller prompter, inte till handpåläggning i datan.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
from pathlib import Path

from .verify import binding_in, period_months

DATA = Path(__file__).resolve().parent.parent / "data"
OLD_SOURCE = re.compile(r"tidigare|arkiv|archive|historik|/old|20(1\d|20|21|22)[-_/]", re.I)


def v(p, k):
    return (p["fields"].get(k) or {}).get("value")


def amount(text):
    if not text:
        return None
    m = re.search(r"(\d[\d  ]*)\s*(kr|kronor|sek)", text, re.I)
    return int(re.sub(r"\D", "", m.group(1))) if m else None


def checks(bank, p):
    name, rate, bind = p["name"], v(p, "rate_percent"), v(p, "binding_months")
    ptype = v(p, "product_type")
    months = period_months(name)
    if months is not None and bind is not None and bind != months:
        yield "bindningstid ≠ namn", f"{bind} mån men namnet säger {months}"
    if ptype == "fasträntekonto" and bind == 0:
        yield "fastränta utan bindning", ""
    if ptype == "rörligt sparkonto" and bind:
        yield "rörligt med bindning", f"{bind} mån"
    if v(p, "rate_type") == "fast" and bind == 0:
        yield "fast ränta utan bindning", ""
    mn, mx = v(p, "min_deposit_sek"), v(p, "max_deposit_sek")
    if mn is not None and mx is not None and mn > mx:
        yield "min > max", f"{mn} > {mx}"
    if rate is not None and (rate <= 0 or rate > 5):
        yield "ränta utanför 0–5 %", f"{rate} %"
    gc, home = v(p, "guarantee_country"), bank["bank"].get("home_country")
    if gc and home and gc != home:
        yield "garantiland ≠ hemland", f"{gc} vs {home}"
    wd = v(p, "withdrawals")
    if wd == "fria" and v(p, "free_withdrawals_per_year"):
        yield "fria uttag men antal angivet", str(v(p, "free_withdrawals_per_year"))
    if wd == "ej tillåtna" and not bind:
        yield "låst utan bindningstid", ""
    vf = v(p, "rate_valid_from")
    if vf and re.match(r"\d{4}-\d{2}-\d{2}", vf):
        age = (dt.date.today() - dt.date.fromisoformat(vf[:10])).days
        if age > 730:
            yield "ränta äldre än 2 år", vf
    src = p["fields"].get("rate_percent", {}).get("source")
    if src is not None and src < len(bank["sources"]) and OLD_SOURCE.search(bank["sources"][src]["url"]):
        yield "räntan från gammal källa?", bank["sources"][src]["url"]
    elig = (v(p, "eligibility") or "").lower()
    if re.search(r"\b(företag|juridisk person|organisationsnummer)\b", elig) and "privat" not in elig:
        yield "verkar vara företagskonto", elig[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    hits = collections.defaultdict(list)
    se_amounts = collections.Counter()
    for f in sorted((DATA / "products").glob("*.json")):
        bank = json.loads(f.read_text())
        names = collections.Counter(p["name"] for p in bank.get("products", []))
        for n, c in names.items():
            if c > 1:
                hits["dubblett"].append((bank["bank"]["id"], n, f"{c} st"))
        for p in bank.get("products", []):
            if v(p, "guarantee_country") == "SE":
                se_amounts[amount(v(p, "guarantee_amount"))] += 1
            for rule, detail in checks(bank, p):
                hits[rule].append((bank["bank"]["id"], p["name"], detail))
    common = se_amounts.most_common(1)[0][0] if se_amounts else None
    for f in sorted((DATA / "products").glob("*.json")):
        bank = json.loads(f.read_text())
        for p in bank.get("products", []):
            a = amount(v(p, "guarantee_amount"))
            if v(p, "guarantee_country") == "SE" and a and a != common:
                hits["avvikande svenskt garantibelopp"].append((bank["bank"]["id"], p["name"], f"{a} (vanligast {common})"))
    print(f"Svenska garantibelopp: {dict(se_amounts.most_common(4))}\n")
    for rule, items in sorted(hits.items(), key=lambda x: -len(x[1])):
        print(f"{len(items):4}  {rule}")
        for it in items if args.verbose else items[:4]:
            print(f"        {it[0]} | {it[1][:40]} | {it[2]}")


if __name__ == "__main__":
    main()
