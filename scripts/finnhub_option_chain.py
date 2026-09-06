"""Download daily option-chain snapshots from Finnhub.

This script fetches the option chain for a given equity symbol on one or more
calendar dates and saves the result to a CSV file.

Requirements:
- FINNHUB_API_KEY must be set in the environment.
- requests and pandas are used; both are already dependencies for this repo.

Example:
    python scripts/finnhub_option_chain.py AAPL \
        --start 2025-01-01 --end 2025-01-31 \
        --output data/AAPL-options.csv

The output contains one row per contract per date. It is a daily snapshot of
Finnhub's option-chain data for the requested dates.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import pandas as pd
import requests

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
DEFAULT_SLEEP_SECONDS = 0.4


def load_api_key() -> str:
    key = os.environ.get("FINNHUB_API_KEY")
    if not key:
        raise RuntimeError(
            "Missing Finnhub API key. Set FINNHUB_API_KEY in your environment."
        )
    return key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download daily option-chain snapshots from Finnhub."
    )
    parser.add_argument("symbol", help="Equity ticker symbol, e.g. AAPL")
    parser.add_argument(
        "--start",
        required=True,
        help="Start date (inclusive) in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End date (inclusive) in YYYY-MM-DD format",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output CSV file path",
    )
    parser.add_argument(
        "--contract-types",
        choices=["call", "put", "all"],
        default="all",
        help="Contract types to keep in the output",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Seconds to wait between API requests (default: 0.4).",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=2,
        help="Number of retries per date when the API returns a transient failure.",
    )
    return parser.parse_args()


def build_dates(start: str, end: str) -> list[datetime]:
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    if start_dt > end_dt:
        raise ValueError("start date must be on or before end date")
    dates = pd.date_range(start=start_dt, end=end_dt, freq="D").to_pydatetime().tolist()
    return dates


def fetch_option_chain(symbol: str, query_date: datetime, api_key: str) -> dict:
    url = f"{FINNHUB_BASE_URL}/stock/option-chain"
    params = {
        "symbol": symbol,
        "date": query_date.strftime("%Y-%m-%d"),
        "token": api_key,
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def normalize_option_chain(symbol: str, query_date: datetime, payload: dict) -> pd.DataFrame:
    records = []
    data = payload.get("data") or []
    if not data:
        return pd.DataFrame(columns=[
            "symbol",
            "snapshot_date",
            "option_symbol",
            "contract_type",
            "expiration_date",
            "strike",
            "bid",
            "ask",
            "last_price",
            "open_interest",
            "volume",
            "implied_volatility",
            "underlying_price",
        ])

    for item in data:
        records.append({
            "symbol": symbol,
            "snapshot_date": query_date.date(),
            "option_symbol": item.get("symbol") or item.get("code") or "",
            "contract_type": item.get("type", "").lower(),
            "expiration_date": pd.to_datetime(item.get("expirationDate", item.get("expiration_date")), errors="coerce").date() if item.get("expirationDate") or item.get("expiration_date") else None,
            "strike": item.get("strike"),
            "bid": item.get("bid"),
            "ask": item.get("ask"),
            "last_price": item.get("last"),
            "open_interest": item.get("openInterest", item.get("open_interest")),
            "volume": item.get("volume"),
            "implied_volatility": item.get("impliedVolatility", item.get("implied_volatility")),
            "underlying_price": item.get("underlyingPrice", item.get("underlying_price")),
        })

    return pd.DataFrame.from_records(records)


def main() -> int:
    args = parse_args()
    api_key = load_api_key()
    dates = build_dates(args.start, args.end)
    frames = []

    for query_date in dates:
        if query_date.weekday() >= 5:
            continue

        for attempt in range(1, args.retry + 1):
            try:
                payload = fetch_option_chain(args.symbol, query_date, api_key)
                frame = normalize_option_chain(args.symbol, query_date, payload)
                frames.append(frame)
                break
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in {429, 500, 502, 503, 504} and attempt < args.retry:
                    wait = args.sleep * attempt
                    print(
                        f"Warning: transient error for {query_date.date()} (status={status}), retrying in {wait:.1f}s...",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
                raise
            except requests.RequestException as exc:
                if attempt < args.retry:
                    wait = args.sleep * attempt
                    print(
                        f"Warning: request failed for {query_date.date()}: {exc}. Retrying in {wait:.1f}s...",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
                raise
        time.sleep(args.sleep)

    if not frames:
        print("No option-chain records were downloaded.", file=sys.stderr)
        return 1

    result = pd.concat(frames, ignore_index=True)
    if args.contract_types != "all":
        result = result[result["contract_type"] == args.contract_types]

    result = result.sort_values(["snapshot_date", "option_symbol"])
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    result.to_csv(args.output, index=False)
    print(f"Saved {len(result)} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
