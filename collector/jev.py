"""Valfri andra kontroll med TypeSafe Jev (aktiveras av TYPESAFE_API_KEY).

För varje belagt fält läser Jev citatets sammanhang i källan och avgör om det
stöder, motsäger eller inte säger något om påståendet. Ett tydligt "motsäger"
eller "säger inget" nollar fältet; osäkra svar markeras men behålls.
Mönster: https://docs.typesafe.ai/cookbooks/citation_check
"""
from __future__ import annotations

import os

import httpx

from . import segments

URL = os.environ.get("TYPESAFE_ENDPOINT", "https://api.typesafe.ai/v1/systemone")
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")
ACCEPT = 0.8
ACCEPT_BOOL = 0.4
CONTEXT = 700

usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


def claim(product: str, bank: str, desc: str, value) -> str:
    """Påståendet Jev bedömer, på naturlig svenska – särskilt ja/nej-frågor."""
    if isinstance(value, bool):
        return f"För produkten {product!r} hos {bank} gäller följande. Fråga: {desc} Svar: {'ja' if value else 'nej'}."
    return f"För produkten {product!r} hos {bank}: {desc} Värde: {value}."


def number_in_quote(field: dict) -> bool:
    from .verify import number_in

    return number_in(field["value"], field["quote"])


def binding_in_name(name: str, field: dict) -> bool:
    from .verify import binding_in, number_in

    v = field["value"]
    in_name = number_in(v, name) or binding_in(v, name)
    return in_name and (binding_in(v, field["quote"]) or number_in(v, field["quote"]))


def available() -> bool:
    return bool(os.environ.get("TYPESAFE_API_KEY"))


def _context(quote: str, doc: str) -> str:
    """Citatet med omgivande text, så att Jev ser t.ex. att räntan gäller företag."""
    i = doc.lower().find(quote.lower()[:40])
    if i < 0:
        # Normaliserad position är svår att mappa tillbaka – ta citatet självt.
        return quote
    return doc[max(0, i - CONTEXT): i + len(quote) + CONTEXT]


def check_product(product: dict, docs: list[str], bank_name: str, previous: dict | None = None) -> None:
    """Uppdaterar product['fields'] på plats med jev-resultat. Fält med samma värde och citat
    som förra gången, där Jev då höll med, kontrolleras inte igen (sparar anrop)."""
    fields = {k: v for k, v in product["fields"].items() if v["status"] == "belagt"}
    for k in list(fields):
        old = ((previous or {}).get("fields") or {}).get(k) or {}
        if old.get("value") == fields[k]["value"] and old.get("quote") == fields[k]["quote"] \
                and (old.get("jev") or {}).get("verdict") == "supports":
            fields[k]["jev"] = old["jev"]
            fields.pop(k)
    # Bindningstid som står i produktens eget namn och i citatet ("Sparkonto 3 månader: 2,95 %")
    # är redan starkt belagd; Jev läser ofta sådana rader för bokstavligt.
    b = fields.get("binding_months")
    if b and b["value"] and binding_in_name(product["name"], b):
        fields.pop("binding_months")
    # Räntor som i citatet står ihop med periodens namn ("2,95 % / 9 månader", tabellraden
    # "| 3 mån | 2,73 | 2,75 | …") ska inte heller nollas – Jev läser långa tabellrader dåligt.
    from .verify import binding_in, number_in, period_months

    months = period_months(product["name"])
    for key in ("rate_percent", "avg_rate_percent"):
        r = fields.get(key)
        if r and months and number_in_quote(r) and (binding_in(months, r["quote"]) or number_in(months, r["quote"])):
            fields.pop(key)

    if not fields:
        return
    desc = {name: d for name, _, d in segments.cur().fields}
    state = {"bank": bank_name, "product": product["name"]}
    questions = {}
    for k, v in fields.items():
        state[k] = _context(v["quote"], docs[v["source"]])
        questions[k] = {
            "type": "choice",
            "instructions": {
                "claim": claim(product["name"], bank_name, desc[k], v["value"]),
                "question": f"Hur förhåller sig texten i `{k}` till påståendet `claim`, för just denna produkt och för privatpersoner?",
            },
            "criteria": {
                "supports": "Texten säger uttryckligen detta för denna produkt.",
                "contradicts": "Texten säger något annat för denna produkt (annat värde, gäller annan produkt eller företag, eller är inaktuellt).",
                "says_nothing": "Texten säger inte detta om denna produkt.",
            },
        }
    r = httpx.post(
        URL,
        headers={"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}"},
        json={"state": state, "model": MODEL, "questions": questions},
        timeout=120,
    )
    r.raise_for_status()
    body = r.json()
    usage["calls"] += 1
    for key in ("input_tokens", "output_tokens"):
        usage[key] += body.get("usage", {}).get(key, 0)
    for k, ans in body["answers"].items():
        f = product["fields"][k]
        f["jev"] = {"verdict": ans["choice"], "confidence": round(ans["confidence"], 2)}
        # Citatet är redan bevisat att stå i källan. Jev nollar bara när den säkert
        # säger emot; ett osäkert nej markeras men värdet står kvar.
        if ans["choice"] == "supports":
            continue
        # Ja/nej: ett tvivelaktigt nej är sämre än "okänt" (det får folk att välja bort banken),
        # så ett nej nollas redan vid låg säkerhet. Ett ja har ett citat där saken nämns och
        # behandlas som andra värden.
        threshold = ACCEPT_BOOL if f["value"] is False else ACCEPT
        if ans["confidence"] >= threshold:
            f["claimed"], f["value"] = f["value"], None
            f["status"] = "motsägs av källan" if ans["choice"] == "contradicts" else "stöds inte av källan"
        else:
            f["status"] = "osäkert"
