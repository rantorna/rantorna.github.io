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
    dedupe_by_brand: bool = False         # flera varumärken kan dela webbplats (t.ex. SEB och Gamla Liv)

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

PENSION_RESOLVE = """Du kartlägger svenska livförsäkrings- och tjänstepensionsbolag åt en oberoende jämförelsesajt. Använd webbsökning och kontrollera på bolagets egna webbplatser.

Avgör om bolaget, under eget namn eller under ett annat varumärke, i dag förvaltar traditionell försäkring (garanterad pension/kapital, med återbäringsränta eller avkastningsränta) för kunder i Sverige – tjänstepension, privat pensionsförsäkring eller kapitalförsäkring. Räkna inte med: bara fondförsäkring/depåförsäkring, bara risk-/sjukförsäkringar, eller bestånd som är helt stängda utan publicerade räntor.

Ange för varje varumärke den svenska webbplatsen (homepage) och sidan som visar återbäringsränta, avkastning och konsolideringsgrad för den traditionella förvaltningen (product_url). Hitta aldrig på adresser. Ange bara adresser du faktiskt har sett."""

PENSION_EXTRACT = """Du extraherar nyckeltal för traditionell pensions- och kapitalförsäkring (garanterad förvaltning) ur ett svenskt försäkringsbolags egna webbsidor och rapporter, för en oberoende jämförelsesajt.

Regler:
- Ta med varje traditionell förvaltning eller produktlinje som har egna publicerade nyckeltal (t.ex. 'Traditionell förvaltning', 'Kapitalförsäkring Traditionell', separata portföljer för olika avtal). Hoppa över fondförsäkring, risk- och sjukförsäkring och stängda bestånd utan aktuella siffror.
- Ta bara med förvaltningar som tillhör det angivna bolaget/varumärket. Dokument om systerbolag eller andra bestånd på samma webbplats (t.ex. SEB Pension och Försäkring respektive Gamla Liv) ska ignoreras.
- rate_percent måste vara ett årstal som går att jämföra mellan bolag. Bolag med deklarerad årlig återbäringsränta: ta den (rate_kind = deklarerad årlig återbäringsränta). Bolag som redovisar avkastningsränta per månad (t.ex. "augusti 1,4 %", kolumner som "månad", "hittills i år", "senaste 12 månader"): rate_kind = månadsvis avkastningsränta, rate_percent = senaste 12 månaderna, monthly_rate_percent = senaste månaden. Använd aldrig en enskild månad eller "hittills i år" som rate_percent – finns ingen tolvmånaderssiffra, sätt null.
- Återbäringsräntan är inte totalavkastningen. Ange månaden den gäller (rate_month) och om den är före eller efter avgifter och avkastningsskatt (rate_basis) om bolaget anger det.
- Totalavkastning och konsolideringsgrad: ta de senast publicerade siffrorna och ange perioden.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, max ~300 tecken; vid tabeller hela tabellraden) och dokumentets index i "source".
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig.
- Procent som tal (4,5 % -> 4.5). Negativ avkastning som negativt tal.
- Om dokumenten motsäger varandra: använd det som ser mest aktuellt ut och nämn det i notes."""

