"""Schemat för ett sparkonto. Varje fält har ett värde och ett ordagrant citat
ur källan (plus vilket dokument citatet kommer från). Saknas belägg ska
värdet vara null – hellre okänt än gissat."""
from __future__ import annotations


def _ev(value_schema: dict, desc: str) -> dict:
    return {
        "type": "object",
        "description": desc,
        "properties": {
            "value": value_schema,
            "quote": {"type": ["string", "null"], "description": "Ordagrant citat ur källan som belägger värdet, max ~300 tecken."},
            "source": {"type": ["integer", "null"], "description": "Index för dokumentet citatet kommer från."},
        },
        "required": ["value", "quote", "source"],
        "additionalProperties": False,
    }


def _enum(*vals):
    return {"type": ["string", "null"], "enum": [*vals, None]}


NUM = {"type": ["number", "null"]}
INT = {"type": ["integer", "null"]}
STR = {"type": ["string", "null"]}
BOOL = {"type": ["boolean", "null"]}

PRODUCT_TYPES = ("rörligt sparkonto", "fasträntekonto", "sparkonto med uttagsbegränsning",
                 "transaktionskonto med ränta", "annat")

# (fältnamn, schema, beskrivning, visas i jämförelsen)
FIELDS = [
    ("product_type", _enum(*PRODUCT_TYPES), "Typ av konto."),
    ("rate_percent", NUM, "Gällande nominell årsränta i procent för en vanlig privatkund och ett normalt belopp (t.ex. 100 000 kr). Vid trappa: räntan som gäller för 100 000 kr."),
    ("rate_type", _enum("rörlig", "fast"), "Rörlig eller fast ränta."),
    ("binding_months", INT, "Bindningstid i månader. 0 om ingen bindning."),
    ("withdrawals", _enum("fria", "begränsade", "ej under bindningstid"), "Hur uttag fungerar."),
    ("free_withdrawals_per_year", INT, "Antal fria uttag per år om det är begränsat."),
    ("withdrawal_terms", STR, "Kort sammanfattning (svenska, max 200 tecken) av uttagsregler, avgifter och uppsägningstid."),
    ("early_withdrawal", _enum("ej tillåtet", "tillåtet mot avgift/ränteavdrag", "tillåtet utan kostnad"), "Uttag före bindningstidens slut (för bundna konton)."),
    ("min_deposit_sek", NUM, "Lägsta insättning/behållning i kronor för att få räntan. 0 om inget minimum."),
    ("max_deposit_sek", NUM, "Högsta belopp i kronor som räntan gäller för eller som får sättas in. null om inget tak anges."),
    ("monthly_deposit_cap_sek", NUM, "Högsta insättning per månad i kronor om kontot är ett månadssparkonto eller har ett månadstak. null om inget sådant tak finns."),
    ("deposit_terms", STR, "Kort sammanfattning av insättningsregler (t.ex. engångsinsättning, påfyllning tillåten)."),
    ("eligibility", STR, "Vem kan öppna kontot (ålder, folkbokföring i Sverige, BankID, kund i banken)."),
    ("requires_other_products", BOOL, "Krävs andra produkter (lönekonto, kort, paket) för räntan?"),
    ("intro_rate", BOOL, "Är räntan en kampanj- eller introduktionsränta som gäller tillfälligt?"),
    ("interest_paid", STR, "När räntan kapitaliseras/betalas ut (månadsvis, årsvis, vid bindningstidens slut)."),
    ("guarantee_country", {"type": ["string", "null"], "description": "ISO-landskod för den insättningsgaranti som gäller (SE, LT, NO …)."}, "Vilket lands insättningsgaranti som gäller."),
    ("guarantee_amount", STR, "Garantibeloppet som anges (t.ex. '1 050 000 kr' eller '100 000 euro')."),
    ("rate_valid_from", STR, "Datum då räntan började gälla, ISO-format om angivet."),
]

TIER = {
    "type": "object",
    "properties": {
        "min_sek": NUM, "max_sek": NUM, "rate_percent": NUM,
        "quote": {"type": ["string", "null"]}, "source": INT,
    },
    "required": ["min_sek", "max_sek", "rate_percent", "quote", "source"],
    "additionalProperties": False,
}

PRODUCT = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Produktnamn så som banken skriver det, inkl. bindningstid för fasträntekonton (t.ex. 'Fasträntekonto 12 mån')."},
        "fields": {
            "type": "object",
            "properties": {name: _ev(s, d) for name, s, d in FIELDS},
            "required": [f[0] for f in FIELDS],
            "additionalProperties": False,
        },
        "rate_tiers": {"type": "array", "items": TIER, "description": "Räntetrappa om räntan beror på belopp, annars tom."},
    },
    "required": ["name", "fields", "rate_tiers"],
    "additionalProperties": False,
}

EXTRACTION = {
    "type": "object",
    "properties": {
        "products": {"type": "array", "items": PRODUCT},
        "notes": {"type": ["string", "null"], "description": "Kort om något viktigt saknas i källorna (t.ex. räntan visas bara efter inloggning)."},
    },
    "required": ["products", "notes"],
    "additionalProperties": False,
}
