"""Låter Claude fylla i schemat från bankens egna dokument."""
from __future__ import annotations

from . import llm
from .fetch import Page
from . import segments

MAX_DOC_CHARS = 60_000

# Prompten och schemat kommer från segmentet (collector/segments.py).


def build_prompt(bank: dict, pages: list[Page]) -> str:
    parts = [f"Bank: {bank['name']} ({bank['homepage']})\n"]
    for i, p in enumerate(pages):
        text = p.text[:MAX_DOC_CHARS]
        parts.append(f'<document index="{i}" url="{p.url}" title="{p.title}">\n{text}\n</document>')
    parts.append("Extrahera alla produkter enligt schemat.")
    return "\n\n".join(parts)


EMPTY = {"value": None, "quote": None, "source": None}


def normalize(raw: dict) -> dict:
    """Svaret kommer via ett verktygsanrop och följer schemat nästan alltid – men inte garanterat.
    Felformade delar blir okända värden i stället för att stoppa tolkningen av hela banken."""
    names = [f[0] for f in segments.cur().fields]
    products = []
    for p in raw.get("products") or [] if isinstance(raw, dict) else []:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str):
            continue
        fields = p.get("fields") if isinstance(p.get("fields"), dict) else {}
        p["fields"] = {k: ({**EMPTY, **fields[k]} if isinstance(fields.get(k), dict) else dict(EMPTY)) for k in names}
        p["rate_tiers"] = [t for t in p.get("rate_tiers") or [] if isinstance(t, dict)]
        products.append(p)
    return {"products": products, "notes": raw.get("notes") if isinstance(raw, dict) else None}


def extract(bank: dict, pages: list[Page]) -> dict:
    return normalize(llm.json_call(
        task="extract",
        system=segments.cur().extract_system,
        user=build_prompt(bank, pages),
        schema=segments.cur().extraction,
        max_tokens=64000,
    ))