SEGMENTS["pension"] = Segment(
    key="pension",
    fields=schema.PENSION_FIELDS,
    extraction=schema.PENSION_EXTRACTION,
    extract_system=PENSION_EXTRACT,
    choose_system=(
        "Du hjälper en svensk jämförelsesajt för traditionell pensions- och kapitalförsäkring. Välj de sidor "
        "som mest sannolikt innehåller aktuell återbäringsränta, totalavkastning, konsolideringsgrad, "
        "garantiränta och avgifter för den traditionella förvaltningen. Välj inte fondsidor, risk- eller "
        "sjukförsäkringar, nyheter eller allmänna pensionsguider."
    ),
    core=("rate_percent",),
    data_dir=DATA / "pension",
    site_file=DATA / "pension.json",
    resolve_system=PENSION_RESOLVE,
    resolve_out=DATA / "pension" / "institutions.json",
    resolve_hints=DATA / "pension" / "brand_hints.yaml",
    resolve_categories=("RIKSLI", "TJPAB", "TJPE", "TJPÖMS", "UTLFFL"),
    pos={"aterbaringsranta": 9, "aterbaring": 7, "avkastningsranta": 8, "traditionell": 7, "trad": 5,
         "konsolidering": 7, "konsolideringsgrad": 9, "konsolideringsniva": 9, "garanterad": 4, "garantiranta": 6,
         "avkastning": 5, "nyckeltal": 6, "pension": 2, "kapitalforsakring": 4, "fond": -4, "fonder": -4,
         "sjukforsakring": -5, "livforsakring": 0},
    terms_re=r"(återbäring|aterbaring|avkastning|konsolider|nyckeltal|traditionell|villkor|avgift)",
    manual_banks=DATA / "pension" / "banks.yaml",
    max_rate=20.0,
    dedupe_by_brand=True,
)

FINANCING_RESOLVE = """Du kartlägger svensk finansiering för små och medelstora företag åt en oberoende sajt. Använd webbsökning och kontrollera på aktörens egna webbplatser.

Avgör om aktören, under eget namn eller under ett annat varumärke, i dag erbjuder finansiering till svenska småföretag med ett publicerat erbjudande: företagslån, checkkredit/rörelsekredit, fakturaköp/factoring, startlån/mikrolån eller lån via gräsrotsfinansiering. Räkna inte med: bara privatlån, bara bolån, bara storföretag/koncerner via förfrågan, leasing av bilar eller bara förmedling utan eget utlåningserbjudande (men låneförmedlare som Lendo och plattformar som förmedlar till många långivare får tas med om de har en egen sida för företag – skriv då det i notes).

Ange för varje varumärke den svenska webbplatsen (homepage) och sidan som bäst beskriver företagsfinansieringen med villkor och priser (product_url). Hitta aldrig på adresser. Ange bara adresser du faktiskt har sett."""

FINANCING_EXTRACT = """Du extraherar fakta om finansiering för små och medelstora företag i Sverige ur en långivares egna webbsidor och dokument, för en oberoende sajt som hjälper företagare att hitta vem som kan finansiera dem.

Regler:
- Ta med varje finansieringsprodukt för svenska företag: företagslån, checkkredit/rörelsekredit, fakturaköp/factoring, startlån/mikrolån. Hoppa över privatlån, bolån, billeasing och tjänster bara för storföretag.
- Viktigast: belopp från–till, löptid, om nystartade företag kan få finansiering, krav (tid i drift, omsättning, borgen, säkerhet) och hur snabbt pengarna betalas ut.
- Kostnad: ange bara det som långivaren själv publicerar. Årsränta ('från 4,9 %') i rate_from_percent. Månadsavgift/månadsränta i procent av lånebeloppet ('från 1,5 % per månad') i monthly_fee_percent – räkna aldrig om den till årsränta själv. Effektiv ränta bara om långivaren anger den.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, max ~300 tecken) och dokumentets index i "source".
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig – särskilt inte om borgen eller nystartade.
- Belopp i kronor som tal (5 MSEK -> 5000000). Löptid i månader (3 år -> 36)."""

