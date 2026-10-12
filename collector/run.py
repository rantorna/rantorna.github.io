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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import discover, extract, fetch, jev, llm, verify

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PRODUCTS = DATA / "products"
RAW = DATA / "raw"  # Claudes råsvar, så att kontrollen kan köras om utan nya anrop
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
    """Banker från uppslagen i FI-registret, plus/överstyrda av data/banks.yaml."""
    from .resolve import banks_from_institutions, site_key

    manual = yaml.safe_load((DATA / "banks.yaml").read_text()) or []
    ids = {b["id"] for b in manual}
    sites = {site_key(b["homepage"]) for b in manual}
    sites |= {site_key(u) for b in manual for u in b.get("start_urls", [])}
    out = list(manual)
    for b in banks_from_institutions():
        if b["id"] in ids or site_key(b["homepage"]) in sites or any(site_key(u) in sites for u in b.get("start_urls", [])):
            continue
        ids.add(b["id"])
        out.append(b)
    return [b for b in out if not b.get("skip")]


REDISCOVER_DAYS = 7


def collect_pages(bank: dict, log, previous: dict | None = None, rediscover: bool = False) -> list[fetch.Page]:
    """Återanvänder förra körningens sidor (så att hashen bara ändras när innehållet
    gör det) och letar nya sidor en gång i veckan eller när en gammal sida fallerat."""
    prev_urls = [s["url"] for s in (previous or {}).get("sources", [])]
    disc = (previous or {}).get("discovered_at")
    stale = not disc or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(disc)).days >= REDISCOVER_DAYS
    if prev_urls and not stale and not rediscover:
        pages = []
        for u in prev_urls:
            p = fetch.get(u) if not u.lower().endswith(".pdf") else fetch.get(u, allow_browser=False)
            if p.error or len(p.text) < 200:
                log(f"  - {u}: {p.error or 'för lite text'} – letar nya sidor")
                return collect_pages(bank, log, previous, rediscover=True)
            pages.append(p)
        log(f"  {len(pages)} kända sidor")
        return pages
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


def process(bank: dict, discover_only: bool, force: bool, log, rediscover: bool = False,
            reverify: bool = False, relink_only: bool = False) -> dict | None:
    log(f"\n== {bank['name']}")
    out_path = PRODUCTS / f"{bank['id']}.json"
    previous = json.loads(out_path.read_text()) if out_path.exists() else None
    if relink_only:
        if not previous or not previous.get("sources"):
            return previous
        pages = []
        for src in previous["sources"]:
            pg = fetch.get(src["url"], allow_browser=src.get("via") == "browser")
            pages.append(pg if not pg.error else fetch.Page(url=src["url"], title=src.get("title", ""), text=""))
        n = relink(previous, pages)
        log(f"  {n} källindex rättade")
        out_path.write_text(json.dumps(previous, ensure_ascii=False, indent=1))
        return previous
    pages = collect_pages(bank, log, previous, rediscover=rediscover)
    reused = previous and [s["url"] for s in previous.get("sources", [])] == [p.url for p in pages]
    record = {
        "bank": {k: bank.get(k) for k in ("id", "name", "homepage", "home_country", "kind", "legal_name")},
        "checked_at": now(),
        "discovered_at": (previous or {}).get("discovered_at") if reused else now(),
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
    if previous and previous.get("source_hash") == h and not force and not reverify:
        log("  oförändrat – ingen ny tolkning")
        previous["checked_at"] = record["checked_at"]
        previous["discovered_at"] = record["discovered_at"]
        # Källistan behålls i sin gamla ordning – produkternas källindex pekar dit.
        if [x["url"] for x in previous.get("sources", [])] != [x["url"] for x in record["sources"]]:
            relink(previous, pages)
        out_path.write_text(json.dumps(previous, ensure_ascii=False, indent=1))
        return previous
    if not llm.available():
        log("  ! ingen LLM – hoppar över tolkning")
        return None
    raw_path = RAW / f"{bank['id']}.json"
    if reverify:
        if not raw_path.exists():
            log("  ingen sparad tolkning – hoppar över")
            return previous
        raw = json.loads(raw_path.read_text())["extraction"]
        record["source_hash"] = h
        return finish(bank, record, raw, pages, previous, out_path, log)
    try:
        raw = extract.extract(bank, pages)
        RAW.mkdir(exist_ok=True)
        raw_path.write_text(json.dumps({"model": llm.model(), "at": now(), "extraction": raw}, ensure_ascii=False, indent=1))
    except Exception as e:
        log(f"  ! tolkning misslyckades: {e}")
        if previous:
            previous["checked_at"] = record["checked_at"]
            previous["status"] = f"senaste tolkning misslyckades ({str(e)[:80]})"
            out_path.write_text(json.dumps(previous, ensure_ascii=False, indent=1))
        return previous
    return finish(bank, record, raw, pages, previous, out_path, log, h)


def relink(record: dict, pages: list[fetch.Page]) -> int:
    """Kopplar varje citat till den hämtade sida där det faktiskt står och
    ersätter källistan med `pages`. Returnerar antalet ändrade index."""
    docs = [p.text for p in pages]
    changed = 0
    for prod in record.get("products", []):
        items = list(prod["fields"].values()) + prod.get("rate_tiers", [])
        for f in items:
            q = f.get("quote")
            if not q:
                continue
            idx = next((i for i, d in enumerate(docs) if verify.quote_in(q, d)), None)
            if idx is None:
                continue
            if idx != f.get("source"):
                changed += 1
            f["source"] = idx
    record["sources"] = [{"url": p.url, "title": p.title, "kind": p.kind, "via": p.via, "chars": len(p.text)} for p in pages]
    return changed


def finish(bank, record, raw, pages, previous, out_path, log, h=None):
    """Kontroll (citat, tal, Jev, rimlighet) av en tolkning och sparande."""
    h = h or record.get("source_hash")
    docs = [p.text for p in pages]
    prev_by_name = {p["name"]: p for p in (previous or {}).get("products", [])}
    products = [verify.verify_product(p, docs, prev_by_name.get(p["name"]))
                for p in raw.get("products", []) if verify.in_scope(p)]
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
        "model": llm.model(),
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
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--relink", action="store_true", help="hämta källorna och koppla om citat till rätt sida (inga Claude-anrop)")
    ap.add_argument("--reverify", action="store_true", help="kör om kontrollen mot sparade tolkningar (inga nya Claude-anrop)")
    ap.add_argument("--rediscover", action="store_true", help="leta sidor på nytt i stället för att återanvända förra körningens")
    args = ap.parse_args()
    PRODUCTS.mkdir(parents=True, exist_ok=True)
    banks = [b for b in load_banks() if not args.bank or b["id"] in args.bank]
    print(f"{len(banks)} banker", flush=True)
    failures = 0

    def work(b):
        lines = []
        try:
            process(b, args.discover_only, args.force, lines.append, rediscover=args.rediscover,
                    reverify=args.reverify, relink_only=args.relink)
            ok = True
        except Exception as e:  # en trasig bank ska inte stoppa resten
            lines.append(f"  ! {b['id']}: {type(e).__name__}: {e}")
            ok = False
        finally:
            fetch.close()
        print("\n".join(lines), flush=True)  # en banks logg samlad
        return ok

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(work, banks))
    failures = results.count(False)
    if not args.discover_only:
        build_site_data()
    print(f"\nLLM: {llm.usage}  Jev: {jev.usage}", flush=True)
    sys.exit(1 if failures == len(banks) and banks else 0)


if __name__ == "__main__":
    main()
