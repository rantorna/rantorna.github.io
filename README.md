# räntorna

Automatiskt uppdaterad jämförelse av sparräntor i Sverige, med villkoren: bindning, uttag, belopp, vem som får öppna kontot och insättningsgaranti. Sidan ligger på **https://rantorna.github.io**.

## Hur det fungerar

`collector/` körs varje natt i GitHub Actions ([.github/workflows/collect.yml](.github/workflows/collect.yml)):

0. **registry.py** (måndagar) – hämtar alla institut med inlåningstillstånd ur FI:s företagsregister till `data/fi_register.json`.
   **resolve.py** – Claude med webbsökning tar reda på vilka institut som erbjuder sparkonton till privatpersoner i Sverige, under vilka varumärken och på vilka sajter (`data/institutions.json`). Varumärken som inte heter som institutet står i `data/brand_hints.yaml`. Svaren återanvänds och kontrolleras igen efter 120 dagar.
1. **discover.py** – hittar varje banks spar- och villkorssidor via sitemap och länkar. Det finns ingen kod per bank.
2. **fetch.py** – hämtar HTML och PDF. Sidor som kräver JavaScript hämtas med en headless Chromium som reserv.
3. **extract.py** – Claude fyller i schemat ([schema.py](collector/schema.py)). Varje värde ska ha ett ordagrant citat och en källa.
4. **verify.py** – kontrollerar att citatet står i källan och att talet står i citatet. Annars blir värdet null ("okänt"). Orimliga räntor och stora ränteskutt flaggas också.
5. **jev.py** (valfritt) – TypeSafe Jev bedömer om citatets sammanhang stöder påståendet.

Tolkningen körs bara när den relevanta texten på en banks sidor har ändrats.

Resultatet hamnar i `data/products/<bank>.json` och slås ihop till `data/rates.json`, som den statiska sidan (`index.html`, `app.js`) läser. Git-historiken är räntehistoriken.

## Lägga till eller rätta en bank

Bankerna kommer automatiskt från FI-registret. [data/banks.yaml](data/banks.yaml) används bara för att överstyra (samma `id` eller sajt) eller lägga till något som saknas; `skip: true` tar bort en bank.

## Användbara flaggor

- `--rediscover` – leta bankens sidor på nytt (annars återanvänds förra veckans)
- `--reverify` – kör om citat- och Jev-kontrollen mot sparade tolkningar i `data/raw/`, utan nya Claude-anrop
- `--force` – tolka om även om källorna är oförändrade

## Köra lokalt

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/python -m playwright install chromium
cp .env.example .env   # fyll i ANTHROPIC_API_KEY (eller CLAUDE_CODE_OAUTH_TOKEN)
.venv/bin/python -m collector.run --bank sbab
python3 -m http.server 8000
```

## Secrets i GitHub

| Secret | Behövs | Vad |
|---|---|---|
| `ANTHROPIC_API_KEY` | ett av de två | Claude API |
| `CLAUDE_CODE_OAUTH_TOKEN` | ett av de två | `claude setup-token`, använder en Claude-prenumeration |
| `TYPESAFE_API_KEY` | valfritt | Jev-kontroll |

Valfria variabler: `RANTORNA_MODEL` (standard `claude-sonnet-5-5` i Actions), `RANTORNA_CHEAP_MODEL` (standard `claude-haiku-5-5`, används för sidurval).
