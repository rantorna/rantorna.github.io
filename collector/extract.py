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


def extract(bank: dict, pages: list[Page]) -> dict:
    return llm.json_call(
        task="extract",
        system=segments.cur().extract_system,
        user=build_prompt(bank, pages),
        schema=segments.cur().extraction,
        max_tokens=64000,
    )
