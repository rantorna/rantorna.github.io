"""Tar reda på vilka institut som erbjuder sparkonton till privatpersoner i Sverige,
under vilka varumärken och på vilka webbplatser. Claude söker på webben.

    python -m collector.resolve                  # svenska institut + ledtrådar, sedan utländska i mån av utrymme
    python -m collector.resolve --limit 40       # högst 40 uppslag i den här körningen
    python -m collector.resolve --only "Lunar"   # bara institut/ledtrådar vars namn innehåller texten

Resultatet sparas i data/institutions.json och återanvänds. Uppslag görs om efter RECHECK_DAYS.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import yaml

from . import llm

DATA = Path(__file__).resolve().parent.parent / "data"
OUT = DATA / "institutions.json"
RECHECK_DAYS = 120
WORKERS = 6

SYSTEM = """Du kartlägger den svenska marknaden för sparkonton åt en oberoende jämförelsesajt. Använd webbsökning och kontrollera på institutets egna webbplatser.

Avgör om institutet, under eget namn eller under ett annat varumärke, i dag erbjuder sparkonton eller annan inlåning som privatpersoner i Sverige kan öppna (svensk webbplats eller svenskspråkig sida, öppnas med t.ex. BankID). Räkna inte med: bara företagskunder, bara lån eller kort, ISK/fonder/aktier, pensionsprodukter, eller sparkonton som bara erbjuds i andra länder.

För plattformar som förmedlar sparkonton hos andra banker (t.ex. Avanza, Nordnet eller Sambla): ta med varumärket om kunden öppnar sparkontot via plattformen, och skriv i notes vilka banker som står för inlåningen.

Ange för varje varumärke den officiella svenska webbplatsen (homepage) och den sida som bäst listar sparkontona och deras räntor (savings_url). Hitta aldrig på adresser. Ange bara adresser du faktiskt har sett."""

SCHEMA = {
    "type": "object",
    "properties": {
        "legal_name": {"type": "string"},
        "offers_savings_in_sweden": {"type": "boolean"},
        "home_country": {"type": ["string", "null"], "description": "ISO-landskod för landet där institutet har sitt banktillstånd."},
        "brands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string"},
                    "homepage": {"type": "string"},
                    "savings_url": {"type": ["string", "null"]},
                    "kind": {"type": "string", "enum": ["storbank", "sparbank", "nischbank", "neobank", "utlandsk_bank", "kreditmarknadsbolag", "plattform", "medlemsbank", "annat"]},
                },
                "required": ["brand", "homepage", "savings_url", "kind"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "description": "Kort motivering och källor, max 400 tecken."},
    },
    "required": ["legal_name", "offers_savings_in_sweden", "home_country", "brands", "notes"],
    "additionalProperties": False,
}

_lock = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load() -> dict:
    return json.loads(OUT.read_text()) if OUT.exists() else {}


def save(db: dict) -> None:
    with _lock:
        OUT.write_text(json.dumps(dict(sorted(db.items())), ensure_ascii=False, indent=1))


def queue(db: dict, only: str | None) -> list[tuple[str, str]]:
    """(nyckel, fråga) i prioritetsordning: ledtrådar, svenska institut, utländska."""
    fresh_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECHECK_DAYS)

    def due(key):
        e = db.get(key)
        return not e or dt.datetime.fromisoformat(e["checked_at"]) < fresh_after

    items = []
    hints = yaml.safe_load((DATA / "brand_hints.yaml").read_text()) or []
    for h in hints:
        items.append((0, f"hint:{h}", f'Varumärket/företaget "{h}" marknadsförs för sparande i Sverige. Vilket institut står bakom, och vilka varumärken med egna sparkonton finns?'))
    for r in json.loads((DATA / "fi_register.json").read_text()):
        prio = 2 if r["category"] in ("UTLBGH", "UTLKGH") else 1
        items.append((prio, f"fi:{r['fi_id']}",
                      f'Institut i Finansinspektionens register: "{r["name"]}" (FI-id {r["fi_id"]}, kategori: {r["category_name"]}).'))
    items.sort(key=lambda x: x[0])
    out = [(k, q) for _, k, q in items if due(k)]
    if only:
        out = [(k, q) for k, q in out if only.lower() in q.lower()]
    return out


def resolve_one(key: str, question: str) -> dict:
    res = llm.research_call(SYSTEM, question + "\n\nSvara enligt schemat.", SCHEMA)
    res["checked_at"] = now()
    res["query"] = question
    for b in res.get("brands", []):
        for f in ("homepage", "savings_url"):
            if b.get(f) and not b[f].startswith("http"):
                b[f] = "https://" + b[f].lstrip("/")
    return res


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\b(ab|publ|bank aktiebolag|aktiebolag|bankaktiebolag|asa|as|a/s|gmbh|uab|plc|sa)\b", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def site_key(url: str) -> str:
    u = urlparse(url)
    host = u.netloc.lower().removeprefix("www.")
    loc = re.match(r"^/([a-z]{2}(?:-[a-z]{2})?)(?:/|$)", u.path, re.I)
    return host + ("/" + loc.group(1).lower() if loc else "")


def banks_from_institutions() -> list[dict]:
    """Bankposter för insamlingen, härledda ur uppslagen."""
    db = load()
    out, seen = [], set()
    for key, e in sorted(db.items()):
        if not e.get("offers_savings_in_sweden"):
            continue
        for b in e.get("brands", []):
            if not b.get("savings_url") and b.get("kind") == "annat":
                continue
            sk = site_key(b.get("savings_url") or b["homepage"])
            if sk in seen:
                continue
            seen.add(sk)
            entry = {
                "id": slug(b["brand"]) or slug(e["legal_name"]),
                "name": b["brand"],
                "homepage": b["homepage"],
                "home_country": e.get("home_country"),
                "kind": b.get("kind"),
                "legal_name": e.get("legal_name"),
                "source": key,
            }
            if b.get("savings_url"):
                entry["start_urls"] = [b["savings_url"]]
            out.append(entry)
    return out


def main():
    from .run import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--only")
    ap.add_argument("--domestic-only", action="store_true")
    args = ap.parse_args()
    db = load()
    todo = queue(db, args.only)
    if args.domestic_only:
        todo = [(k, q) for k, q in todo if "gränsöverskridande" not in q]
    todo = todo[: args.limit]
    print(f"{len(todo)} uppslag att göra")
    done = 0
    with ThreadPoolExecutor(WORKERS) as pool:
        futs = {pool.submit(resolve_one, k, q): k for k, q in todo}
        for f in as_completed(futs):
            k = futs[f]
            try:
                res = f.result()
            except Exception as e:
                print(f"  ! {k}: {str(e)[:200]}", flush=True)
                continue
            with _lock:
                db[k] = res
            done += 1
            brands = ", ".join(f"{b['brand']} <{b.get('savings_url') or b['homepage']}>" for b in res.get("brands", []))
            print(f"  {'+' if res['offers_savings_in_sweden'] else '-'} {res['legal_name']}: {brands}", flush=True)
            if done % 5 == 0:
                save(db)
    save(db)
    print(f"klart: {done}, LLM {llm.usage}")


if __name__ == "__main__":
    main()