SEGMENTS["business_financing"] = Segment(
    key="business_financing",
    fields=schema.FINANCING_FIELDS,
    extraction=schema.FINANCING_EXTRACTION,
    extract_system=FINANCING_EXTRACT,
    choose_system=(
        "Du hjälper en svensk sajt om finansiering för småföretag. Välj de sidor som mest sannolikt beskriver "
        "långivarens företagslån, checkkredit, fakturaköp/factoring eller startlån: belopp, löptid, priser, krav "
        "(tid i drift, omsättning, borgen) och vilka företag som kan få finansiering. Välj inte privatlån, bolån, "
        "sparkonton, nyheter eller allmänna guider utan villkor."
    ),
    core=("product_type",),
    data_dir=DATA / "business" / "financing",
    site_file=DATA / "business_financing.json",
    resolve_system=FINANCING_RESOLVE,
    resolve_out=DATA / "business" / "financing_institutions.json",
    resolve_hints=DATA / "business" / "financing_hints.yaml",
    resolve_categories=("BANK", "MBANK", "KMB", "UTLFIL", "FILBK", "GRÄS"),
    pos={"foretag": 5, "foretagslan": 9, "lan": 4, "checkkredit": 8, "rorelsekredit": 8, "factoring": 8,
         "fakturakop": 8, "fakturabelaning": 8, "finansiering": 6, "startlan": 8, "mikrolan": 8, "kredit": 3,
         "priser": 3, "villkor": 3, "privat": -5, "bolan": -5, "privatlan": -6, "sparkonto": -5, "spara": -4},
    terms_re=r"(företag|foretag|lån|lan|kredit|faktura|villkor|prislista|priser)",
    manual_banks=DATA / "business" / "banks_financing.yaml",
    max_rate=40.0,
)

LOAN_RESOLVE = """Du kartlägger den svenska marknaden för privatlån (lån utan säkerhet till privatpersoner) åt en oberoende jämförelsesajt. Använd webbsökning och kontrollera på aktörens egna webbplatser.

Avgör om aktören, under eget namn eller under ett annat varumärke, i dag erbjuder privatlån, samlingslån eller andra konsumentlån med fast löptid till privatpersoner i Sverige. Räkna inte med: bara bolån, bara kreditkort eller kontokrediter, bara delbetalning i butik, bara företagslån, eller lån bara i andra länder. Låneförmedlare (t.ex. Lendo, Zmarta, Sambla, Advisa) tas med om privatpersoner ansöker via dem – skriv i notes att de förmedlar.

Ange för varje varumärke den svenska webbplatsen (homepage) och sidan som bäst beskriver privatlånet med ränta, avgifter och representativt exempel (product_url). Hitta aldrig på adresser. Ange bara adresser du faktiskt har sett."""

LOAN_EXTRACT = """Du extraherar fakta om privatlån (konsumentlån med fast löptid) i Sverige ur en långivares eller låneförmedlares egna webbsidor och dokument, för en oberoende jämförelsesajt.

Regler:
- Ta med varje lån för privatpersoner med egna villkor: privatlån/blancolån, samlingslån och lån med säkerhet (bil, båt, husvagn). Hoppa över bolån, kreditkort, kontokrediter, delbetalning i butik, SMS-lån utan fast löptid och företagslån.
- Viktigast: räntespannet (från–till), avgifter, belopp och löptid, och det representativa exemplet som långivare måste visa ('Vid ett lån på 150 000 kr … 12 år … rörlig ränta 6,95 % … effektiv ränta 7,45 % … totalt att betala …'). Ta exemplets siffror precis som de står – räkna inte om något.
- Om exemplet gäller ett annat lån än produkten (t.ex. ett billån på samma sida), koppla det inte till fel produkt.
- Låneförmedlare: sätt lender_role = låneförmedlare och ta förmedlarens publicerade spann och exempel.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, max ~300 tecken) och dokumentets index i "source".
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig.
- Räntor i procent som tal (6,95 % -> 6.95). Belopp i kronor som tal. Löptid i månader (12 år -> 144)."""

