"""Kör insamlingen: hitta sidor → hämta → (om relevant text ändrats) tolka → kontrollera → spara.

    python -m collector.run                 # alla banker
    python -m collector.run --bank sbab     # en bank
    python -m collector.run --discover-only # bara hitta och hämta sidor, ingen tolkning
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

from . import discover, extract, fetch, jev, llm, verify

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PRODUCTS = DATA / "products"
MAX_TOTAL_CHARS = 250_000

RELEVANT = re.compile(r"(%|ränt|rant|uttag|insätt|insatt|bind|villkor|garanti|kr\b|sek\b|belopp|månad|år\b)", re.I)


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def relevant_hash(pages: list[fetch.Page]) -> str:
    """Hash över de rader som kan påverka svaret – så att t.ex. ett nytt
    nyhetsdatum i sidfoten inte triggar en ny (kostsam) tolkning."""
    h = hashlib.sha256()
    for p in sorted(pages, key=lambda p: p.url):
        h.update(p.url.encode())
        for line in p.text.splitlines():
            if RELEVANT.search(line):
                h.update(line.encode())
    return h.hexdigest()[:16]


def load_banks() -> list[dict]:
    return yaml.safe_load((DATA / "banks.yaml").read_text())


def collect_pages(bank: dict, log) -> list[fetch.Page]:
    found = discover.candidates(bank, log=log)
    urls = discover.choose(bank, found, log=log)
    pages = []
    for u in urls:
        p = fetch.get(u)
        if p.error or len(p.text) < 200:
            log(f"  - {u}: {p.error or 'för lite text'}")
            continue
        log(f"  + {p.url} ({len(p.text)} tecken, {p.via})")
        pages.append(p)
    extra = discover.linked_terms(pages, bank["homepage"], {p.url for p in pages})
    for u in extra:
        p = fetch.get(u, allow_browser=False)
        if not p.error and len(p.text) >= 200:
            log(f"  + {p.url} ({len(p.text)} tecken, {p.kind})")
            pages.append(p)
    # Håll nere storleken: korta ner dokument tills totalen ryms.
    total = sum(len(p.text) for p in pages)
    if total > MAX_TOTAL_CHARS:
        share = MAX_TOTAL_CHARS // max(1, len(pages))
        for p in pages:
            p.text = p.text[: max(share, 8000)]
    return pages


def process(bank: dict, discover_only: bool, force: bool, log) -> dict | None:
    log(f"\n== {bank['name']}")
    out_path = PRODUCTS / f"{bank['id']}.json"
    previous = json.loads(out_path.read_text()) if out_path.exists() else None
    pages = collect_pages(bank, log)
    record = {
        "bank": {k: bank.get(k) for k in ("id", "name", "homepage", "home_country", "kind")},
        "checked_at": now(),
        "sources": [{"url": p.url, "title": p.title, "kind": p.kind, "via": p.via, "chars": len(p.text)} for p in pages],
    }
    if not pages:
        record |= {"status": "kunde inte hämtas", "products": (previous or {}).get("products", [])}
        if previous:
            record["changed_at"] = previous.get("changed_at")
            record["source_hash"] = previous.get("source_hash")
        out_path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
        return record
    h = relevant_hash(pages)
    if discover_only:
        log(f"  hash {h}")
        return None
    if previous and previous.get("source_hash") == h and not force:
        log("  oförändrat – ingen ny tolkning")
        previous["checked_at"] = record["checked_at"]
        out_path.write_text(json.dumps(previous, ensure_ascii=False, indent=1))
        return previous
    if not llm.available():
        log("  ! ingen LLM – hoppar över tolkning")
        return None
    try:
        raw = extract.extract(bank, pages)
    except Exception as e:
        log(f"  ! tolkning misslyckades: {e}")
        if previous:
            previous["checked_at"] = record["checked_at"]
            previous["status"] = f"senaste tolkning misslyckades ({str(e)[:80]})"
            out_path.write_text(json.dumps(previous, ensure_ascii=False, indent=1))
        return previous
    docs = [p.text for p in pages]
    prev_by_name = {p["name"]: p for p in (previous or {}).get("products", [])}
    products = [verify.verify_product(p, docs, prev_by_name.get(p["name"])) for p in raw.get("products", [])]
    if jev.available():
        for p in products:
            try:
                jev.check_product(p, docs, bank["name"])
                verify.restatus(p)
            except Exception as e:
                log(f"  ! jev: {e}")
    record |= {
        "status": "ok" if products else "inga produkter hittades",
        "notes": raw.get("notes"),
        "products": products,
        "source_hash": h,
        "changed_at": record["checked_at"],
        "model": llm.MODEL,
    }
    for p in products:
        f = p["fields"]
        log(f"  * {p['name']}: {f['rate_percent']['value']} % [{p['status']}] "
            + ", ".join(f"{k}:{v['status']}" for k, v in f.items() if v["status"] not in ("belagt", "okänt")))
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    return record


def build_site_data():
    """Slår ihop allt till data/rates.json som sidan läser."""
    banks = []
    for f in sorted(PRODUCTS.glob("*.json")):
        r = json.loads(f.read_text())
        banks.append({k: r.get(k) for k in ("bank", "checked_at", "changed_at", "status", "notes", "sources", "products")})
    (DATA / "rates.json").write_text(json.dumps({"generated_at": now(), "banks": banks}, ensure_ascii=False))


def load_dotenv():
    """Lokala nycklar i .env (ignoreras av git). Miljövariabler har företräde."""
    import os
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", action="append", help="bank-id (kan upprepas)")
    ap.add_argument("--discover-only", action="store_true")
    ap.add_argument("--force", action="store_true", help="tolka även om källorna inte ändrats")
    args = ap.parse_args()
    PRODUCTS.mkdir(parents=True, exist_ok=True)
    banks = [b for b in load_banks() if not args.bank or b["id"] in args.bank]
    log = lambda s: print(s, flush=True)
    failures = 0
    try:
        for b in banks:
            try:
                process(b, args.discover_only, args.force, log)
            except Exception as e:  # en trasig bank ska inte stoppa resten
                failures += 1
                log(f"  ! {b['id']}: {type(e).__name__}: {e}")
    finally:
        fetch.close()
    if not args.discover_only:
        build_site_data()
    log(f"\nLLM: {llm.usage}  Jev: {jev.usage}")
    sys.exit(1 if failures == len(banks) and banks else 0)


if __name__ == "__main__":
    main()
