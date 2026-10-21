"""Logg över ändrade räntor och avgifter: "SBAB sänkte sparräntan från 2,50 till 2,40 %".

En ändring loggas bara när både det gamla och det nya värdet är belagt med citat och
produkten inte är flaggad – annars skulle tolkningsbrus se ut som ränteändringar.

    python -m collector.changes --backfill   # bygg loggen ur git-historiken för sidfilerna
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "changes.json"
KEEP_DAYS = 400

# Vilka värden som loggas per segment (fält, etikett)
FIELDS = {
    "savings": [("rate_percent", "ränta")],
    "business_savings": [("rate_percent", "ränta")],
    "mortgage": [("rate_percent", "listränta"), ("avg_rate_percent", "snittränta")],
    "personal_loans": [("rate_percent", "lägsta ränta"), ("example_effective_rate_percent", "exemplets effektiva ränta")],
    "cards": [("annual_fee_sek", "årsavgift"), ("currency_fee_percent", "valutapåslag"), ("rate_percent", "ränta")],
    "pension": [("rate_percent", "återbäringsränta")],
    "debit_cards": [("fx_fee_percent", "valutapåslag"), ("monthly_fee_sek", "månadsavgift")],
    "fx_savings": [("rate_percent", "ränta")],
    "broker_fx": [("fx_fee_percent", "valutaväxlingsavgift")],
    "business_transfers": [("fee_fixed_sek", "avgift"), ("fee_percent", "avgift i procent"), ("fx_markup_percent", "växlingspåslag")],
    "transfers": [("fee_fixed_sek", "avgift"), ("fee_percent", "avgift i procent"), ("fx_markup_percent", "växlingspåslag")],
}
SITE_FILES = {"savings": "data/rates.json", "mortgage": "data/mortgage.json", "business_savings": "data/business_savings.json",
              "personal_loans": "data/personal_loans.json", "cards": "data/cards.json", "pension": "data/pension.json",
              "transfers": "data/transfers.json", "broker_fx": "data/broker_fx.json"}

_pending: list[dict] = []
_lock = threading.Lock()


def _ok(p: dict | None, field: str):
    """Värdet om det är belagt och produkten inte är flaggad, annars None."""
    if not p or p.get("status") == "ej verifierad":
        return None
    f = (p.get("fields") or {}).get(field) or {}
    if f.get("status") not in (None, "belagt", "osäkert") or f.get("value") is None:
        return None
    return f["value"]


def _key(p: dict) -> str:
    """Produkter identifieras på namn; bolån även på bindningstid."""
    b = ((p.get("fields") or {}).get("binding_months") or {}).get("value")
    return f"{p['name'].strip().lower()}|{b}"


def detect(segment: str, previous: dict | None, record: dict, date: str | None = None) -> list[dict]:
    if segment not in FIELDS or not previous:
        return []
    prev = {_key(p): p for p in previous.get("products") or []}
    out = []
    for p in record.get("products") or []:
        q = prev.get(_key(p))
        for field, label in FIELDS[segment]:
            old, new = _ok(q, field), _ok(p, field)
            if old is None or new is None or abs(old - new) < 1e-9:
                continue
            out.append({"date": (date or record.get("checked_at") or "")[:10], "segment": segment,
                        "bank_id": record["bank"]["id"], "bank": record["bank"]["name"], "product": p["name"],
                        "field": field, "label": label, "old": old, "new": new})
    return out


def add(entries: list[dict]) -> None:
    with _lock:
        _pending.extend(entries)


def save() -> int:
    """Skriver nya poster till loggen (dubbletter och gamla poster rensas)."""
    with _lock:
        new, _pending[:] = list(_pending), []
    if not new:
        return 0
    log = json.loads(LOG.read_text()) if LOG.exists() else []
    seen = {(e["date"], e["segment"], e["bank_id"], e["product"], e["field"], e["new"]) for e in log}
    added = [e for e in new if (e["date"], e["segment"], e["bank_id"], e["product"], e["field"], e["new"]) not in seen]
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    log = sorted([e for e in log + added if e["date"] >= cutoff], key=lambda e: (e["date"], e["segment"], e["bank"]), reverse=True)
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=0))
    return len(added)


def backfill() -> None:
    """Går igenom varje commit av sidfilerna och loggar ändringar mellan på varandra följande versioner."""
    for seg, path in SITE_FILES.items():
        commits = subprocess.run(["git", "log", "--reverse", "--format=%H %cs", "--", path], cwd=ROOT,
                                 capture_output=True, text=True).stdout.split("\n")
        prev_banks = None
        for line in filter(None, commits):
            sha, date = line.split()
            try:
                data = json.loads(subprocess.run(["git", "show", f"{sha}:{path}"], cwd=ROOT, capture_output=True, text=True).stdout)
            except json.JSONDecodeError:
                continue  # t.ex. en version med sammanslagningskonflikt
            banks = {b["bank"]["id"]: b for b in data.get("banks", [])}
            if prev_banks is not None:
                for bid, rec in banks.items():
                    add(detect(seg, prev_banks.get(bid), rec, date=date))
            prev_banks = banks
        print(f"{seg}: {len(_pending)} ändringar hittills")
    print(f"sparade {save()} nya poster")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true")
    if ap.parse_args().backfill:
        backfill()
