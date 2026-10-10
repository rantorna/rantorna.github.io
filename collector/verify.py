"""Kontrollerar att modellens svar faktiskt står i källan.

Ett fält räknas som belagt bara om citatet går att hitta i källdokumentet och,
för tal, om talet förekommer i citatet. Annars nollas värdet och fältet blir
"okänt" på sidan.
"""
from __future__ import annotations

import re
import unicodedata

from .schema import FIELDS

# Fält som måste vara belagda för att produkten ska räknas som verifierad.
CORE = ("rate_percent", "binding_months", "withdrawals")
MAX_PLAUSIBLE_RATE = 8.0
MAX_JUMP_PP = 1.5  # procentenheter mellan två körningar innan vi kräver bekräftelse


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = s.replace("­", "")
    s = re.sub(r"[‐-‒–—−]", "-", s)
    s = re.sub(r"[\"'“”‘’«»]", "", s)
    s = re.sub(r"(\d)[   ](?=\d{3}\b)", r"\1", s)  # 100 000 -> 100000
    s = re.sub(r"[^\w%,.\-]+", " ", s)
    return " ".join(s.split())


def quote_in(quote: str, source: str) -> bool:
    q = _norm(quote)
    if len(q) < 4:
        return False
    src = _norm(source)
    if q in src:
        return True
    # Tåla att modellen hoppat över ett mellanled ("…"): alla bitar måste finnas i ordning.
    chunks = [c.strip() for c in re.split(r"\.\.\.|…", quote) if c.strip()]
    if len(chunks) > 1:
        pos = 0
        for c in chunks:
            i = src.find(_norm(c), pos)
            if i < 0:
                return False
            pos = i
        return True
    return False


def _num_variants(x: float) -> set[str]:
    out = set()
    for d in (0, 1, 2, 3):
        s = f"{x:.{d}f}"
        if float(s) == round(x, 3):
            out |= {s, s.replace(".", ",")}
    if float(x).is_integer():
        out.add(str(int(x)))
    return out


WORDS = {1: ("ett", "en", "ettårigt"), 2: ("två",), 3: ("tre",), 4: ("fyra",), 5: ("fem",), 6: ("sex",),
         7: ("sju",), 8: ("åtta",), 9: ("nio",), 10: ("tio",), 11: ("elva",), 12: ("tolv",), 18: ("arton",)}


def number_in(value: float, quote: str) -> bool:
    q = _norm(quote).replace(" ", "")
    if any(v.replace(" ", "") in q for v in _num_variants(value)):
        return True
    # Små heltal skrivs ofta med ord ("tre månader", "två år").
    words = set(re.findall(r"\w+", _norm(quote)))
    return float(value).is_integer() and any(w in words for w in WORDS.get(int(value), ()))


def check_field(name, ev: dict, docs: list[str]) -> dict:
    """Returnerar {value, quote, source, status}."""
    value, quote, src = ev.get("value"), ev.get("quote"), ev.get("source")
    if value is None:
        return {"value": None, "quote": None, "source": None, "status": "okänt"}
    if not quote or src is None or not (0 <= src < len(docs)):
        return {"value": None, "quote": quote, "source": src, "status": "saknar belägg", "claimed": value}
    if not quote_in(quote, docs[src]):
        # Citatet kan stå i ett annat dokument än det modellen angav.
        alt = next((i for i, d in enumerate(docs) if quote_in(quote, d)), None)
        if alt is None:
            return {"value": None, "quote": quote, "source": src, "status": "citat hittades inte", "claimed": value}
        src = alt
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if name in ("binding_months", "free_withdrawals_per_year") and value == 0:
            pass  # "ingen bindning" står sällan som siffran 0
        elif name in ("binding_months",) and number_in(value / 12, quote):
            pass  # "1 år", "3 år"
        elif not number_in(value, quote):
            return {"value": None, "quote": quote, "source": src, "status": "talet finns inte i citatet", "claimed": value}
    return {"value": value, "quote": quote, "source": src, "status": "belagt"}


def verify_product(prod: dict, docs: list[str], previous: dict | None) -> dict:
    fields = {name: check_field(name, prod["fields"].get(name, {}), docs) for name, _, _ in FIELDS}
    tiers = []
    for t in prod.get("rate_tiers", []):
        ok = (
            t.get("rate_percent") is not None and t.get("quote") and t.get("source") is not None
            and 0 <= t["source"] < len(docs)
            and quote_in(t["quote"], docs[t["source"]]) and number_in(t["rate_percent"], t["quote"])
        )
        tiers.append({**t, "status": "belagt" if ok else "ej belagt"})

    flags = []
    rate = fields["rate_percent"]["value"]
    if rate is not None and not (0 <= rate <= MAX_PLAUSIBLE_RATE):
        flags.append(f"orimlig ränta {rate} %")
    if previous and rate is not None:
        prev_rate = previous.get("fields", {}).get("rate_percent", {}).get("value")
        if prev_rate is not None and abs(rate - prev_rate) > MAX_JUMP_PP:
            confirmed = previous.get("pending_rate") == rate
            if not confirmed:
                flags.append(f"räntan hoppade {prev_rate} → {rate} %, väntar på bekräftelse nästa körning")

    out = {
        "name": prod["name"],
        "flags": flags,
        "fields": fields,
        "rate_tiers": tiers,
        "pending_rate": rate if any("väntar" in f for f in flags) else None,
    }
    restatus(out)
    return out


def restatus(p: dict) -> None:
    """Sätter produktens samlade status utifrån fälten (körs igen efter Jev)."""
    f = p["fields"]
    bound = f["binding_months"]["value"] not in (None, 0)
    core = [c for c in CORE if not (c == "withdrawals" and bound)]
    if f["rate_percent"]["value"] is None or p["flags"]:
        p["status"] = "ej verifierad"
    elif all(f[c]["status"] in ("belagt", "osäkert") and f[c]["value"] is not None for c in core):
        p["status"] = "verifierad"
    else:
        p["status"] = "delvis verifierad"
