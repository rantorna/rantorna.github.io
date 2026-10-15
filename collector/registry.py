"""Hämtar alla institut som får ta emot insättningar ur Finansinspektionens företagsregister.

    python -m collector.registry

Skriver data/fi_register.json. Kategorierna är FI:s egna koder.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import httpx

URL = "https://www.fi.se/sv/vara-register/foretagsregistret/index"
DATA = Path(__file__).resolve().parent.parent / "data"

# kod -> (beskrivning, utländskt?)
CATEGORIES = {
    "BANK": ("Bankaktiebolag", False),
    "SPAR": ("Sparbank", False),
    "MBANK": ("Medlemsbank", False),
    "KMB": ("Kreditmarknadsbolag", False),
    "KMF": ("Kreditmarknadsförening", False),
    "UTLFIL": ("Utländsk bank, svensk filial", True),
    "FILBK": ("Betydande filial till kreditinstitut inom EU/EES", True),
    "UTLKMF": ("Utländskt kreditmarknadsbolag, svensk filial", True),
    "UTLBGH": ("Utländsk bank, gränsöverskridande handel", True),
    "UTLKGH": ("Utländskt kreditmarknadsbolag, gränsöverskridande handel", True),
    "INLÅN": ("Inlåningsföretag (ingen insättningsgaranti)", False),
    "BKRI": ("Bostadskreditinstitut", False),
    "RIKSLI": ("Riksbolag, livförsäkringar", False),
    "TJPAB": ("Tjänstepensionsaktiebolag", False),
    "TJPE": ("Tjänstepensionsförening", False),
    "TJPÖMS": ("Ömsesidigt tjänstepensionsbolag", False),
    "UTLFFL": ("Utländskt försäkringsbolag, svensk filial, liv", True),
    "UTBKRF": ("Utländskt bostadskreditinstitut, svensk filial", True),
    "GRÄS": ("Leverantör av gräsrotsfinansieringstjänster", False),
}


def fetch_category(code: str) -> list[dict]:
    r = httpx.get(URL, params={"cat": code}, headers={"User-Agent": "Mozilla/5.0 rantorna"}, timeout=60, follow_redirects=True)
    r.raise_for_status()
    out = []
    for fid, name in re.findall(r'<a href="details\?id=(\d+)">([^<]+)</a>', r.text):
        out.append({"fi_id": fid, "name": " ".join(html.unescape(name).split()), "category": code,
                    "category_name": CATEGORIES[code][0], "foreign": CATEGORIES[code][1]})
    return out


def main():
    seen, rows = set(), []
    for code in CATEGORIES:
        items = fetch_category(code)
        print(f"{code}: {len(items)}")
        for it in items:
            if it["fi_id"] not in seen:
                seen.add(it["fi_id"])
                rows.append(it)
    rows.sort(key=lambda r: (r["foreign"], r["category"], r["name"].lower()))
    (DATA / "fi_register.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"totalt {len(rows)} institut")


if __name__ == "__main__":
    main()
