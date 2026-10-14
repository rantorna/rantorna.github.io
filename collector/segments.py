"""Det som skiljer sparkonton, bolån (och senare företag, pension) åt.

En körning arbetar med ett segment åt gången: `segments.use("mortgage")` och
sedan läser modulerna `segments.cur()`. Maskineriet – hämtning, citatkontroll,
Jev, rimlighetskontroll – är gemensamt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import schema

DATA = Path(__file__).resolve().parent.parent / "data"


@dataclass
class Segment:
    key: str
    fields: list
    extraction: dict
    extract_system: str
    choose_system: str
    core: tuple
    data_dir: Path                 # products/ och raw/ under denna
    site_file: Path                # det sidan läser
    resolve_system: str
    resolve_out: Path
    resolve_hints: Path
    resolve_categories: tuple      # FI-kategorier som slås upp (tom = alla)
    pos: dict = field(default_factory=dict)   # extra/ändrade nyckelordspoäng för sidurval
    terms_re: str = r"(villkor|ranta|ränt|spar|insattning|insättning|prislista|terms|savings)"
    manual_banks: Path | None = None
    max_rate: float = 8.0
    url_field: str = "product_url"        # vilken adress i uppslaget insamlingen startar från
    resolve_secondary: str | None = None  # beskrivning av en extra adress i uppslaget (t.ex. företagssparande)

    @property
    def products(self) -> Path:
        return self.data_dir / "products"

    @property
    def raw(self) -> Path:
        return self.data_dir / "raw"


SAVINGS_EXTRACT = """Du extraherar fakta om sparkonton (inlåning) för privatpersoner i Sverige ur en banks egna webbsidor och villkorsdokument, för en oberoende jämförelsesajt.

Regler:
- Ta med varje separat sparprodukt med egen ränta eller egna villkor som en privatperson i Sverige kan öppna (varje bindningstid för fasträntekonton är en egen produkt). Hoppa över företagskonton, barnkonton, ISK/depåer, lån, produkter som inte längre säljs och konton för särskilda ändamål (skogskonto, skogsskadekonto, upphovsmannakonto, klientmedelskonto, pensionssparkonto).
- Om samma konto har olika ränta beroende på medlemskap, betalpaket eller kundnivå (t.ex. "Plus", "Premium"): ta med varje variant som en egen produkt med variantens namn, och sätt requires_other_products till true för de betalda varianterna.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, inklusive siffror och procenttecken, max ~300 tecken) och dokumentets index i "source".
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig och dra inga slutsatser från allmän kunskap om banken.
- Räntor anges i procent som tal (3,25 % -> 3.25). Belopp i kronor som tal.
- Sammanfattande textfält skrivs på svenska, korta och sakliga, men måste ändå ha ett citat som stöd.
- Om dokumenten motsäger varandra: använd det som ser mest aktuellt ut och nämn det i notes."""

MORTGAGE_EXTRACT = """Du extraherar bolåneräntor för privatpersoner i Sverige ur en långivares egna webbsidor och dokument, för en oberoende jämförelsesajt.

Regler:
- Ta med en produkt per räntebindningstid som långivaren erbjuder för vanliga bolån (villa, bostadsrätt, fritidshus om samma räntor). Hoppa över byggkreditiv, blancolån, företagslån, lantbrukslån och historiska räntor.
- Listräntan (rate_percent) är den ränta banken anger som sin aktuella ränta. Snitträntan (avg_rate_percent) är den genomsnittliga ränta kunderna faktiskt fått på nya lån under den senast redovisade månaden – banker måste publicera den, ofta i en separat tabell. Blanda inte ihop dem, och ange avg_rate_month (ÅÅÅÅ-MM) för snitträntan. Ta den senaste månaden om tabellen visar flera.
- Om räntan beror på belåningsgrad: ange räntorna per belåningsgrad i rate_tiers och den högsta (sämsta) som rate_percent, om inte banken anger en listränta.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, inklusive siffror och procenttecken, max ~300 tecken) och dokumentets index i "source". När räntan står i en tabell: citera hela tabellraden.
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig.
- Räntor anges i procent som tal (3,25 % -> 3.25). Bindningstid i månader: rörlig/3 mån = 3, 1 år = 12, 5 år = 60.
- Om dokumenten motsäger varandra: använd det som ser mest aktuellt ut och nämn det i notes."""

SAVINGS_RESOLVE = """Du kartlägger den svenska marknaden för sparkonton åt en oberoende jämförelsesajt. Använd webbsökning och kontrollera på institutets egna webbplatser.

Avgör om institutet, under eget namn eller under ett annat varumärke, i dag erbjuder sparkonton eller annan inlåning som privatpersoner i Sverige kan öppna (svensk webbplats eller svenskspråkig sida, öppnas med t.ex. BankID). Räkna inte med: bara företagskunder, bara lån eller kort, ISK/fonder/aktier, pensionsprodukter, eller sparkonton som bara erbjuds i andra länder.

