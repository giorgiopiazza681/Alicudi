"""Script 02: Prepare, clean, filter (<= €1.0B market cap + liquidity) and build aligned matrices.

Builds:
1. Universe summary and filtered small/mid cap universe (`data/processed/universe_filtered.parquet`)
2. Aligned daily matrices (`prices_matrix.parquet`, `returns_matrix.parquet`, `market_cap_matrix.parquet`, `benchmark_returns.parquet`)
3. Point-in-Time (PIT) fundamental matrices (`data/processed/fundamentals_pit/*.parquet`)

Usage:
    python scripts/02_prepare_dataset.py [--cap-max 1000] [--min-adtv 20000] [--start-date 1999-01-01]
"""

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import config
from src.fundamental_engine import FundamentalEngine
from src.universe_manager import UniverseManager


def main():
    parser = argparse.ArgumentParser(description="Prepare dataset and screen Small/Mid Cap universe.")
    parser.add_argument("--cap-max", type=float, default=config.MARKET_CAP_THRESHOLD_EUR / 1e6, help="Max Market Cap in Millions EUR (default: 1000M = 1.0B EUR).")
    parser.add_argument("--min-adtv", type=float, default=config.MIN_DAILY_TURNOVER_EUR, help="Min Average Daily Traded Value in EUR (default: 20,000).")
    parser.add_argument("--min-days", type=int, default=config.MIN_TRADING_DAYS, help="Min required historical trading days (default: 252).")
    parser.add_argument("--start-date", type=str, default="1999-01-01", help="Start date for aligned matrix (default: 1999-01-01 so 1Y lookback starts in Jan 2000).")
    args = parser.parse_args()

    mgr = UniverseManager(
        cap_threshold_eur=args.cap_max * 1_000_000.0,
        min_trading_days=args.min_days,
        min_adtv_eur=args.min_adtv,
    )

    print("=" * 75)
    print("STEP 1: SCANNING AND FILTERING SMALL/MID CAP UNIVERSE")
    print("=" * 75)
    summary = mgr.scan_and_summarize_tickers()
    filtered = mgr.filter_small_mid_caps(summary)
    print(f"Total tickers scanned: {len(summary)} | Eligible Small/Mid Caps (<= {args.cap_max:.0f}M EUR): {len(filtered)}")
    if "status" in filtered.columns:
        print("\nBreakdown by Corporate Status (Eligible Universe):")
        print(filtered["status"].value_counts().to_string())

    print("\n" + "=" * 75)
    print(f"STEP 2: BUILDING SYNCHRONIZED TIME-SERIES MATRICES (FROM {args.start_date})")
    print("=" * 75)
    prices, returns, _, bench = mgr.build_aligned_matrices(
        tickers=filtered["ticker"].tolist(),
        start_date=args.start_date,
    )
    print(f"Prices matrix: {prices.shape[1]} stocks x {prices.shape[0]} trading days | Benchmark obs: {len(bench)}")

    print("\n" + "=" * 75)
    print("STEP 3: BUILDING POINT-IN-TIME FUNDAMENTAL MATRICES (90-DAY LAG)")
    print("=" * 75)
    pit_data = FundamentalEngine().build_pit_fundamental_matrices(prices, returns, reporting_lag_days=90)
    print(f"PIT Fundamental matrices saved for {pit_data['pe'].shape[1]} stocks.")
    print("Dataset preparation completed successfully!")


if __name__ == "__main__":
    main()
