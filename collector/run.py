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

from . import changes, discover, extract, fetch, jev, llm, segments, verify

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAX_TOTAL_CHARS = 250_000

RATE_URL = re.compile(r"rant|r%c3%a4nt|ränt", re.I)  # räntesidor: hämta även via webbläsaren
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
    """Banker från uppslagen i FI-registret, plus/överstyrda av segmentets manuella lista."""
    from .resolve import banks_from_institutions, site_key

    mb = segments.cur().manual_banks
    manual = (yaml.safe_load(mb.read_text()) or []) if mb and mb.exists() else []
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
        starts = set(bank.get("start_urls", []))
        for u in prev_urls:
            p = fetch.get(u, rich=u in starts or bool(RATE_URL.search(u))) if not u.lower().endswith(".pdf") else fetch.get(u, allow_browser=False)
            if p.error or len(p.text) < 200:
                log(f"  - {u}: {p.error or 'för lite text'} – letar nya sidor")
                return collect_pages(bank, log, previous, rediscover=True)
            pages.append(p)
        log(f"  {len(pages)} kända sidor")
        return pages
    found = discover.candidates(bank, log=log)
    urls = discover.choose(bank, found, log=log)
    pages = []
    starts = set(bank.get("start_urls", []))
    for u in urls:
        p = fetch.get(u, rich=u in starts or bool(RATE_URL.search(u)))
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
    out_path = segments.cur().products / f"{bank['id']}.json"
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
    if previous and not force and not reverify and quotes_still_there(previous, pages):
        # Sidan har ändrats, men varje belagt citat står kvar – det som ändrats är inte
        # räntor eller villkor (nyheter, datum, kakbanner). Ingen ny tolkning behövs.
        log("  citaten står kvar – ingen ny tolkning")
        previous |= {"checked_at": record["checked_at"], "discovered_at": record["discovered_at"], "source_hash": h}
        relink(previous, pages)
        out_path.write_text(json.dumps(previous, ensure_ascii=False, indent=1))
        return previous
    if not llm.available():
        log("  ! ingen LLM – hoppar över tolkning")
        return None
    raw_path = segments.cur().raw / f"{bank['id']}.json"
    if reverify:
        if not raw_path.exists():
            log("  ingen sparad tolkning – hoppar över")
            return previous
        raw = json.loads(raw_path.read_text())["extraction"]
        record["source_hash"] = h
        return finish(bank, record, raw, pages, previous, out_path, log)
    try:
        raw = extract.extract(bank, pages)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(json.dumps({"model": llm.model(), "at": now(), "extraction": raw}, ensure_ascii=False, indent=1))
    except Exception as e:
        log(f"  ! tolkning misslyckades: {e}")
        if previous:
            previous["checked_at"] = record["checked_at"]
            previous["status"] = f"senaste tolkning misslyckades ({str(e)[:80]})"
            out_path.write_text(json.dumps(previous, ensure_ascii=False, indent=1))
        return previous
    return finish(bank, record, raw, pages, previous, out_path, log, h)


FULL_EXTRACT_DAYS = 7


def quotes_still_there(previous: dict, pages: list[fetch.Page]) -> bool:
    """Sant om förra tolkningen har belagda värden och alla deras citat finns kvar i sidorna,
    och den inte är äldre än en vecka (då tolkas allt om, så att nya produkter kommer med)."""
    changed = previous.get("changed_at")
    if not changed or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(changed)).days >= FULL_EXTRACT_DAYS:
        return False
    docs = [p.text for p in pages]
    quotes = [f["quote"] for prod in previous.get("products", []) for f in prod["fields"].values()
              if f.get("value") is not None and f.get("quote")]
    return bool(quotes) and all(any(verify.quote_in(q, d) for d in docs) for q in quotes)


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
                jev.check_product(p, docs, bank["name"], prev_by_name.get(p["name"]))
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
        rate = f.get('rate_percent', {}).get('value')
        log(f"  * {p['name']}: {'' if rate is None else str(rate) + ' %'} [{p['status']}] "
            + ", ".join(f"{k}:{v['status']}" for k, v in f.items() if v["status"] not in ("belagt", "okänt")))
    changes.add(changes.detect(segments.cur().key, previous, record))
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    return record


def safe_url(u: str | None) -> str | None:
    """Bara http(s)-adresser, och utan tecken som kan bryta ut ur ett HTML-attribut.
    Adresserna kommer från främmande webbsidor och skrivs in i länkar på sajten."""
    if not u or not re.match(r"^https?://", u, re.I):
        return None
    return re.sub(r"[\"'<>`\s]", lambda m: "%%%02X" % ord(m.group()), u)


