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
    ("withdrawals", _enum("fria", "begränsade", "mot avgift", "ej tillåtna"),
     "Uttag under kontots löptid (för bundna konton: före bindningstidens slut). fria = när som helst utan kostnad; "
     "begränsade = ett visst antal fria uttag eller uppsägningstid; mot avgift = tillåtet men kostar (avgift eller ränteavdrag); "
     "ej tillåtna = pengarna är låsta."),
    ("free_withdrawals_per_year", INT, "Antal fria uttag per år om det är begränsat."),
    ("withdrawal_terms", STR, "Kort sammanfattning (svenska, max 200 tecken) av uttagsregler, avgifter och uppsägningstid."),
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


def extraction_schema(fields, name_desc: str, tier: dict, tiers_desc: str, notes_desc: str) -> dict:
    product = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": name_desc},
            "fields": {
                "type": "object",
                "properties": {name: _ev(s, d) for name, s, d in fields},
                "required": [f[0] for f in fields],
                "additionalProperties": False,
            },
            "rate_tiers": {"type": "array", "items": tier, "description": tiers_desc},
        },
        "required": ["name", "fields", "rate_tiers"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "products": {"type": "array", "items": product},
            "notes": {"type": ["string", "null"], "description": notes_desc},
        },
        "required": ["products", "notes"],
        "additionalProperties": False,
    }


EXTRACTION = extraction_schema(
    FIELDS,
    "Produktnamn så som banken skriver det, inkl. bindningstid för fasträntekonton (t.ex. 'Fasträntekonto 12 mån').",
    TIER, "Räntetrappa om räntan beror på belopp, annars tom.",
    "Kort om något viktigt saknas i källorna (t.ex. räntan visas bara efter inloggning).",
)


# ---------- Bolån: en produkt per bank och bindningstid ----------

MORTGAGE_FIELDS = [
    ("loan_category", _enum("vanligt bolån", "specialistbolån", "seniorlån"),
     "vanligt bolån = för kunder med normal ekonomi och anställning; specialistbolån = riktar sig till dem som nekats av "
     "storbankerna (betalningsanmärkning, egenföretagare utan historik, utan fast anställning); seniorlån = "
     "för äldre, lån mot bostadens värde utan amorteringskrav (t.ex. hypotekspension)."),
    ("binding_months", INT, "Räntebindningstid i månader (3 för rörlig/3 mån, 12 för 1 år, 60 för 5 år)."),
    ("rate_percent", NUM, "Bankens listränta (nominell) i procent för den här bindningstiden."),
    ("avg_rate_percent", NUM, "Genomsnittlig ränta (snittränta) som kunderna faktiskt fått på nya lån med den här bindningstiden under den senast redovisade månaden."),
    ("avg_rate_month", STR, "Månaden snitträntan avser, format ÅÅÅÅ-MM."),
    ("effective_rate_percent", NUM, "Effektiv ränta om den anges för listräntan (med exempelberäkning)."),
    ("rate_valid_from", STR, "Datum då listräntan började gälla, ISO-format om angivet."),
    ("ltv_pricing", STR, "Kort (max 200 tecken): hur räntan beror på belåningsgrad, lånebelopp eller energiklass, om banken anger det."),
    ("discounts", STR, "Kort: rabatter eller villkor som sänker räntan (grönt bolån, paket, medlemskap, förhandling)."),
    ("requires_other_products", BOOL, "Krävs andra produkter eller kundrelation (lönekonto, paket, medlemskap) för att få lånet eller räntan?"),
    ("max_ltv_percent", NUM, "Högsta belåningsgrad i procent som banken lånar ut till, om den anges."),
    ("eligibility", STR, "Kort: vem kan låna (t.ex. bara befintliga kunder, bara vissa orter, bostadsrätt/villa, fritidshus)."),
]

TIER_LTV = {
    "type": "object",
    "properties": {
        "ltv_max_percent": NUM, "rate_percent": NUM,
        "quote": {"type": ["string", "null"]}, "source": INT,
    },
    "required": ["ltv_max_percent", "rate_percent", "quote", "source"],
    "additionalProperties": False,
}

MORTGAGE_EXTRACTION = extraction_schema(
    MORTGAGE_FIELDS,
    "Bindningstiden så som banken skriver den (t.ex. '3 mån', '1 år', '5 år').",
    TIER_LTV, "Räntor per belåningsgrad för den här bindningstiden om banken prissätter så, annars tom.",
    "Kort om något viktigt saknas (t.ex. bara snitträntor, listräntor kräver inloggning).",
)
