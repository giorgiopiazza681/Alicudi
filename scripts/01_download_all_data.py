"""Script 01: Download all historical financial data for Italian listed equities.

Downloads:
1. Universe tickers master list
2. Full historical OHLCV data from earliest available date to today
3. Benchmark index (FTSE MIB)
4. Financial statements (Balance Sheet, Income Statement, Cash Flow) and valuation ratios

Usage:
    python scripts/01_download_all_data.py [--limit N] [--skip-financials] [--force]
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.data_downloader import ItalianMarketDownloader
from src.delisted_manager import DelistedMarketManager


def main():
    parser = argparse.ArgumentParser(description="Download financial data for Italian equities.")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of tickers to download (for testing).")
    parser.add_argument("--skip-financials", action="store_true", help="Download only prices and skip balance sheets.")
    parser.add_argument("--force", action="store_true", help="Force re-download of already existing files.")
    parser.add_argument("--pause", type=float, default=0.2, help="Pause seconds between requests.")
    args = parser.parse_args()

    downloader = ItalianMarketDownloader()

    print("=" * 70)
    print("STEP 1: BUILDING MASTER TICKER LIST FOR ITALIAN EQUITIES")
    print("=" * 70)
    master_df = downloader.build_master_ticker_list(force_refresh=args.force)
    all_tickers = master_df["symbol"].tolist()

    if args.limit:
        all_tickers = all_tickers[:args.limit]
        print(f"Limiting download to first {len(all_tickers)} tickers as requested.")

    print(f"Target Universe: {len(all_tickers)} tickers.")
    print("=" * 70)
    print("STEP 2: DOWNLOADING BENCHMARK (FTSE MIB) AND HISTORICAL DATA")
    print("=" * 70)

    stats = downloader.download_all(
        tickers=all_tickers,
        skip_existing=not args.force,
        download_financials=not args.skip_financials,
        use_batch_prices=True,
        pause_sec=args.pause
    )

    print("\n" + "=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)
    print(f"Total Tickers Screened:   {stats['total_tickers']}")
    print(f"Prices Downloaded:        {stats['prices_success']} / {stats['total_tickers']}")
    print(f"Financials Downloaded:    {stats['financials_success']} / {stats['total_tickers']}")
    if stats['failed_tickers']:
        print(f"Failed or Inactive:       {len(stats['failed_tickers'])} tickers: {stats['failed_tickers'][:10]}...")

    print("\n" + "=" * 70)
    print("STEP 3: INTEGRATING DELISTED, BANKRUPT, ACQUIRED & RENAMED COMPANIES")
    print("=" * 70)
    delisted_mgr = DelistedMarketManager()
    delisted_stats = delisted_mgr.run_full_delisted_integration()
    print(f"Official Delistings Registry (1995-2024): {delisted_stats['official_delistings_1995_2024']} companies")
    print(f"Official Admissions Registry (1995-2024): {delisted_stats['official_admissions_1995_2024']} companies")
    print(f"Official Borsa Italiana Panel (2007-2023): {delisted_stats['official_panel_rows_2007_2023']} stock-years")
    print(f"Renamed Tickers Recovered:                {delisted_stats['recovered_renamed_tickers']}")
    print(f"Euronext Delisted/Bankrupt/OPA Recovered: {delisted_stats['recovered_euronext_delisted']}")
    print(f"Pre-2023 Delisted/Bankrupt Recovered:     {delisted_stats['calibrated_pre2023_delisted']}")
    print("Data download and survivorship-bias-free integration completed successfully!")


if __name__ == "__main__":
    main()