SEGMENTS["personal_loans"] = Segment(
    key="personal_loans",
    fields=schema.PERSONAL_LOAN_FIELDS,
    extraction=schema.PERSONAL_LOAN_EXTRACTION,
    extract_system=LOAN_EXTRACT,
    choose_system=(
        "Du hjälper en svensk jämförelsesajt för privatlån. Välj de sidor som mest sannolikt innehåller "
        "privatlånets räntespann, avgifter, lånebelopp, löptid och representativt exempel med effektiv ränta, "
        "samt villkor och prislistor för lån till privatpersoner. Välj inte bolån, sparkonton, kort, företagslån, "
        "nyheter eller allmänna guider."
    ),
    core=("rate_percent", "example_effective_rate_percent"),
    data_dir=DATA / "loans",
    site_file=DATA / "personal_loans.json",
    resolve_system=LOAN_RESOLVE,
    resolve_out=DATA / "loans" / "institutions.json",
    resolve_hints=DATA / "loans" / "brand_hints.yaml",
    resolve_categories=("BANK", "SPAR", "MBANK", "KMB", "KKRI", "UTLFIL", "FILBK", "UTLKMF"),
    pos={"privatlan": 9, "blancolan": 9, "samlingslan": 8, "lan": 4, "lana": 5, "lana-pengar": 6,
         "effektiv": 5, "representativt": 6, "exempel": 3, "billan": 3, "priser": 3, "prislista": 4, "villkor": 3,
         "bolan": -6, "foretag": -6, "foretagslan": -6, "spara": -5, "sparkonto": -5, "kort": -3, "kreditkort": -4},
    terms_re=r"(lån|lan|ränt|ranta|villkor|prislista|priser|effektiv)",
    manual_banks=DATA / "loans" / "banks.yaml",
    max_rate=45.0,
)

CARD_RESOLVE = """Du kartlägger den svenska marknaden för kreditkort och betalkort åt en oberoende jämförelsesajt. Använd webbsökning och kontrollera på utgivarens egna webbplatser.

Avgör om aktören, under eget namn eller under ett annat varumärke (t.ex. Eurocard, SAS EuroBonus, Coop, Volvo), i dag ger ut kreditkort eller betalkort med kredit till privatpersoner i Sverige. Räkna inte med: bara bankkort/debetkort kopplade till lönekonto, bara företagskort, förbetalda kort, eller kort bara i andra länder. Ett varumärke per kortfamilj med egen webbsida.

Ange för varje varumärke den svenska webbplatsen (homepage) och sidan som bäst beskriver kortet med avgifter, ränta och prislista (product_url). Hitta aldrig på adresser. Ange bara adresser du faktiskt har sett."""

CARD_EXTRACT = """Du extraherar fakta om kreditkort och betalkort för privatpersoner i Sverige ur utgivarens egna webbsidor, prislistor och villkor, för en oberoende jämförelsesajt.

Regler:
- Ta med varje kort som privatpersoner kan ansöka om (t.ex. Classic, Gold, Platinum som egna produkter). Hoppa över debetkort kopplade till lönekonto, företagskort, förbetalda kort och kort som inte längre säljs.
- Viktigast: årsavgift, avgifter per månad, ränta, räntefria dagar, valutapåslag, uttagsavgift och det representativa exemplets effektiva ränta.
- Avgifter står ofta i en prislista – citera tabellraden. Räkna aldrig om månadsavgift till årsavgift eller tvärtom.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, max ~300 tecken) och dokumentets index i "source".
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig.
- Procent som tal (1,75 % -> 1.75). Belopp i kronor som tal."""

