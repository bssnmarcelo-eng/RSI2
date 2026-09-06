"""Capture a dated PTM fundamental snapshot from a Norgate collection."""
from __future__ import annotations

import argparse
from pathlib import Path

from src.norgate_loader import get_database_symbols, get_watchlist_symbols
from src.ptm_snapshot import collect_snapshot, eligible_universe, save_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", help="Norgate watchlist or database name")
    parser.add_argument("--database", action="store_true", help="Treat collection as a database")
    parser.add_argument("--limit", type=int, help="Optional development-only symbol limit")
    parser.add_argument("--minimum-market-cap", type=float, default=1_000.0, metavar="USD_M")
    parser.add_argument("--output", type=Path, default=Path("logs/ptm_snapshots"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = (
        get_database_symbols(args.collection)
        if args.database
        else get_watchlist_symbols(args.collection)
    )
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1")
        symbols = symbols[: args.limit]
    if not symbols:
        raise RuntimeError(f"No symbols found in Norgate collection: {args.collection}")

    snapshot = collect_snapshot(symbols)
    eligible = eligible_universe(snapshot, args.minimum_market_cap)
    path = save_snapshot(snapshot, args.output)
    print(f"Captured {len(snapshot)} symbols; {len(eligible)} meet the market-cap floor.")
    print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