För plattformar som förmedlar sparkonton hos andra banker (t.ex. Avanza, Nordnet eller Sambla): ta med varumärket om kunden öppnar sparkontot via plattformen, och skriv i notes vilka banker som står för inlåningen.

Ange för varje varumärke den officiella svenska webbplatsen (homepage) och den sida som bäst listar sparkontona och deras räntor (savings_url). Hitta aldrig på adresser. Ange bara adresser du faktiskt har sett."""

MORTGAGE_RESOLVE = """Du kartlägger den svenska bolånemarknaden åt en oberoende jämförelsesajt. Använd webbsökning och kontrollera på institutets egna webbplatser.

Avgör om institutet, under eget namn eller under ett annat varumärke, i dag lånar ut bolån till privatpersoner i Sverige (villa, bostadsrätt, fritidshus). Räkna inte med: bara företags- eller lantbrukslån, bara blancolån, eller bolån bara i andra länder.

För förmedlare och plattformar (t.ex. Avanza, Nordnet, Ikano, ICA): ta med varumärket om kunden ansöker via varumärket och räntan publiceras där, och skriv i notes vem som är långivare.

Ange för varje varumärke den officiella svenska webbplatsen (homepage) och den sida som bäst visar bolåneräntorna – helst både listräntor och genomsnittliga räntor (savings_url används för den sidan). Hitta aldrig på adresser. Ange bara adresser du faktiskt har sett."""

SEGMENTS = {
    "savings": Segment(
        key="savings",
        fields=schema.FIELDS,
        extraction=schema.EXTRACTION,
        extract_system=SAVINGS_EXTRACT,
        choose_system=(
            "Du hjälper en svensk jämförelsesajt för sparkonton. Välj de sidor som mest sannolikt "
            "innehåller aktuella räntesatser och villkor för sparkonton/inlåning för privatpersoner i "
            "Sverige (rörliga sparkonton, fasträntekonton, villkorsdokument, räntetabeller, "
            "insättningsgaranti). Välj inte lån, kort, fonder, företagskonton eller nyheter."
        ),
        core=("rate_percent", "binding_months", "withdrawals"),
        data_dir=DATA,
        site_file=DATA / "rates.json",
        resolve_system=SAVINGS_RESOLVE,
        resolve_out=DATA / "institutions.json",
        resolve_hints=DATA / "brand_hints.yaml",
        resolve_categories=(),
        manual_banks=DATA / "banks.yaml",
    ),
    "mortgage": Segment(
        key="mortgage",
        fields=schema.MORTGAGE_FIELDS,
        extraction=schema.MORTGAGE_EXTRACTION,
        extract_system=MORTGAGE_EXTRACT,
        choose_system=(
            "Du hjälper en svensk jämförelsesajt för bolån. Välj de sidor som mest sannolikt innehåller "
            "aktuella bolåneräntor (listräntor), genomsnittliga räntor (snitträntor) per bindningstid och "
            "villkor för bolån till privatpersoner i Sverige. Välj inte sparkonton, privatlån, kort, "
            "företagslån, nyheter eller kalkylatorer utan räntor."
        ),
        core=("rate_percent", "binding_months"),
        data_dir=DATA / "mortgage",
        site_file=DATA / "mortgage.json",
        resolve_system=MORTGAGE_RESOLVE,
        resolve_out=DATA / "mortgage" / "institutions.json",
        resolve_hints=DATA / "mortgage" / "brand_hints.yaml",
        resolve_categories=("BANK", "SPAR", "MBANK", "KMB", "BKRI", "UTLFIL", "FILBK", "UTBKRF"),
        manual_banks=DATA / "mortgage" / "banks.yaml",
        pos={"bolan": 7, "bolanerantor": 7, "bolaneranta": 7, "snittranta": 7, "snittrantor": 7,
             "listranta": 6, "listrantor": 6, "genomsnittlig": 4, "genomsnittsrantor": 7, "bostadslan": 5,
             "lan": 1, "rantor": 4, "ranta": 3, "spar": -3, "sparkonto": -5, "sparkonton": -5,
             "privatlan": -5, "billan": -5, "blancolan": -5},
        terms_re=r"(bolån|bolan|ränt|ranta|snitt|genomsnitt|villkor|prislista)",
        max_rate=12.0,
    ),
}

BUSINESS_RESOLVE = """Du kartlägger den svenska marknaden för bankkonton för företag åt en oberoende jämförelsesajt. Använd webbsökning och kontrollera på institutets egna webbplatser.

Avgör om institutet, under eget namn eller under ett annat varumärke, i dag erbjuder företagskonton (transaktionskonto för företag) och/eller sparkonton/placeringskonton för företag i Sverige – för svenska aktiebolag, enskilda firmor, handelsbolag eller föreningar. Räkna inte med: bara privatkunder, bara lån/factoring, bara stora koncerner via förfrågan utan publicerat erbjudande, eller konton bara i andra länder.