def slim(bank: dict) -> None:
    """Sidan behöver värde, citat, källa och status – inte Jev-svar, nollade påståenden
    eller källornas metadata. Halverar ungefär filerna som webbläsaren laddar."""
    bank["sources"] = [{"url": safe_url(s["url"]) or "#"} for s in bank.get("sources") or []]
    if bank.get("bank"):
        bank["bank"] = dict(bank["bank"], homepage=safe_url(bank["bank"].get("homepage")) or "#")
    for p in bank.get("products") or []:
        p.pop("pending_rate", None)
        for f in p["fields"].values():
            f.pop("jev", None)
            f.pop("claimed", None)
            if f.get("value") is None:  # okänt: citatet visas ändå inte
                f.pop("quote", None)
                f.pop("source", None)


def savings_context() -> dict:
    """Inflation och ISK-regler från ränteläget, så att sparkontosidan kan visa
    räntan efter skatt och inflation utan att ladda hela macro.json."""
    path = DATA / "macro.json"
    if not path.exists():
        return {}
    series = json.loads(path.read_text()).get("series", {})
    latest = lambda sid: (series.get(sid) or {}).get("latest") or {}
    return {
        "kpif": latest("se_kpif").get("value"), "kpif_month": latest("se_kpif").get("date"),
        "isk_year": (latest("se_isk_schablon").get("date") or "")[:4] or None,
        "isk_schablon": latest("se_isk_schablon").get("value"), "isk_skatt": latest("se_isk_skatt").get("value"),
        "isk_grund": latest("se_isk_grund").get("value"),
        # SCB: vad hushåll och företag i snitt får på pengarna i banken – riktmärke för sparkontona
        "dep_month": latest("se_dep_hh_all").get("date"),
        "dep_hh_all": latest("se_dep_hh_all").get("value"), "dep_hh_free": latest("se_dep_hh_free").get("value"),
        "dep_hh_fixed": latest("se_dep_hh_fixed").get("value"), "dep_corp_all": latest("se_dep_corp_all").get("value"),
    }


def financing_context(ids=("se_corp_new_all", "se_corp_new_var", "se_corp_new_1y5y", "se_corp_kontokredit",
                            "se_soletrader_new_all", "se_policy")) -> dict:
    """SCB:s räntor (t.ex. på nya företagslån) som riktmärke på sidan."""
    path = DATA / "macro.json"
    if not path.exists():
        return {}
    series = json.loads(path.read_text()).get("series", {})
    return {sid: {"name": series[sid]["name"], **{k: series[sid]["latest"].get(k) for k in ("value", "date", "chg_1y")}}
            for sid in ids if sid in series}


def build_site_data():
    """Slår ihop segmentets banker till filen som sidan läser (t.ex. data/rates.json)."""
    banks = []
    seg = segments.cur()
    for f in sorted(seg.products.glob("*.json")):
        r = json.loads(f.read_text())
        banks.append({k: r.get(k) for k in ("bank", "checked_at", "changed_at", "status", "sources", "products")})
        slim(banks[-1])
    out = {"generated_at": now(), "banks": banks}
    if seg.key in ("savings", "business_savings", "youth"):
        out["context"] = savings_context()
    elif seg.key == "business_financing":
        out["context"] = financing_context()
    elif seg.key == "personal_loans":
        out["context"] = financing_context(("se_consumer_new", "se_consumer_stock", "se_policy", "se_ref"))
    seg.site_file.write_text(json.dumps(out, ensure_ascii=False))


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
    ap.add_argument("--segment", default="savings", help=f"ett av: {', '.join(segments.SEGMENTS)}")
    ap.add_argument("--relink", action="store_true", help="hämta källorna och koppla om citat till rätt sida (inga Claude-anrop)")
    ap.add_argument("--reverify", action="store_true", help="kör om kontrollen mot sparade tolkningar (inga nya Claude-anrop)")
    ap.add_argument("--rediscover", action="store_true", help="leta sidor på nytt i stället för att återanvända förra körningens")
    args = ap.parse_args()
    segments.use(args.segment)
    segments.cur().products.mkdir(parents=True, exist_ok=True)
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
        if not args.bank:  # en delkörning ska inte logga halva marknaden
            print(f"{changes.save()} ränteändringar loggade", flush=True)
    print(f"\nLLM: {llm.usage}  Jev: {jev.usage}", flush=True)
    sys.exit(1 if failures == len(banks) and banks else 0)


if __name__ == "__main__":
    main()