SEGMENTS["cards"] = Segment(
    key="cards",
    fields=schema.CARD_FIELDS,
    extraction=schema.CARD_EXTRACTION,
    extract_system=CARD_EXTRACT,
    choose_system=(
        "Du hjälper en svensk jämförelsesajt för kreditkort. Välj de sidor som mest sannolikt innehåller kortets "
        "årsavgift, ränta, räntefria dagar, valutapåslag, uttagsavgifter, representativt exempel, prislistor och "
        "villkor för privatpersoner. Välj inte lån, sparkonton, företagskort, nyheter eller allmänna guider."
    ),
    core=("annual_fee_sek", "rate_percent"),
    data_dir=DATA / "cards",
    site_file=DATA / "cards.json",
    resolve_system=CARD_RESOLVE,
    resolve_out=DATA / "cards" / "institutions.json",
    resolve_hints=DATA / "cards" / "brand_hints.yaml",
    resolve_categories=("BANK", "SPAR", "MBANK", "KMB", "KKRI", "UTLFIL", "FILBK", "UTLKMF"),
    pos={"kreditkort": 9, "kort": 5, "betalkort": 7, "prislista": 6, "priser": 4, "avgifter": 5, "villkor": 3,
         "valutapaslag": 7, "arsavgift": 7, "effektiv": 4, "mastercard": 4, "visa": 3, "gold": 3, "platinum": 3,
         "lan": -4, "privatlan": -6, "bolan": -6, "spara": -5, "sparkonto": -5, "foretag": -6, "foretagskort": -6},
    terms_re=r"(kort|prislista|priser|avgift|villkor|ränt|ranta)",
    manual_banks=DATA / "cards" / "banks.yaml",
    max_rate=45.0,
)

YOUTH_EXTRACT = """Du extraherar fakta om sparkonton för BARN och UNGA i Sverige ur en banks egna webbsidor och villkorsdokument, för en oberoende jämförelsesajt.

Regler:
- Ta med två slags konton:
  1. Konton särskilt för barn eller unga (youth_only = true): barnsparkonton, ungdomskonton och ungdomssparkonton med åldersgräns, fasträntekonton för barn.
  2. Vanliga sparkonton och fasträntekonton som banken UTTRYCKLIGEN säger kan öppnas i barnets namn, för barn eller av förmyndare åt barn (youth_only = false, target_group = barn). Citera texten som säger det.
- Hoppa över fondsparande, ISK, Junior-ISK, kapitalförsäkringar och kort. Ta inte med vanliga konton där det inte står att barn kan ha dem.
- Varje bindningstid för fasträntekonton är en egen produkt.
- Ange åldersgränser och vad som händer när de passeras, och vem som får öppna kontot och sätta in pengar.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, inklusive siffror och procenttecken, max ~300 tecken) och dokumentets index i "source".
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig.
- Räntor anges i procent som tal (3,25 % -> 3.25). Belopp i kronor som tal.
- Finns inga barn- eller ungdomskonton i dokumenten: returnera en tom produktlista."""

SEGMENTS["youth"] = Segment(
    key="youth",
    fields=schema.YOUTH_FIELDS,
    extraction=schema.YOUTH_EXTRACTION,
    extract_system=YOUTH_EXTRACT,
    choose_system=(
        "Du hjälper en svensk jämförelsesajt för sparkonton för barn och unga. Välj de sidor som mest sannolikt "
        "innehåller räntor och villkor för barnsparkonton, ungdomskonton och sparande till barn (åldersgränser, vem "
        "som kan öppna, räntesatser, prislistor). Välj inte fonder, Junior-ISK, försäkringar, lån eller nyheter."
    ),
    core=("rate_percent", "target_group"),
    data_dir=DATA / "youth",
    site_file=DATA / "youth.json",
    # Samma banker som för sparkonton – inga nya uppslag behövs.
    resolve_system=SAVINGS_RESOLVE,
    resolve_out=DATA / "institutions.json",
    resolve_hints=DATA / "brand_hints.yaml",
    resolve_categories=(),
    manual_banks=DATA / "banks.yaml",
    pos={"barn": 9, "barnsparkonto": 10, "barnspar": 9, "ungdom": 9, "ungdomskonto": 10, "unga": 7, "junior": 3,
         "spara-till-barn": 9, "barnkonto": 9, "ranta": 4, "rantor": 4, "sparkonto": 3, "fond": -4, "fonder": -4,
         "isk": -3, "forsakring": -5, "lan": -5, "bolan": -6, "foretag": -6},
    terms_re=r"(barn|ungdom|unga|villkor|ränt|ranta|spar)",
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
