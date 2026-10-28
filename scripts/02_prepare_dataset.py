"""Script 02: Prepare, clean, filter (<500M market cap + liquidity) and build aligned matrices.

Usage:
    python scripts/02_prepare_dataset.py [--cap-max 500] [--min-adtv 20000] [--start-date 2015-01-01]
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import config
from src.universe_manager import UniverseManager


def main():
    parser = argparse.ArgumentParser(description="Prepare dataset and screen Small/Mid Cap universe.")
    parser.add_argument(
        "--cap-max",
        type=float,
        default=500.0,
        help="Max Market Capitalization in Millions of EUR (default: 500M)."
    )
    parser.add_argument(
        "--min-adtv",
        type=float,
        default=20000.0,
        help="Minimum Average Daily Traded Value in EUR (default: 20,000 EUR)."
    )
    parser.add_argument(
        "--min-days",
        type=int,
        default=252,
        help="Minimum required historical trading days (default: 252)."
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="1999-01-01",
        help="Start date for aligned analysis matrix (YYYY-MM-DD, default 1999-01-01 so 1Y lookback starts trading in Jan 2000)."
    )
    args = parser.parse_args()

    cap_threshold = args.cap_max * 1_000_000.0

    print("=" * 70)
    print("STEP 1: SCANNING AND SUMMARIZING DOWNLOADED TICKERS")
    print("=" * 70)
    mgr = UniverseManager(
        cap_threshold_eur=cap_threshold,
        min_trading_days=args.min_days,
        min_adtv_eur=args.min_adtv
    )

    summary = mgr.scan_and_summarize_tickers()
    print(f"Total tickers scanned: {len(summary)}")
    if "status" in summary.columns:
        print("\nBreakdown by Corporate Status (Full Database):")
        print(summary["status"].value_counts().to_string())

    print("\n" + "=" * 70)
    print(f"STEP 2: FILTERING SMALL/MID CAPS (< {args.cap_max:.0f}M EUR) WITH LIQUIDITY CONTROLS")
    print("=" * 70)
    filtered = mgr.filter_small_mid_caps(summary)
    print(f"Tickers eligible for portfolio construction: {len(filtered)}")
    if "status" in filtered.columns:
        print("\nBreakdown by Corporate Status (Eligible Small/Mid Cap Universe):")
        print(filtered["status"].value_counts().to_string())

    print("\nSample of Eligible Small/Mid Caps:")
    print(
        filtered[["ticker", "company_name", "sector", "market_cap_eur", "adtv_eur_1y", "annualized_volatility"]]
        .head(15)
        .to_string(index=False)
    )

    print("\n" + "=" * 70)
    print(f"STEP 3: BUILDING SYNCHRONIZED TIME-SERIES MATRICES (FROM {args.start_date})")
    print("=" * 70)
    prices, returns, vols, bench = mgr.build_aligned_matrices(
        tickers=filtered["ticker"].tolist(),
        start_date=args.start_date
    )
    print(f"Prices matrix shape:   {prices.shape} ({prices.shape[1]} assets x {prices.shape[0]} dates)")
    print(f"Returns matrix shape:  {returns.shape}")
    print(f"Benchmark observations:{len(bench)}")
    print("\nDataset preparation completed successfully!")


if __name__ == "__main__":
    main()
