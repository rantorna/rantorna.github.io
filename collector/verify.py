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
    s = re.sub(r"(\d)[ \u00a0\u202f](?=\d{3}(?!\d))", r"\1", s)  # 100 000 -> 100000
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
    for d in (0, 1, 2, 3, 4):
        s = f"{x:.{d}f}"
        if float(s) == round(x, 4):
            out |= {s, s.replace(".", ",")}
    if float(x).is_integer():
        out.add(str(int(x)))
    return out


WORDS = {1: ("ett", "en", "ettårigt"), 2: ("två",), 3: ("tre",), 4: ("fyra",), 5: ("fem",), 6: ("sex",),
         7: ("sju",), 8: ("åtta",), 9: ("nio",), 10: ("tio",), 11: ("elva",), 12: ("tolv",), 18: ("arton",)}


def number_in(value: float, quote: str) -> bool:
    """Talet som eget tal i citatet – "2" ska inte matcha "2,10" eller "12".
    _norm har redan slagit ihop tusental ("100 000" -> "100000")."""
    q = _norm(quote)
    for v in _num_variants(value):
        if re.search(r"(?<![\d,.])" + re.escape(v) + r"(?![\d]|[,.]\d)", q):
            return True
    # Små heltal skrivs ofta med ord ("tre månader", "två år").
    words = set(re.findall(r"\w+", _norm(quote)))
    return float(value).is_integer() and any(w in words for w in WORDS.get(int(value), ()))


def number_near(value: float, quote: str, doc: str) -> str | None:
    """Om talet står i samma tabellrad som citatet (eller raden direkt under,
    där etiketten står ovanför värdet): returnera ett utökat citat med båda."""
    q = " ".join(quote.split()).lower()
    lines = [" ".join(l.split()) for l in doc.splitlines()]
    for i, line in enumerate(lines):
        if q[:60] not in line.lower():
            continue
        spans = [line]
        if not re.search(r"\d\s*%", line) and i + 1 < len(lines):
            spans.append(line + " " + lines[i + 1])  # etikett ovanför värdet
        for span in spans:
            for v in _num_variants(value):
                if re.search(r"(?<![\d,.])" + re.escape(v) + r"(?!\d)", span):
                    return span[:400]
    return None


PERIOD_WORDS = {"halvår": 6, "halvt år": 6, "kvartal": 3}


def binding_in(months: float, quote: str) -> bool:
    """Bindningstid uttryckt i år, dagar eller ord."""
    if number_in(months / 12, quote):
        return True
    q = _norm(quote)
    for days in {round(months * 30), round(months * 365 / 12), round(months * 365 / 12) + 1}:
        if re.search(rf"(?<!\d){days}\s*(dagar|dgr|d\b)", q):
            return True
    return any(w in q and v == months for w, v in PERIOD_WORDS.items())


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
        elif name == "min_deposit_sek" and value == 0 and re.search(r"första kronan|inget (lägsta|minsta)", quote, re.I):
            pass
        elif name == "binding_months" and binding_in(value, quote):
            pass  # "1 år", "90 dagar", "ett halvår"
        elif not number_in(value, quote):
            wider = number_near(value, quote, docs[src])
            if wider:
                return {"value": value, "quote": wider, "source": src, "status": "belagt"}
            return {"value": None, "quote": quote, "source": src, "status": "talet finns inte i citatet", "claimed": value}
    return {"value": value, "quote": quote, "source": src, "status": "belagt"}


SPECIAL_PURPOSE = re.compile(r"skogs|upphovsman|klientmedel|pensionsspar", re.I)


def in_scope(prod: dict) -> bool:
    """Konton för särskilda ändamål är inte vanligt sparande och jämförs inte."""
    return not SPECIAL_PURPOSE.search(prod.get("name", ""))


def period_months(name: str) -> int | None:
    """Bindningstid ur produktnamnet: "Fix 24 mån" -> 24, "1 år" -> 12, "90 dagar" -> 3."""
    m = re.search(r"(\d+(?:[,.]5)?)\s*(?:[–-]\s*\d+\s*)?(mån|månad|år|dag)", name, re.I)  # "6–11 mån" -> 6
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    return round(n * 12) if unit == "år" else round(n / 30) if unit == "dag" else round(n)


def with_period(field: dict, months: int, docs: list[str]) -> dict:
    """Citat som bara är räntan ("3,15 %") utökas med raden intill om den raden
    anger produktens period ("24 månader"), så att belägget står för sig självt."""
    q = field.get("quote") or ""
    if field.get("status") != "belagt" or binding_in(months, q) or number_in(months, q):
        return field
    lines = [" ".join(l.split()) for l in docs[field["source"]].splitlines()]
    target = " ".join(q.split())
    for i, line in enumerate(lines):
        if target and target in line:
            for j in (i + 1, i - 1):
                if 0 <= j < len(lines) and lines[j] and (binding_in(months, lines[j]) or number_in(months, lines[j])):
                    pair = (line, lines[j]) if j > i else (lines[j], line)
                    return {**field, "quote": " / ".join(pair)}
    return field


def verify_product(prod: dict, docs: list[str], previous: dict | None) -> dict:
    fields = {name: check_field(name, prod["fields"].get(name, {}), docs) for name, _, _ in FIELDS}
    months = period_months(prod.get("name", ""))
    if months:
        r = fields["rate_percent"] = with_period(fields["rate_percent"], months, docs)
        b = fields["binding_months"]
        claimed = b["value"] if b["value"] is not None else b.get("claimed")
        if b["status"] != "belagt" and claimed == months and r["status"] == "belagt" \
                and (binding_in(months, r["quote"]) or number_in(months, r["quote"])):
            # Räntans citat ("2,75 % / 3 månader") belägger också produktens bindningstid.
            fields["binding_months"] = {"value": months, "quote": r["quote"], "source": r["source"], "status": "belagt"}
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
    core = list(CORE)
    if f["rate_percent"]["value"] is None or p["flags"]:
        p["status"] = "ej verifierad"
    elif all(f[c]["status"] in ("belagt", "osäkert") and f[c]["value"] is not None for c in core):
        p["status"] = "verifierad"
    else:
        p["status"] = "delvis verifierad"
