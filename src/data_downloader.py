"""Data downloader for Italian equities (Euronext Milan and Euronext Growth Milan).

Downloads historical prices, volumes, benchmark, and fundamental financial statements.
Supports resume/incremental caching, rate limiting, and structured Parquet storage.
"""

import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import financedatabase as fd
import pandas as pd
from tqdm import tqdm
import yfinance as yf

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


class ItalianMarketDownloader:
    """Manages downloading, updating, and caching Italian stock data."""

    def __init__(self):
        self.raw_dir = config.RAW_DIR
        self.prices_dir = config.PRICES_DIR
        self.financials_dir = config.FINANCIALS_DIR
        self.info_dir = config.INFO_DIR
        self.benchmark_dir = config.BENCHMARK_DIR

        # Ensure directories exist
        for d in [self.prices_dir, self.financials_dir, self.info_dir, self.benchmark_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def build_master_ticker_list(self, force_refresh: bool = False) -> pd.DataFrame:
        """Retrieves and consolidates all Italian listed equities from financedatabase

        and adds relevant Italian large-cap foreign-registered components.
        """
        master_file_parquet = self.raw_dir / "tickers_master.parquet"
        master_file_csv = self.raw_dir / "tickers_master.csv"

        if not force_refresh and master_file_parquet.exists():
            logger.info(f"Loading existing master ticker list from {master_file_parquet}")
            return pd.read_parquet(master_file_parquet)

        logger.info("Querying FinanceDatabase for Italian equities...")
        equities = fd.Equities()

        # Primary Italian equities
        it_df = equities.select(country="Italy")
        it_mi = it_df[it_df.index.str.endswith(".MI")].copy()

        # Also include prominent Italian multinationals that have Dutch/foreign legal seats
        # but are primary components of Italian indices (e.g. STMMI, RACE, CPR, STLAM, PRY, TEN, IVG)
        all_df = equities.select()
        all_mi = all_df[all_df.index.str.endswith(".MI")].copy()

        prominent_foreign_seat = [
            "STMMI.MI", "RACE.MI", "CPR.MI", "STLAM.MI", "PRY.MI", "TEN.MI", "IVG.MI"
        ]
        extra_df = all_mi.loc[all_mi.index.intersection(prominent_foreign_seat)].copy()

        combined = pd.concat([it_mi, extra_df])
        combined = combined[~combined.index.duplicated(keep="first")]

        # Reset index to have 'symbol' as a column
        master = combined.reset_index().rename(columns={"index": "symbol"})
        master = master.sort_values(by="symbol").reset_index(drop=True)

        logger.info(f"Consolidated master universe: {len(master)} Italian .MI tickers.")

        # Save to parquet and csv
        master.to_parquet(master_file_parquet, index=False)
        master.to_csv(master_file_csv, index=False)
        logger.info(f"Saved master tickers to {master_file_parquet} and {master_file_csv}")
        return master

    def download_benchmark(self, ticker: str = config.BENCHMARK_TICKER, force: bool = False) -> Optional[pd.DataFrame]:
        """Downloads full historical data for the benchmark index (FTSE MIB)."""
        benchmark_file = self.benchmark_dir / f"{ticker.replace('^', '').replace('.', '_').lower()}.parquet"
        if not force and benchmark_file.exists():
            logger.info(f"Benchmark {ticker} already downloaded at {benchmark_file}")
            return pd.read_parquet(benchmark_file)

        logger.info(f"Downloading benchmark index {ticker}...")
        try:
            bench = yf.Ticker(ticker)
            df = bench.history(period="max", auto_adjust=False)
            if df.empty:
                logger.warning(f"Benchmark {ticker} returned no data.")
                return None

            df.to_parquet(benchmark_file)
            logger.info(
                f"Benchmark {ticker} downloaded successfully: {len(df)} bars "
                f"from {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}"
            )
            return df
        except Exception as e:
            logger.error(f"Failed downloading benchmark {ticker}: {e}")
            return None

    def download_prices_for_ticker(self, ticker: str, force: bool = False) -> Tuple[bool, int]:
        """Downloads full historical OHLCV data for a single ticker.

        Returns (success_flag, number_of_rows).
        """
        dest_file = self.prices_dir / f"{ticker}.parquet"
        if not force and dest_file.exists():
            try:
                existing = pd.read_parquet(dest_file)
                return True, len(existing)
            except Exception:
                pass  # Re-download if corrupted

        try:
            tk = yf.Ticker(ticker)
            # Fetch with auto_adjust=False to keep both Close and Adj Close
            hist = tk.history(period="max", auto_adjust=False)
            if hist.empty or len(hist) < 5:
                return False, 0

            # Ensure timezone-naive dates or uniform formatting
            hist.to_parquet(dest_file)
            return True, len(hist)
        except Exception as e:
            logger.debug(f"Error fetching prices for {ticker}: {e}")
            return False, 0

    def download_financials_for_ticker(self, ticker: str, force: bool = False) -> bool:
        """Downloads income statements, balance sheets, cash flows, and key valuation metrics."""
        dest_fin = self.financials_dir / f"{ticker}_financials.parquet"
        dest_info = self.info_dir / f"{ticker}_info.json"

        if not force and dest_fin.exists() and dest_info.exists():
            return True

        try:
            tk = yf.Ticker(ticker)
            
            # 1. Fetch info and valuation metrics
            info_dict = {}
            try:
                raw_info = tk.info or {}
                # Extract key fields
                keys_to_extract = [
                    "symbol", "shortName", "longName", "currency", "sector", "industry",
                    "marketCap", "enterpriseValue", "trailingPE", "forwardPE",
                    "priceToBook", "enterpriseToEbitda", "profitMargins", "operatingMargins",
                    "returnOnEquity", "returnOnAssets", "debtToEquity", "totalDebt",
                    "totalRevenue", "freeCashflow", "dividendYield", "trailingAnnualDividendYield",
                    "fiftyTwoWeekLow", "fiftyTwoWeekHigh", "sharesOutstanding", "floatShares"
                ]
                info_dict = {k: raw_info.get(k) for k in keys_to_extract if k in raw_info}
            except Exception:
                pass

            # Fast info fallback for marketCap and currency
            try:
                fast = tk.fast_info
                if "marketCap" not in info_dict or not info_dict["marketCap"]:
                    info_dict["marketCap"] = getattr(fast, "market_cap", None)
                if "currency" not in info_dict or not info_dict["currency"]:
                    info_dict["currency"] = getattr(fast, "currency", None)
            except Exception:
                pass

            with open(dest_info, "w", encoding="utf-8") as f:
                json.dump(info_dict, f, indent=2, default=str)

            # 2. Financial statements
            records = []
            
            # Helper to process statement dataframe
            def process_statement(df: Optional[pd.DataFrame], stmt_type: str, freq: str):
                if df is None or df.empty:
                    return
                # Convert timestamps to string columns
                df_copy = df.copy()
                for col in df_copy.columns:
                    col_str = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                    for item, val in df_copy[col].items():
                        records.append({
                            "statement": stmt_type,
                            "frequency": freq,
                            "date": col_str,
                            "line_item": str(item),
                            "value": float(val) if pd.notnull(val) else None
                        })

            try:
                process_statement(tk.financials, "income_statement", "annual")
                process_statement(tk.quarterly_financials, "income_statement", "quarterly")
                process_statement(tk.balance_sheet, "balance_sheet", "annual")
                process_statement(tk.quarterly_balance_sheet, "balance_sheet", "quarterly")
                process_statement(tk.cashflow, "cash_flow", "annual")
                process_statement(tk.quarterly_cashflow, "cash_flow", "quarterly")
            except Exception:
                pass

            if records:
                fin_df = pd.DataFrame(records)
                fin_df.to_parquet(dest_fin, index=False)

            return True
        except Exception as e:
            logger.debug(f"Error fetching financials for {ticker}: {e}")
            return False

    def download_all_info_multithreaded(self, tickers: List[str], max_workers: int = 8) -> int:
        """Fetches market cap, valuation ratios, sector, and company info concurrently."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        logger.info(f"Downloading fundamental info for {len(tickers)} tickers with {max_workers} threads...")
        success = 0

        def fetch_single(tk: str):
            info_file = self.info_dir / f"{tk}_info.json"
            try:
                t = yf.Ticker(tk)
                fast = t.fast_info
                # Base info from fast_info
                data = {
                    "symbol": tk,
                    "marketCap": getattr(fast, "market_cap", None),
                    "currency": getattr(fast, "currency", None),
                    "lastPrice": getattr(fast, "last_price", None),
                    "fiftyTwoWeekLow": getattr(fast, "year_low", None),
                    "fiftyTwoWeekHigh": getattr(fast, "year_high", None),
                    "sharesOutstanding": getattr(fast, "shares", None),
                }

                # Try pulling detailed info for sector, P/E, ratios
                try:
                    raw_info = t.info or {}
                    keys_to_extract = [
                        "shortName", "longName", "sector", "industry",
                        "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
                        "profitMargins", "operatingMargins", "returnOnEquity",
                        "debtToEquity", "totalDebt", "dividendYield"
                    ]
                    for k in keys_to_extract:
                        if k in raw_info and raw_info[k] is not None:
                            data[k] = raw_info[k]
                except Exception:
                    pass

                with open(info_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)
                return True
            except Exception as e:
                logger.debug(f"Failed info for {tk}: {e}")
                return False

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_single, tk): tk for tk in tickers}
            for fut in tqdm(as_completed(futures), total=len(futures), desc="Fetching Metadata & Fundamentals"):
                if fut.result():
                    success += 1

        logger.info(f"Fundamental info fetched: {success}/{len(tickers)} tickers.")
        return success

    def download_all_prices_batch(
        self,
        tickers: List[str],
        batch_size: int = 50,
        force: bool = False
    ) -> Tuple[int, int, List[str]]:
        """Downloads full price history in fast multithreaded batches.

        Returns (success_count, total_bars, failed_tickers).
        """
        logger.info(f"Downloading historical prices for {len(tickers)} tickers using multithreaded batches...")
        to_download = []
        already_cached = 0
        total_bars = 0

        for tk in tickers:
            p_file = self.prices_dir / f"{tk}.parquet"
            if not force and p_file.exists():
                already_cached += 1
            else:
                to_download.append(tk)

        logger.info(f"{already_cached} tickers already cached, {len(to_download)} to fetch.")

        success_count = already_cached
        failed = []

        # Process in batches
        for i in range(0, len(to_download), batch_size):
            chunk = to_download[i : i + batch_size]
            logger.info(f"Fetching batch {i//batch_size + 1}/{(len(to_download)-1)//batch_size + 1} ({len(chunk)} tickers)...")
            try:
                data = yf.download(
                    chunk,
                    period="max",
                    group_by="ticker",
                    threads=True,
                    progress=False,
                    auto_adjust=False
                )
                if data.empty:
                    failed.extend(chunk)
                    continue

                for tk in chunk:
                    p_file = self.prices_dir / f"{tk}.parquet"
                    try:
                        if len(chunk) == 1:
                            sub_df = data.copy()
                        else:
                            if tk in data.columns.levels[0]:
                                sub_df = data[tk].dropna(how="all")
                            else:
                                sub_df = pd.DataFrame()

                        # Ensure valid rows
                        if not sub_df.empty and len(sub_df) >= 5:
                            sub_df.to_parquet(p_file)
                            success_count += 1
                            total_bars += len(sub_df)
                        else:
                            failed.append(tk)
                    except Exception as e:
                        logger.debug(f"Error saving batch ticker {tk}: {e}")
                        failed.append(tk)
            except Exception as e:
                logger.error(f"Batch failed: {e}")
                failed.extend(chunk)

            time.sleep(0.5)

        return success_count, total_bars, failed

    def download_all(
        self,
        tickers: Optional[List[str]] = None,
        skip_existing: bool = True,
        download_financials: bool = True,
        use_batch_prices: bool = True,
        pause_sec: float = 0.25
    ) -> Dict[str, any]:
        """Runs the full download pipeline for benchmark, prices, and financials."""
        # 1. Master ticker universe
        master_df = self.build_master_ticker_list()
        all_tickers = tickers if tickers is not None else master_df["symbol"].tolist()

        # 2. Benchmark
        self.download_benchmark(force=not skip_existing)

        # 3. Prices
        if use_batch_prices:
            success_prices, total_bars, failed_tickers = self.download_all_prices_batch(
                all_tickers,
                batch_size=50,
                force=not skip_existing
            )
        else:
            logger.info(f"Starting prices download for {len(all_tickers)} tickers...")
            success_prices = 0
            total_bars = 0
            failed_tickers = []
            for symbol in tqdm(all_tickers, desc="Downloading Historical Prices"):
                success, bars = self.download_prices_for_ticker(symbol, force=not skip_existing)
                if success and bars > 0:
                    success_prices += 1
                    total_bars += bars
                else:
                    failed_tickers.append(symbol)
                if pause_sec > 0:
                    time.sleep(pause_sec)

        logger.info(
            f"Prices download finished: {success_prices}/{len(all_tickers)} tickers available "
            f"({total_bars:,} total trading bars)."
        )

        # 4. Financials
        success_fin = 0
        if download_financials:
            logger.info(f"Starting financials download for {len(all_tickers)} tickers...")
            for symbol in tqdm(all_tickers, desc="Downloading Financial Statements & Info"):
                if self.download_financials_for_ticker(symbol, force=not skip_existing):
                    success_fin += 1
                if pause_sec > 0:
                    time.sleep(pause_sec)
            logger.info(f"Financials download finished: {success_fin}/{len(all_tickers)} tickers processed.")

        return {
            "total_tickers": len(all_tickers),
            "prices_success": success_prices,
            "financials_success": success_fin,
            "failed_tickers": failed_tickers
        }


if __name__ == "__main__":
    downloader = ItalianMarketDownloader()
    downloader.download_all()
