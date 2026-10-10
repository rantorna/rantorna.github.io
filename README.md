# räntorna

Automatiskt uppdaterad jämförelse av sparräntor i Sverige, med villkoren: bindning, uttag, belopp, vem som får öppna kontot och insättningsgaranti. Sidan ligger på **https://rantorna.github.io**.

## Hur det fungerar

`collector/` körs varje natt i GitHub Actions ([.github/workflows/collect.yml](.github/workflows/collect.yml)):

1. **discover.py** – hittar varje banks spar- och villkorssidor via sitemap och länkar. Det finns ingen kod per bank.
2. **fetch.py** – hämtar HTML och PDF. Sidor som kräver JavaScript hämtas med en headless Chromium som reserv.
3. **extract.py** – Claude fyller i schemat ([schema.py](collector/schema.py)). Varje värde ska ha ett ordagrant citat och en källa.
4. **verify.py** – kontrollerar att citatet står i källan och att talet står i citatet. Annars blir värdet null ("okänt"). Orimliga räntor och stora ränteskutt flaggas också.
5. **jev.py** (valfritt) – TypeSafe Jev bedömer om citatets sammanhang stöder påståendet.

Tolkningen körs bara när den relevanta texten på en banks sidor har ändrats.

Resultatet hamnar i `data/products/<bank>.json` och slås ihop till `data/rates.json`, som den statiska sidan (`index.html`, `app.js`) läser. Git-historiken är räntehistoriken.

## Lägga till en bank

Lägg till en post i [data/banks.yaml](data/banks.yaml). `start_urls` är valfritt.

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

Valfria variabler: `RANTORNA_MODEL` (standard `claude-opus-5-5`), `RANTORNA_CHEAP_MODEL` (standard `claude-haiku-5-5`, används för sidurval).
