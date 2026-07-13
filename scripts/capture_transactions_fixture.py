#!/usr/bin/env python3
"""Capture a sanitized ``mTransactions2`` sample for the transaction adapter.

Read-only. Makes ESPN GET requests only; writes one local JSON fixture. Requires
ESPN credentials in the environment (your ``.env``: ``ESPN_LEAGUE_ID``,
``ESPN_SEASON``, ``ESPN_SWID``, ``ESPN_S2``).

What it answers
---------------
1. Whether one ``mTransactions2`` request with a matchup-week number returns that
   whole week's transactions, or just a single daily scoring period. The summary
   prints the distinct ``scoringPeriodId`` values and the process-date spread in
   the response, which settles the question.
2. The exact JSON shape (transaction + item keys), so trade-chain reconstruction
   can be finalized against ground truth.

Usage
-----
    # From the repo root, with your .env present:
    python scripts/capture_transactions_fixture.py --scoring-period 21

    # Not sure which period? Probe a range and see where transactions land:
    python scripts/capture_transactions_fixture.py --scoring-period 21 --probe 18 24

Output
------
- Prints a summary to the terminal (safe to paste back — it contains no
  credentials, member GUIDs, or free text).
- Writes ``tests/fixtures/mtransactions2_sample.json`` (sanitized): member GUIDs
  and any free-text/message fields are redacted; numeric player/team ids and the
  structural fields the adapter needs are kept.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

# Allow running as `python scripts/capture_transactions_fixture.py` from the repo
# root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is optional if the vars are already exported
    pass

from backend.league import data_feed as feed  # noqa: E402

# The full useful transaction vocabulary (see espn_api basketball constant.py).
USEFUL_TYPES = [
    "FREEAGENT", "WAIVER", "WAIVER_ERROR",
    "TRADE_ACCEPT", "TRADE_UPHOLD", "TRADE_PROPOSAL", "TRADE_DECLINE", "TRADE_VETO",
    "DRAFT", "FUTURE_ROSTER", "ROSTER",
]

# Keys that identify a real person or carry free text. Values are replaced with
# "REDACTED"; structure is preserved so the fixture stays useful.
SENSITIVE_KEYS = {"memberId", "author", "messages", "message", "note", "notes"}


def _fetch(h, scoring_period: int) -> list[dict]:
    params = {"view": "mTransactions2", "scoringPeriodId": int(scoring_period)}
    filters = {"transactions": {"filterType": {"value": USEFUL_TYPES}}}
    headers = {"x-fantasy-filter": json.dumps(filters)}
    data = h.league.espn_request.league_get(params=params, headers=headers)
    return (data or {}).get("transactions") or []


def _epoch_ms_to_date(value) -> str | None:
    if not value:
        return None
    try:
        import pandas as pd

        seconds = int(value)
        if seconds > 10**10:
            seconds /= 1000.0
        return pd.to_datetime(seconds, unit="s", utc=True).date().isoformat()
    except Exception:
        return str(value)


def _summarize(label: str, txns: list[dict]) -> None:
    print(f"\n=== {label}: {len(txns)} transactions ===")
    if not txns:
        return
    sp = collections.Counter(t.get("scoringPeriodId") for t in txns)
    types = collections.Counter(t.get("type") for t in txns)
    statuses = collections.Counter(t.get("status") for t in txns)
    dates = sorted(d for d in (_epoch_ms_to_date(t.get("processDate")) for t in txns) if d)
    print("  scoringPeriodId values:", dict(sp))
    print("  process-date range:", (dates[0], dates[-1]) if dates else None)
    print("  types:", dict(types))
    print("  statuses:", dict(statuses))
    print("  transaction keys:", sorted(txns[0].keys()))
    items = txns[0].get("items") or []
    if items:
        print("  item keys:", sorted(items[0].keys()))
    # Show one executed add/drop and one trade skeleton (ids only, no names).
    for t in txns:
        if t.get("type") in {"TRADE_ACCEPT", "TRADE_UPHOLD"}:
            print("  sample trade item keys:", sorted((t.get("items") or [{}])[0].keys()))
            break


def _sanitize(obj):
    if isinstance(obj, dict):
        return {
            k: ("REDACTED" if k in SENSITIVE_KEYS else _sanitize(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_sanitize(x) for x in obj]
    return obj


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scoring-period", type=int, required=True,
                    help="Scoring period / matchup week to capture (e.g. a completed week like 21).")
    ap.add_argument("--probe", type=int, nargs=2, metavar=("LOW", "HIGH"), default=None,
                    help="Optional: also fetch each period in [LOW, HIGH] and report counts, "
                         "to learn how scoringPeriodId maps to weeks.")
    ap.add_argument("--max-fixture", type=int, default=80,
                    help="Cap transactions written to the fixture (default 80).")
    args = ap.parse_args()

    print("Connecting to ESPN (read-only)...")
    h = feed.connect()

    txns = _fetch(h, args.scoring_period)
    _summarize(f"scoringPeriodId={args.scoring_period}", txns)

    if args.probe:
        low, high = args.probe
        print("\n--- probe: transactions returned per scoringPeriodId ---")
        for sp in range(low, high + 1):
            try:
                n = len(_fetch(h, sp))
            except Exception as exc:  # noqa: BLE001 - report and continue
                n = f"error: {type(exc).__name__}"
            print(f"  scoringPeriodId={sp}: {n}")

    out = Path("tests/fixtures/mtransactions2_sample.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    sample = {"transactions": [_sanitize(t) for t in txns[: args.max_fixture]]}
    out.write_text(json.dumps(sample, indent=2))
    print(f"\nWrote {out} ({len(sample['transactions'])} sanitized transactions).")
    print("Please eyeball the file for anything you don't want committed, then:")
    print("  git add tests/fixtures/mtransactions2_sample.json && git commit")


if __name__ == "__main__":
    main()