Ange för varje varumärke den svenska webbplatsen (homepage), sidan som beskriver företagskontot (product_url, null om inget företagskonto) och sidan som beskriver sparande/placeringskonto för företag med räntor (secondary_url, null om inget sådant). Hitta aldrig på adresser. Ange bara adresser du faktiskt har sett."""

BUSINESS_ACCOUNT_EXTRACT = """Du extraherar fakta om företagskonton (transaktionskonton för företag) i Sverige ur en banks egna webbsidor och dokument, för en oberoende sajt som hjälper företagare att se vilka banker som tar emot dem.

Regler:
- Ta med varje företagskonto eller företagspaket (med konto) som banken erbjuder svenska företag. Hoppa över privatkonton, lån, factoring, kortkrediter och erbjudanden bara för storföretag.
- Viktigast: vilka företagsformer som kan öppna kontot, om nystartade företag tas emot, om kontot kan öppnas digitalt, om flera personer kan få behörighet, och vad det kostar.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, max ~300 tecken) och dokumentets index i "source".
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig – särskilt inte om nystartade eller flera användare.
- Belopp i kronor som tal (månadsavgift 99 kr -> 99). Räntor i procent som tal.
- Sammanfattande textfält skrivs på svenska, korta och sakliga, men måste ändå ha ett citat som stöd."""

BUSINESS_SAVINGS_EXTRACT = SAVINGS_EXTRACT.replace(
    "för privatpersoner i Sverige", "för företag och föreningar i Sverige"
).replace(
    "som en privatperson i Sverige kan öppna", "som ett svenskt företag eller en förening kan öppna"
).replace(
    "Hoppa över företagskonton, barnkonton, ISK/depåer, lån,", "Hoppa över privatkonton, barnkonton, ISK/depåer, lån, rena transaktionskonton utan sparränta,"
)

_BUSINESS_SHARED = dict(
    resolve_system=BUSINESS_RESOLVE,
    resolve_out=DATA / "business" / "institutions.json",
    resolve_hints=DATA / "business" / "brand_hints.yaml",
    resolve_categories=("BANK", "SPAR", "MBANK", "KMB", "UTLFIL", "FILBK", "UTLKMF"),
    resolve_secondary="Sidan om sparande/placeringskonto för företag med räntor, eller null.",
)

SEGMENTS["business_accounts"] = Segment(
    key="business_accounts",
    fields=schema.BUSINESS_ACCOUNT_FIELDS,
    extraction=schema.BUSINESS_ACCOUNT_EXTRACTION,
    extract_system=BUSINESS_ACCOUNT_EXTRACT,
    choose_system=(
        "Du hjälper en svensk sajt som jämför företagskonton. Välj de sidor som mest sannolikt beskriver "
        "bankens företagskonto eller företagspaket: vilka företag som kan bli kund, nystartade företag, "
        "behörigheter för flera användare, avgifter/prislistor och villkor. Välj inte privatsidor, lån, "
        "kortkrediter, nyheter eller storföretagstjänster."
    ),
    core=("company_forms", "monthly_fee_sek"),
    data_dir=DATA / "business" / "accounts",
    site_file=DATA / "business_accounts.json",
    pos={"foretag": 6, "foretagskonto": 8, "foretagspaket": 7, "foretagare": 5, "business": 5, "nystartad": 5,
         "nystartat": 5, "prislista": 4, "priser": 3, "avgifter": 3, "behorighet": 4, "behorigheter": 4,
         "bli-kund": 4, "konto": 2, "privat": -4, "lan": -3, "ranta": 0},
    terms_re=r"(företag|foretag|prislista|priser|avgift|villkor|business)",
    manual_banks=DATA / "business" / "banks_accounts.yaml",
    **_BUSINESS_SHARED,
)

SEGMENTS["business_savings"] = Segment(
    key="business_savings",
    fields=schema.FIELDS,
    extraction=schema.EXTRACTION,
    extract_system=BUSINESS_SAVINGS_EXTRACT,
    choose_system=(
        "Du hjälper en svensk jämförelsesajt för sparande för företag. Välj de sidor som mest sannolikt "
        "innehåller aktuella räntor och villkor för sparkonton, placeringskonton och fasträntekonton för "
        "företag och föreningar (inte privatpersoner). Välj inte lån, kort, privatkonton eller nyheter."
    ),
    core=("rate_percent", "binding_months", "withdrawals"),
    data_dir=DATA / "business" / "savings",
    site_file=DATA / "business_savings.json",
    pos={"foretag": 6, "foretagssparkonto": 8, "placeringskonto": 7, "foretagsspar": 7, "privat": -5,
         "spara": 3, "sparkonto": 4, "fastrantekonto": 5, "ranta": 4, "rantor": 4},
    url_field="secondary_url",
    manual_banks=DATA / "business" / "banks_savings.yaml",
    **_BUSINESS_SHARED,
)

_current = "savings"


def use(key: str) -> Segment:
    global _current
    if key not in SEGMENTS:
        raise SystemExit(f"okänt segment {key!r} – välj bland {', '.join(SEGMENTS)}")
    _current = key
    return SEGMENTS[key]


def cur() -> Segment:
    return SEGMENTS[_current]
