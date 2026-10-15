"""Stoppar en commit om någon datafil är trasig (ogiltig JSON eller kvarlämnade krockmarkeringar).

    python -m collector.check_data
"""
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def main() -> int:
    bad = []
    for f in sorted(DATA.rglob("*.json")):
        text = f.read_text(encoding="utf-8")
        if text.startswith(("<<<<<<<", "=======", ">>>>>>>")) or "\n<<<<<<< " in text or "\n>>>>>>> " in text:
            bad.append(f"{f.relative_to(DATA.parent)}: krockmarkeringar")
            continue
        try:
            json.loads(text)
        except json.JSONDecodeError as e:
            bad.append(f"{f.relative_to(DATA.parent)}: ogiltig JSON ({e})")
    for b in bad:
        print("!", b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
