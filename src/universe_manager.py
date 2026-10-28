"""Universe Manager for Italian Small and Mid Cap Equities.

Parses downloaded stock prices and metadata, filters companies based on:
1. Market Capitalization (< 500 Million EUR)
2. Historical trading length (minimum trading days)
3. Liquidity & Tradability (ADTV - Average Daily Traded Value, zero volume frequency)

Generates clean aligned pivot matrices (Adjusted Close, Daily Returns, Volumes) for portfolio optimization.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)


class UniverseManager:
    """Processes raw market data, filters small/mid cap universe, and aligns time series."""

    def __init__(
        self,
        cap_threshold_eur: float = config.MARKET_CAP_THRESHOLD_EUR,
        min_trading_days: int = config.MIN_TRADING_DAYS,
        min_adtv_eur: float = config.MIN_DAILY_TURNOVER_EUR,
        max_zero_vol_pct: float = config.MAX_ZERO_VOLUME_PCT
    ):
        self.cap_threshold_eur = cap_threshold_eur
        self.min_trading_days = min_trading_days
        self.min_adtv_eur = min_adtv_eur
        self.max_zero_vol_pct = max_zero_vol_pct

        self.prices_dir = config.PRICES_DIR
        self.info_dir = config.INFO_DIR
        self.benchmark_dir = config.BENCHMARK_DIR
        self.processed_dir = config.PROCESSED_DIR
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def scan_and_summarize_tickers(self) -> pd.DataFrame:
        """Inspects all downloaded tickers, computes stats, liquidity metrics, and market cap."""
        price_files = list(self.prices_dir.glob("*.parquet"))
        if not price_files:
            raise FileNotFoundError(f"No price parquet files found in {self.prices_dir}. Run downloader first.")

        records = []
        for p_file in price_files:
            ticker = p_file.stem
            try:
                df = pd.read_parquet(p_file)
                if df.empty or len(df) < 10:
                    continue

                # Date range
                start_dt = df.index[0]
                end_dt = df.index[-1]
                n_bars = len(df)

                # Adjusted close column
                close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
                prices = df[close_col].dropna()
                volumes = df["Volume"].dropna() if "Volume" in df.columns else pd.Series(0, index=df.index)

                # Daily returns
                daily_ret = prices.pct_change().dropna()
                ann_vol = daily_ret.std() * np.sqrt(252) if len(daily_ret) > 20 else np.nan

                # Liquidity metrics (last 252 days or full if shorter)
                recent_df = df.iloc[-min(252, len(df)):]
                recent_close = recent_df[close_col]
                recent_vol = recent_df["Volume"] if "Volume" in recent_df.columns else pd.Series(0, index=recent_df.index)

                traded_val_eur = recent_close * recent_vol
                adtv_eur = traded_val_eur.mean()
                zero_vol_pct = (recent_vol == 0).mean()

                # Read info metadata
                info_path = self.info_dir / f"{ticker}_info.json"
                info = {}
                if info_path.exists():
                    try:
                        with open(info_path, "r", encoding="utf-8") as f:
                            info = json.load(f)
                    except Exception:
                        pass

                market_cap = info.get("marketCap")
                sector = info.get("sector", "Unknown")
                industry = info.get("industry", "Unknown")
                company_name = info.get("shortName") or info.get("longName") or ticker
                pe_ratio = info.get("trailingPE")
                pb_ratio = info.get("priceToBook")
                ev_ebitda = info.get("enterpriseToEbitda")
                div_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield")
                roe = info.get("returnOnEquity")
                debt_to_equity = info.get("debtToEquity")
                status = info.get("status", "ACTIVE")
                is_delisted = bool(info.get("delisted", False))
                delisting_date = info.get("delisting_date")
                data_source = info.get("data_source", "Yahoo Finance")
                isin = info.get("isin")

                # Compute Point-in-Time historical Market Cap range (from 1999 onwards)
                raw_close = df["Close"].dropna() if "Close" in df.columns else prices
                raw_close_post99 = raw_close.loc[raw_close.index >= pd.Timestamp("1999-01-01")] if len(raw_close) > 0 else raw_close
                if len(raw_close_post99) == 0:
                    raw_close_post99 = raw_close
                if market_cap is not None and len(raw_close_post99) > 0 and float(raw_close_post99.iloc[-1]) > 0:
                    hist_mcap = float(market_cap) * (raw_close_post99 / float(raw_close_post99.iloc[-1]))
                    min_hist_cap = float(hist_mcap.min())
                    pct_under_cap = float((hist_mcap <= self.cap_threshold_eur).mean())
                else:
                    min_hist_cap = float(market_cap) if market_cap is not None else np.nan
                    pct_under_cap = 1.0

                records.append({
                    "ticker": ticker,
                    "company_name": company_name,
                    "isin": isin,
                    "status": status,
                    "delisted": is_delisted,
                    "delisting_date": delisting_date,
                    "data_source": data_source,
                    "sector": sector,
                    "industry": industry,
                    "market_cap_eur": market_cap,
                    "min_historical_cap_eur": min_hist_cap,
                    "pct_days_under_cap": pct_under_cap,
                    "start_date": str(start_dt.date()) if hasattr(start_dt, "date") else str(start_dt),
                    "end_date": str(end_dt.date()) if hasattr(end_dt, "date") else str(end_dt),
                    "total_bars": n_bars,
                    "last_close": float(prices.iloc[-1]) if len(prices) > 0 else np.nan,
                    "annualized_volatility": float(ann_vol) if pd.notnull(ann_vol) else np.nan,
                    "adtv_eur_1y": float(adtv_eur) if pd.notnull(adtv_eur) else 0.0,
                    "zero_volume_pct_1y": float(zero_vol_pct) if pd.notnull(zero_vol_pct) else 0.0,
                    "pe_ratio": float(pe_ratio) if pe_ratio is not None else np.nan,
                    "pb_ratio": float(pb_ratio) if pb_ratio is not None else np.nan,
                    "ev_ebitda": float(ev_ebitda) if ev_ebitda is not None else np.nan,
                    "roe": float(roe) if roe is not None else np.nan,
                    "dividend_yield": float(div_yield) if div_yield is not None else np.nan,
                    "debt_to_equity": float(debt_to_equity) if debt_to_equity is not None else np.nan,
                })
            except Exception as e:
                logger.debug(f"Error processing {p_file}: {e}")

        summary_df = pd.DataFrame(records)
        summary_df = summary_df.sort_values(by="market_cap_eur", ascending=True).reset_index(drop=True)

        summary_df.to_parquet(self.processed_dir / "universe_summary.parquet", index=False)
        summary_df.to_csv(self.processed_dir / "universe_summary.csv", index=False)
        return summary_df

    def filter_small_mid_caps(self, summary_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Applies filters to identify valid Italian small & mid cap companies under 500M EUR."""
        if summary_df is None:
            sum_path = self.processed_dir / "universe_summary.parquet"
            if sum_path.exists():
                summary_df = pd.read_parquet(sum_path)
            else:
                summary_df = self.scan_and_summarize_tickers()

        df = summary_df.copy()

        # 1. Point-in-Time Market Cap Filter: <= 500M EUR either today OR historically (at least 5% of trading history)
        # This eliminates "Winners' Exclusion Bias" by allowing former Small Caps (e.g. Reply, Interpump,
        # De'Longhi, SOL, Sesa, Cembre, El.En., Brembo) into the candidate pool during the years when their
        # historical Market Cap was <= 500M EUR, before graduating out once they exceed 500M EUR.
        if "min_historical_cap_eur" in df.columns and "pct_days_under_cap" in df.columns:
            cap_filter = (
                (df["market_cap_eur"].isnull())
                | (df["market_cap_eur"] <= self.cap_threshold_eur)
                | ((df["min_historical_cap_eur"] <= self.cap_threshold_eur) & (df["pct_days_under_cap"] >= 0.05))
            )
        else:
            cap_filter = (df["market_cap_eur"].isnull()) | (df["market_cap_eur"] <= self.cap_threshold_eur)

        # 2. History Filter
        history_filter = df["total_bars"] >= self.min_trading_days

        # 3. Liquidity Filters
        liquidity_filter = (df["adtv_eur_1y"] >= self.min_adtv_eur) & (df["zero_volume_pct_1y"] <= self.max_zero_vol_pct)

        filtered = df[cap_filter & history_filter & liquidity_filter].copy()
        filtered = filtered.sort_values(by="adtv_eur_1y", ascending=False).reset_index(drop=True)

        logger.info(
            f"Screening complete: {len(filtered)} / {len(df)} tickers passed filters "
            f"(Cap <= {self.cap_threshold_eur/1e6:.0f}M €, Min Bars={self.min_trading_days}, "
            f"Min ADTV={self.min_adtv_eur:,.0f} €, Max Zero Vol={self.max_zero_vol_pct:.0%})."
        )

        filtered.to_parquet(self.processed_dir / "universe_filtered.parquet", index=False)
        filtered.to_csv(self.processed_dir / "universe_filtered.csv", index=False)
        return filtered

    def build_aligned_matrices(
        self,
        tickers: Optional[List[str]] = None,
        start_date: Optional[str] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
        """Aligns time series across all selected tickers into synchronized Date x Ticker matrices.

        Returns:
            (prices_matrix, returns_matrix, volume_eur_matrix, benchmark_returns)
        """
        if tickers is None:
            filt_path = self.processed_dir / "universe_filtered.parquet"
            if filt_path.exists():
                tickers = pd.read_parquet(filt_path)["ticker"].tolist()
            else:
                filtered_df = self.filter_small_mid_caps()
                tickers = filtered_df["ticker"].tolist()

        logger.info(f"Building aligned matrices for {len(tickers)} tickers...")
        price_series = {}
        volume_eur_series = {}
        mcap_series = {}

        # Load latest market cap metadata for Point-in-Time Market Cap reconstruction
        sum_path = self.processed_dir / "universe_summary.parquet"
        mcap_lookup = {}
        if sum_path.exists():
            sum_df = pd.read_parquet(sum_path)
            mcap_lookup = dict(zip(sum_df["ticker"], sum_df["market_cap_eur"]))

        for tk in tickers:
            p_file = self.prices_dir / f"{tk}.parquet"
            if not p_file.exists():
                continue
            try:
                df = pd.read_parquet(p_file)
                # Standardize index to date without tz
                df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
                close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
                raw_close_col = "Close" if "Close" in df.columns else close_col
                price_series[tk] = df[close_col]
                if "Volume" in df.columns:
                    volume_eur_series[tk] = df[close_col] * df["Volume"]

                # Reconstruct Point-in-Time Market Cap series: MarketCap_t = MarketCap_last * (Close_t / Close_last)
                mcap_now = mcap_lookup.get(tk)
                rc = df[raw_close_col].dropna()
                if mcap_now is not None and pd.notnull(mcap_now) and len(rc) > 0 and float(rc.iloc[-1]) > 0:
                    mcap_series[tk] = float(mcap_now) * (df[raw_close_col] / float(rc.iloc[-1]))
                else:
                    mcap_series[tk] = pd.Series(250_000_000.0, index=df.index)
            except Exception:
                pass

        prices_df = pd.DataFrame(price_series).sort_index()
        vol_eur_df = pd.DataFrame(volume_eur_series).sort_index()
        mcap_df = pd.DataFrame(mcap_series).sort_index()

        if start_date:
            prices_df = prices_df.loc[start_date:]
            vol_eur_df = vol_eur_df.loc[start_date:]
            mcap_df = mcap_df.loc[start_date:]

        # Trim trailing partial dates where fewer than 50 stocks have quotes (e.g. partial incremental updates)
        active_counts = prices_df.notna().sum(axis=1)
        valid_market_dates = active_counts[active_counts >= min(50, max(10, int(len(tickers) * 0.25)))].index
        if len(valid_market_dates) > 0:
            max_common_dt = valid_market_dates[-1]
            prices_df = prices_df.loc[:max_common_dt]
            vol_eur_df = vol_eur_df.loc[:max_common_dt]
            mcap_df = mcap_df.loc[:max_common_dt]

        # Forward fill missing prices for up to 5 days ONLY within each stock's active trading lifespan
        # (never extend prices past a company's delisting / last valid trading date)
        last_valid_dates = {col: prices_df[col].last_valid_index() for col in prices_df.columns}
        prices_df = prices_df.ffill(limit=5)
        mcap_df = mcap_df.ffill(limit=5)
        for col, last_dt in last_valid_dates.items():
            if last_dt is not None:
                prices_df.loc[prices_df.index > last_dt, col] = np.nan
                mcap_df.loc[mcap_df.index > last_dt, col] = np.nan

        returns_df = prices_df.pct_change(fill_method=None)
        # Neutralize unadjusted reverse-split data glitches (> +150% single-day spike and paired split drops)
        split_spike = returns_df > 1.50
        paired_drop = (returns_df < -0.75) & (split_spike.shift(-1, fill_value=False) | split_spike.shift(1, fill_value=False))
        returns_df = returns_df.mask(split_spike | paired_drop, 0.0)
        for col, last_dt in last_valid_dates.items():
            if last_dt is not None:
                returns_df.loc[returns_df.index > last_dt, col] = np.nan

        # Load benchmark and enrich with FTSE MIB Total Return (reinvested constituent dividends)
        bench_file = list(self.benchmark_dir.glob("*.parquet"))
        bench_ret = pd.Series(dtype=float)
        bench_df_out = pd.DataFrame()
        if bench_file:
            try:
                b_df = pd.read_parquet(bench_file[0])
                b_df.index = pd.to_datetime(b_df.index).tz_localize(None).normalize()
                b_price = b_df["Close"]
                r_price = b_price.pct_change(fill_method=None).dropna()

                # Compute exact daily dividend yield paid on Borsa Italiana ex-dividend dates
                # across FTSE MIB blue-chip constituents (Eni, Enel, Intesa, UniCredit, Generali, etc.)
                ftsemib_blue_chips = [
                    "ENI.MI", "ENEL.MI", "ISP.MI", "UCG.MI", "G.MI", "MB.MI", "TRN.MI", "SRG.MI",
                    "PST.MI", "A2A.MI", "BPE.MI", "BMED.MI", "LDO.MI", "PRY.MI", "STM.MI", "TIT.MI",
                    "CPR.MI", "REC.MI", "MONC.MI", "AMP.MI", "HER.MI", "BAMI.MI", "SPM.MI", "TEN.MI",
                    "IG.MI", "UNI.MI", "BZU.MI", "INW.MI", "NEXI.MI", "DIA.MI"
                ]
                div_yield_list = []
                for b_tk in ftsemib_blue_chips:
                    b_pfile = self.prices_dir / f"{b_tk}.parquet"
                    if b_pfile.exists():
                        try:
                            bdf_tk = pd.read_parquet(b_pfile)
                            bdf_tk.index = pd.to_datetime(bdf_tk.index).tz_localize(None).normalize()
                            if "Close" in bdf_tk.columns and "Adj Close" in bdf_tk.columns:
                                rc = bdf_tk["Close"].pct_change(fill_method=None)
                                ra = bdf_tk["Adj Close"].pct_change(fill_method=None)
                                dy = ((1.0 + ra) / (1.0 + rc) - 1.0).clip(lower=0.0, upper=0.12)
                                div_yield_list.append(dy)
                        except Exception:
                            pass

                if div_yield_list:
                    dy_daily = pd.concat(div_yield_list, axis=1, sort=True).mean(axis=1).reindex(r_price.index).fillna(0.0)
                else:
                    dy_daily = pd.Series(0.0, index=r_price.index)

                # Total Return = (1 + Price Return) * (1 + Daily Ex-Dividend Yield) - 1
                r_tr = (1.0 + r_price) * (1.0 + dy_daily) - 1.0
                r_tr.name = "FTSEMIB_TR"
                r_price.name = "FTSEMIB_PRICE"

                # Update Adj Close in ftsemib_mi.parquet to reflect Total Return index level
                tr_index_level = b_price.iloc[0] * (1.0 + r_tr).cumprod()
                b_df["Adj Close"] = b_df["Close"]
                b_df.loc[tr_index_level.index, "Adj Close"] = tr_index_level
                b_df.to_parquet(bench_file[0])

                bench_ret = r_tr
                bench_df_out = pd.DataFrame({"FTSEMIB_TR": r_tr, "FTSEMIB_PRICE": r_price})
            except Exception as e:
                logger.warning(f"Failed loading benchmark: {e}")

        # Save matrices
        prices_df.to_parquet(self.processed_dir / "prices_matrix.parquet")
        returns_df.to_parquet(self.processed_dir / "returns_matrix.parquet")
        vol_eur_df.to_parquet(self.processed_dir / "volume_eur_matrix.parquet")
        mcap_df.to_parquet(self.processed_dir / "market_cap_matrix.parquet")
        if not bench_df_out.empty:
            bench_df_out.to_parquet(self.processed_dir / "benchmark_returns.parquet")
        elif not bench_ret.empty:
            bench_ret.to_frame().to_parquet(self.processed_dir / "benchmark_returns.parquet")

        logger.info(
            f"Aligned matrices saved: shape {prices_df.shape} "
            f"from {prices_df.index[0].strftime('%Y-%m-%d')} to {prices_df.index[-1].strftime('%Y-%m-%d')}."
        )

        return prices_df, returns_df, vol_eur_df, bench_ret


if __name__ == "__main__":
    mgr = UniverseManager()
    summary = mgr.scan_and_summarize_tickers()
    filtered = mgr.filter_small_mid_caps(summary)
    prices, rets, vols, b_rets = mgr.build_aligned_matrices()
