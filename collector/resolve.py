"""Tar reda på vilka institut som erbjuder segmentets produkt (sparkonton, bolån …) till
privatpersoner i Sverige, under vilka varumärken och på vilka webbplatser. Claude söker på webben.

    python -m collector.resolve                       # sparkonton: ledtrådar, svenska institut, sedan utländska
    python -m collector.resolve --segment mortgage    # bolån
    python -m collector.resolve --limit 40            # högst 40 uppslag i den här körningen
    python -m collector.resolve --only "Lunar"        # bara institut/ledtrådar vars namn innehåller texten

Resultatet sparas i segmentets resolve_out och återanvänds. Uppslag görs om efter RECHECK_DAYS.
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

from . import llm, segments

DATA = Path(__file__).resolve().parent.parent / "data"
RECHECK_DAYS = 120
WORKERS = 6

# Frågan till modellen kommer från segmentet (collector/segments.py).

SCHEMA = {
    "type": "object",
    "properties": {
        "legal_name": {"type": "string"},
        "offers_in_sweden": {"type": "boolean", "description": "Erbjuder institutet produkten till privatpersoner i Sverige?"},
        "home_country": {"type": ["string", "null"], "description": "ISO-landskod för landet där institutet har sitt banktillstånd."},
        "brands": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string"},
                    "homepage": {"type": "string"},
                    "product_url": {"type": ["string", "null"], "description": "Sidan som bäst visar produkterna och räntorna."},
                    "kind": {"type": "string", "enum": ["storbank", "sparbank", "nischbank", "neobank", "utlandsk_bank", "kreditmarknadsbolag", "plattform", "medlemsbank", "annat"]},
                },
                "required": ["brand", "homepage", "product_url", "kind"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string", "description": "Kort motivering och källor, max 400 tecken."},
    },
    "required": ["legal_name", "offers_in_sweden", "home_country", "brands", "notes"],
    "additionalProperties": False,
}

_lock = threading.Lock()


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load() -> dict:
    out = segments.cur().resolve_out
    return json.loads(out.read_text()) if out.exists() else {}


def save(db: dict) -> None:
    with _lock:
        out = segments.cur().resolve_out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(dict(sorted(db.items())), ensure_ascii=False, indent=1))


def queue(db: dict, only: str | None) -> list[tuple[str, str]]:
    """(nyckel, fråga) i prioritetsordning: ledtrådar, svenska institut, utländska."""
    fresh_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECHECK_DAYS)

    def due(key):
        e = db.get(key)
        return not e or dt.datetime.fromisoformat(e["checked_at"]) < fresh_after

    items = []
    seg = segments.cur()
    hints = yaml.safe_load(seg.resolve_hints.read_text()) or [] if seg.resolve_hints.exists() else []
    for h in hints:
        items.append((0, f"hint:{h}", f'Varumärket/företaget "{h}" marknadsförs i Sverige. Vilket institut står bakom, och vilka varumärken finns?'))
    for r in json.loads((DATA / "fi_register.json").read_text()):
        if seg.resolve_categories and r["category"] not in seg.resolve_categories:
            continue
        prio = 2 if r["category"] in ("UTLBGH", "UTLKGH") else 1
        items.append((prio, f"fi:{r['fi_id']}",
                      f'Institut i Finansinspektionens register: "{r["name"]}" (FI-id {r["fi_id"]}, kategori: {r["category_name"]}).'))
    items.sort(key=lambda x: x[0])
    out = [(k, q) for _, k, q in items if due(k)]
    if only:
        out = [(k, q) for k, q in out if only.lower() in q.lower()]
    return out


def resolve_one(key: str, question: str) -> dict:
    res = llm.research_call(segments.cur().resolve_system, question + "\n\nSvara enligt schemat.", SCHEMA)
    res["checked_at"] = now()
    res["query"] = question
    for b in res.get("brands", []):
        for f in ("homepage", "product_url"):
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
        if not e.get("offers_in_sweden", e.get("offers_savings_in_sweden")):
            continue
        for b in e.get("brands", []):
            url = b.get("product_url") or b.get("savings_url")
            if not url and b.get("kind") == "annat":
                continue
            sk = site_key(url or b["homepage"])
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
            if url:
                entry["start_urls"] = [url]
            out.append(entry)
    return out


def main():
    from .run import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--only")
    ap.add_argument("--domestic-only", action="store_true")
    ap.add_argument("--segment", default="savings")
    args = ap.parse_args()
    segments.use(args.segment)
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
            brands = ", ".join(f"{b['brand']} <{b.get('product_url') or b['homepage']}>" for b in res.get("brands", []))
            print(f"  {'+' if res['offers_in_sweden'] else '-'} {res['legal_name']}: {brands}", flush=True)
            if done % 5 == 0:
                save(db)
    save(db)
    print(f"klart: {done}, LLM {llm.usage}")


if __name__ == "__main__":
    main()
