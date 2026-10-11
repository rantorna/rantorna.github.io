"""Låter Claude fylla i schemat från bankens egna dokument."""
from __future__ import annotations

from . import llm
from .fetch import Page
from .schema import EXTRACTION

MAX_DOC_CHARS = 60_000

SYSTEM = """Du extraherar fakta om sparkonton (inlåning) för privatpersoner i Sverige ur en banks egna webbsidor och villkorsdokument, för en oberoende jämförelsesajt.

Regler:
- Ta med varje separat sparprodukt med egen ränta eller egna villkor som en privatperson i Sverige kan öppna (varje bindningstid för fasträntekonton är en egen produkt). Hoppa över företagskonton, barnkonton, ISK/depåer, lån, produkter som inte längre säljs och konton för särskilda ändamål (skogskonto, skogsskadekonto, upphovsmannakonto, klientmedelskonto, pensionssparkonto).
- Om samma konto har olika ränta beroende på medlemskap, betalpaket eller kundnivå (t.ex. "Plus", "Premium"): ta med varje variant som en egen produkt med variantens namn, och sätt requires_other_products till true för de betalda varianterna.
- Varje värde måste beläggas med ett ORDAGRANT citat ur dokumenten (kopiera tecken för tecken, inklusive siffror och procenttecken, max ~300 tecken) och dokumentets index i "source".
- Finns inget belägg: sätt value, quote och source till null. Gissa aldrig och dra inga slutsatser från allmän kunskap om banken.
- Räntor anges i procent som tal (3,25 % -> 3.25). Belopp i kronor som tal.
- Sammanfattande textfält skrivs på svenska, korta och sakliga, men måste ändå ha ett citat som stöd.
- Om dokumenten motsäger varandra: använd det som ser mest aktuellt ut och nämn det i notes."""


def build_prompt(bank: dict, pages: list[Page]) -> str:
    parts = [f"Bank: {bank['name']} ({bank['homepage']})\n"]
    for i, p in enumerate(pages):
        text = p.text[:MAX_DOC_CHARS]
        parts.append(f'<document index="{i}" url="{p.url}" title="{p.title}">\n{text}\n</document>')
    parts.append("Extrahera alla sparprodukter enligt schemat.")
    return "\n\n".join(parts)


def extract(bank: dict, pages: list[Page]) -> dict:
    return llm.json_call(
        task="extract",
        system=SYSTEM,
        user=build_prompt(bank, pages),
        schema=EXTRACTION,
        max_tokens=64000,
    )
