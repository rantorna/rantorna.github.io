"""Växlingskontorens säljkurser för kontanter – utan AI.

    python -m collector.cash

Läser kurslistan hos växlingskontoren (i dag Forex Bank) och tar ut säljkursen per valuta
direkt ur texten. Sidan kräver webbläsaren, så modulen körs i nattjobbet. Valutasidan
jämför kurserna med ECB:s referenskurs. Skriver data/cash.json.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from . import fetch

DATA = Path(__file__).resolve().parent.parent / "data"
# Växlingskontor: namn, kurslista, mönster för "1 EUR = 11,9180 SEK" (eller "100 JPY = …") i sidans text
OFFICES = [
    ("Forex Bank", "https://www.forex.se/en/currency/currency-rates/",
     re.compile(r"(?<![\d,.])(\d+)\s+([A-Z]{3})\s*=\s*(\d+(?:[.,]\d+)?)\s*SEK\b")),
]


def read(name: str, url: str, pattern: re.Pattern) -> dict | None:
    if not fetch.allowed(url):
        print(f"  ! {name}: robots.txt tillåter inte {url}")
        return None
    try:
        page = fetch._browser_get(url)   # kurserna fylls i med JavaScript
    except Exception as e:
        print(f"  ! {name}: {e}")
        return None
    rates = {}
    for unit, cur, val in pattern.findall(page.text):
        rates.setdefault(cur, float(val.replace(",", ".")) / int(unit))   # kronor per en enhet
    if len(rates) < 5:  # sidan har ändrat utseende – hellre inget än fel
        print(f"  ! {name}: bara {len(rates)} kurser kunde läsas")
        return None
    return {"name": name, "url": url, "fetched_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "sell": rates}


def main():
    path = DATA / "cash.json"
    old = {o["name"]: o for o in json.loads(path.read_text()).get("offices", [])} if path.exists() else {}
    offices = []
    for name, url, pat in OFFICES:
        got = read(name, url, pat)
        if got:
            print(f"  {name}: {len(got['sell'])} valutor, EUR {got['sell'].get('EUR')}")
            offices.append(got)
        elif name in old:   # behåll förra hämtningen, märkt med sin tid
            offices.append(old[name])
    fetch.close()
    path.write_text(json.dumps({"offices": offices}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
