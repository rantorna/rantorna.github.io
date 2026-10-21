"""Hälsokontroll av sajtens data – larmar när något har stannat eller rasat.

    python -m collector.health            # skriver rapporten, exit 1 om något är fel

Kontrollerar att varje datafil är färsk, att ingen flik plötsligt tappat många banker
jämfört med för en vecka sedan (ur git-historiken), och att nattjobbet inte misslyckats
flera gånger i rad. Arbetsflödet health.yml gör om rapporten till ett GitHub-ärende.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOW = dt.datetime.now(dt.timezone.utc)

# Datafil, flikens namn, högsta ålder i timmar. Nattjobbet går varje natt; ränteläget bara vardagar.
FILES = [
    ("data/rates.json", "Sparkonton", 30), ("data/youth.json", "Barn & unga", 30),
    ("data/fx_savings.json", "Sparkonton i utländsk valuta", 30), ("data/mortgage.json", "Bolån", 30),
    ("data/personal_loans.json", "Privatlån", 30), ("data/cards.json", "Kreditkort", 30),
    ("data/business_accounts.json", "Företagskonton", 30), ("data/business_savings.json", "Företagssparande", 30),
    ("data/business_financing.json", "Företagsfinansiering", 30), ("data/business_transfers.json", "Företagens utlandsbetalningar", 30),
    ("data/pension.json", "Pension", 30), ("data/transfers.json", "Utlandsbetalningar", 30),
    ("data/broker_fx.json", "Utländska aktier", 30), ("data/debit_cards.json", "Bankkort utomlands", 30),
    ("data/macro.json", "Ränteläget", 100), ("data/fx.json", "Valutakurser", 100),
]
DROP_SHARE = 0.2      # larma om en flik tappat mer än 20 % av bankerna med uppgifter …
DROP_MIN = 3          # … och minst 3 banker
COMPARE_DAYS = 7


def age_hours(stamp: str | None) -> float | None:
    if not stamp:
        return None
    return (NOW - dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() / 3600


def with_data(d: dict) -> int:
    """Antal banker med minst en produkt som inte är flaggad."""
    return sum(1 for b in d.get("banks") or [] if any(p.get("status") != "ej verifierad" for p in b.get("products") or []))


def old_version(path: str) -> dict | None:
    """Filen som den såg ut för en vecka sedan (senaste commit före dess)."""
    until = (NOW - dt.timedelta(days=COMPARE_DAYS)).isoformat()
    sha = subprocess.run(["git", "log", "-1", f"--until={until}", "--format=%H", "--", path], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    if not sha:
        return None
    try:
        return json.loads(subprocess.run(["git", "show", f"{sha}:{path}"], cwd=ROOT, capture_output=True, text=True).stdout)
    except json.JSONDecodeError:
        return None


def failed_runs() -> str | None:
    """Har de två senaste avslutade nattkörningarna misslyckats? (kräver gh och GH_TOKEN)"""
    if not os.environ.get("GH_TOKEN"):
        return None
    out = subprocess.run(["gh", "run", "list", "-w", "collect.yml", "-L", "10", "--json", "conclusion,createdAt,url"],
                         cwd=ROOT, capture_output=True, text=True)
    if out.returncode:
        return None
    done = [r for r in json.loads(out.stdout) if r["conclusion"] not in ("", "skipped", "cancelled")]
    if len(done) >= 2 and all(r["conclusion"] != "success" for r in done[:2]):
        return f"De två senaste nattkörningarna misslyckades ({done[0]['createdAt'][:10]}, {done[1]['createdAt'][:10]}): {done[0]['url']}"
    return None


def main() -> int:
    problems = []
    for path, label, max_age in FILES:
        f = ROOT / path
        if not f.exists():
            problems.append(f"**{label}**: `{path}` saknas.")
            continue
        d = json.loads(f.read_text())
        h = age_hours(d.get("generated_at"))
        if h is None or h > max_age:
            problems.append(f"**{label}**: uppgifterna är {'okänt' if h is None else f'{h / 24:.1f} dygn'} gamla (`{path}`).")
        if "banks" in d:
            now_n, old = with_data(d), old_version(path)
            old_n = with_data(old) if old else None
            if old_n and old_n - now_n >= DROP_MIN and (old_n - now_n) / old_n > DROP_SHARE:
                problems.append(f"**{label}**: {now_n} banker med uppgifter i dag mot {old_n} för en vecka sedan.")
    cash = ROOT / "data/cash.json"
    if cash.exists():
        for o in json.loads(cash.read_text()).get("offices", []):
            h = age_hours(o.get("fetched_at"))
            if h is None or h > 24 * 7:
                problems.append(f"**Kontantkurser**: {o['name']} har inte gått att läsa på över en vecka.")
    if msg := failed_runs():
        problems.append(f"**Nattjobbet**: {msg}")

    report = ROOT / "health.md"
    if problems:
        report.write_text("Hälsokontrollen hittade problem:\n\n" + "\n".join(f"- {p}" for p in problems)
                          + f"\n\nKontrollerat {NOW:%Y-%m-%d %H:%M} UTC. Ärendet stängs automatiskt när allt är i ordning igen.\n")
    else:
        report.write_text(f"Allt i ordning {NOW:%Y-%m-%d %H:%M} UTC.\n")
    print(report.read_text())
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
