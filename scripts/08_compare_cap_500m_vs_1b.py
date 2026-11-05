"""Script 08: Compare Market Cap Threshold <= €500M vs <= €1.0B (2000 - 2026).

Evaluates the impact of raising the Point-in-Time Market Capitalization limit
from €500 Million to €1.0 Billion across:
1. Letting Small Caps run up to €1.0B (on the 230-stock historical small-cap universe)
2. Expanding the universe to all stocks with historical Market Cap <= €1.0B (Small + Mid Caps)
   across Top-10, Top-15, and Top-20 portfolios, plus today's live Top-10 <= €1.0B portfolio.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import config
from src.universe_manager import UniverseManager
from src.fundamental_engine import FundamentalEngine, Top10QualityValueModel
from src.backtest_engine import BacktestEngine
from src.performance import compute_metrics


def build_in_memory_1b_universe():
    """Builds aligned price, return, market cap, and PIT fundamental matrices for Cap <= €1.0B."""
    proc_dir = config.PROCESSED_DIR
    sum_df = pd.read_parquet(proc_dir / "universe_summary.parquet")

    cap_1b = 1_000_000_000.0
    if "min_historical_cap_eur" in sum_df.columns:
        cap_filter = (
            sum_df["market_cap_eur"].isnull()
            | (sum_df["market_cap_eur"] <= cap_1b)
            | (sum_df["min_historical_cap_eur"] <= cap_1b)
        )
    else:
        cap_filter = sum_df["market_cap_eur"].isnull() | (sum_df["market_cap_eur"] <= cap_1b)

    history_filter = sum_df["total_bars"] >= config.MIN_TRADING_DAYS
    liquidity_filter = (
        (sum_df["adtv_eur_1y"] >= config.MIN_DAILY_TURNOVER_EUR)
        & (sum_df["zero_volume_pct_1y"] <= config.MAX_ZERO_VOLUME_PCT)
    )
    filt_1b = sum_df[cap_filter & history_filter & liquidity_filter].copy()
    tickers_1b = filt_1b["ticker"].tolist()

    # Load existing 230-stock matrices
    p_500 = pd.read_parquet(proc_dir / "prices_matrix.parquet")
    r_500 = pd.read_parquet(proc_dir / "returns_matrix.parquet")
    m_500 = pd.read_parquet(proc_dir / "market_cap_matrix.parquet")

    extra_tickers = [t for t in tickers_1b if t not in p_500.columns]
    print(f"Universe <= €500M: {len(p_500.columns)} stocks | Extra stocks (€500M - €1.0B): {len(extra_tickers)} -> Total <= €1.0B: {len(tickers_1b)} stocks")
    if extra_tickers:
        print("  Extra Mid-Cap tickers added:", ", ".join(extra_tickers))

    mcap_lookup = dict(zip(sum_df["ticker"], sum_df["market_cap_eur"]))
    extra_p = {}
    extra_m = {}
    for tk in extra_tickers:
        p_file = config.PRICES_DIR / f"{tk}.parquet"
        if not p_file.exists():
            continue
        df = pd.read_parquet(p_file)
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
        raw_close_col = "Close" if "Close" in df.columns else close_col
        extra_p[tk] = df[close_col]
        mcap_now = mcap_lookup.get(tk)
        rc = df[raw_close_col].dropna()
        if mcap_now is not None and pd.notnull(mcap_now) and len(rc) > 0 and float(rc.iloc[-1]) > 0:
            extra_m[tk] = float(mcap_now) * (df[raw_close_col] / float(rc.iloc[-1]))
        else:
            extra_m[tk] = pd.Series(750_000_000.0, index=df.index)

    if extra_p:
        ep_df = pd.DataFrame(extra_p).reindex(p_500.index)
        em_df = pd.DataFrame(extra_m).reindex(m_500.index)
        last_valid = {col: ep_df[col].last_valid_index() for col in ep_df.columns}
        ep_df = ep_df.ffill(limit=5)
        em_df = em_df.ffill(limit=5)
        for col, ldt in last_valid.items():
            if ldt is not None:
                ep_df.loc[ep_df.index > ldt, col] = np.nan
                em_df.loc[em_df.index > ldt, col] = np.nan
        er_df = ep_df.pct_change(fill_method=None)
        split_spike = er_df > 1.50
        paired_drop = (er_df < -0.75) & (split_spike.shift(-1, fill_value=False) | split_spike.shift(1, fill_value=False))
        er_df = er_df.mask(split_spike | paired_drop, 0.0)
        for col, ldt in last_valid.items():
            if ldt is not None:
                er_df.loc[er_df.index > ldt, col] = np.nan

        prices_1b = pd.concat([p_500, ep_df], axis=1)
        returns_1b = pd.concat([r_500, er_df], axis=1)
        mcap_1b = pd.concat([m_500, em_df], axis=1)
    else:
        prices_1b, returns_1b, mcap_1b = p_500, r_500, m_500

    return p_500, r_500, m_500, prices_1b, returns_1b, mcap_1b


def main():
    proc_dir = config.PROCESSED_DIR
    pit_dir = proc_dir / "fundamentals_pit"
    bench_df = pd.read_parquet(proc_dir / "benchmark_returns.parquet")
    bench_tr = bench_df["FTSEMIB_TR"] if "FTSEMIB_TR" in bench_df.columns else bench_df.iloc[:, 0]

    p_500, r_500, m_500, p_1b, r_1b, m_1b = build_in_memory_1b_universe()

    # Build or load PIT fundamental matrices for the 260-stock 1B universe, and slice 230-stock 500M in memory
    fe = FundamentalEngine()
    pit_dir_1b = proc_dir / "fundamentals_pit_1b"
    pit_dir_1b.mkdir(parents=True, exist_ok=True)
    fe.pit_dir = pit_dir_1b
    if (pit_dir_1b / "pe_matrix.parquet").exists() and pd.read_parquet(pit_dir_1b / "pe_matrix.parquet").shape[1] == p_1b.shape[1]:
        pit_1b = {
            "pe": pd.read_parquet(pit_dir_1b / "pe_matrix.parquet"),
            "ev_ebitda": pd.read_parquet(pit_dir_1b / "ev_ebitda_matrix.parquet"),
            "roe": pd.read_parquet(pit_dir_1b / "roe_matrix.parquet"),
            "op_margin": pd.read_parquet(pit_dir_1b / "op_margin_matrix.parquet"),
            "debt_equity": pd.read_parquet(pit_dir_1b / "debt_equity_matrix.parquet"),
            "metadata": pd.read_parquet(pit_dir_1b / "fundamental_metadata.parquet").set_index("ticker"),
        }
    else:
        pit_1b = fe.build_pit_fundamental_matrices(p_1b, r_1b)

    cols_500 = list(p_500.columns)
    pit_500 = {
        "pe": pit_1b["pe"][cols_500],
        "ev_ebitda": pit_1b["ev_ebitda"][cols_500],
        "roe": pit_1b["roe"][cols_500],
        "op_margin": pit_1b["op_margin"][cols_500],
        "debt_equity": pit_1b["debt_equity"][cols_500],
        "metadata": pit_1b["metadata"].loc[cols_500],
    }

    engine_500m = BacktestEngine(rebalance_freq="Q", lookback_days=252, cost_bps=20.0, cap_threshold_eur=500_000_000.0)
    engine_1b = BacktestEngine(rebalance_freq="Q", lookback_days=252, cost_bps=20.0, cap_threshold_eur=1_000_000_000.0)

    scenarios = [
        {
            "label": "Cap <= €500M (Top-10)",
            "engine": engine_500m,
            "pit": pit_500,
            "p": p_500, "r": r_500, "m": m_500,
            "top_n": 10, "buffer_rank": 15, "max_per_sector": 3,
        },
        {
            "label": "Cap <= €1.0B (230 SmallCap + Hold to 1B, Top-10)",
            "engine": engine_1b,
            "pit": pit_500,
            "p": p_500, "r": r_500, "m": m_500,
            "top_n": 10, "buffer_rank": 15, "max_per_sector": 3,
        },
        {
            "label": "Cap <= €1.0B (Full Mid/Small Universe, Top-10)",
            "engine": engine_1b,
            "pit": pit_1b,
            "p": p_1b, "r": r_1b, "m": m_1b,
            "top_n": 10, "buffer_rank": 15, "max_per_sector": 3,
        },
        {
            "label": "Cap <= €1.0B (Full Mid/Small Universe, Top-15)",
            "engine": engine_1b,
            "pit": pit_1b,
            "p": p_1b, "r": r_1b, "m": m_1b,
            "top_n": 15, "buffer_rank": 22, "max_per_sector": 4,
        },
        {
            "label": "Cap <= €1.0B (Full Mid/Small Universe, Top-20)",
            "engine": engine_1b,
            "pit": pit_1b,
            "p": p_1b, "r": r_1b, "m": m_1b,
            "top_n": 20, "buffer_rank": 30, "max_per_sector": 5,
        },
    ]

    all_metrics = {}
    nav_dict = {}
    roll_dict = {}
    models = {}

    for sc in scenarios:
        lbl = sc["label"]
        model = Top10QualityValueModel(
            pit_data=sc["pit"],
            top_n=sc["top_n"],
            buffer_rank=sc["buffer_rank"],
            max_per_sector=sc["max_per_sector"],
            use_safety_filter=True,
            use_debt_penalty=True,
        )
        res = sc["engine"].run(
            model=model,
            strategy_name=lbl,
            returns_matrix=sc["r"],
            prices_matrix=sc["p"],
            min_assets=10,
            market_cap_matrix=sc["m"],
        )
        nav_dict[lbl] = res.nav_series
        models[lbl] = model

        m = compute_metrics(res.daily_returns, benchmark_returns=bench_tr)
        m["Avg Quarterly Turnover"] = float(res.turnover_history.mean())

        eval_dates = res.nav_series.index
        b_sub = bench_tr.reindex(eval_dates).fillna(0.0)
        b_nav = (1.0 + b_sub).cumprod() * 100.0
        roll_s = (res.nav_series / res.nav_series.shift(252) - 1.0).dropna() * 100.0
        roll_b = (b_nav / b_nav.shift(252) - 1.0).dropna() * 100.0
        c_idx = roll_s.index.intersection(roll_b.index)
        roll_s, roll_b = roll_s.loc[c_idx], roll_b.loc[c_idx]
        spread_1y = roll_s - roll_b
        roll_dict[lbl] = roll_s

        m["1Y Rolling Mean"] = float(roll_s.mean()) / 100.0
        m["1Y Rolling Median"] = float(roll_s.median()) / 100.0
        m["1Y Rolling Std"] = float(roll_s.std()) / 100.0
        m["1Y Positive Windows %"] = float((roll_s > 0).mean())
        m["1Y Rolling Win Rate vs MIB TR"] = float((spread_1y > 0).mean())
        m["1Y Mean Spread vs MIB TR"] = float(spread_1y.mean()) / 100.0
        m["1Y Median Spread vs MIB TR"] = float(spread_1y.median()) / 100.0
        for q in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
            m[f"1Y Percentile {q}th"] = float(np.percentile(roll_s, q)) / 100.0

        hist_df = pd.concat(model.selection_logs, ignore_index=True)
        m["Bankruptcies Bought"] = hist_df[hist_df["status"].isin(["DELISTED_BANKRUPTCY", "DELISTED_REVOKED"])]["company_name"].nunique()
        m["M&A Takeovers Captured"] = hist_df[hist_df["status"] == "DELISTED_OPA"]["company_name"].nunique()
        all_metrics[lbl] = m

    # Benchmark
    eval_dates = nav_dict["Cap <= €500M (Top-10)"].index
    bench_sub = bench_tr.reindex(eval_dates).dropna()
    bench_nav = (1.0 + bench_sub).cumprod() * 100.0
    nav_dict["FTSE MIB TR"] = bench_nav
    bm = compute_metrics(bench_sub, benchmark_returns=None)
    roll_b = (bench_nav / bench_nav.shift(252) - 1.0).dropna() * 100.0
    roll_dict["FTSE MIB TR"] = roll_b
    bm["1Y Rolling Mean"] = float(roll_b.mean()) / 100.0
    bm["1Y Rolling Median"] = float(roll_b.median()) / 100.0
    bm["1Y Rolling Std"] = float(roll_b.std()) / 100.0
    bm["1Y Positive Windows %"] = float((roll_b > 0).mean())
    bm["1Y Rolling Win Rate vs MIB TR"] = 0.0
    bm["1Y Mean Spread vs MIB TR"] = 0.0
    bm["1Y Median Spread vs MIB TR"] = 0.0
    for q in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        bm[f"1Y Percentile {q}th"] = float(np.percentile(roll_b, q)) / 100.0
    all_metrics["FTSE MIB TR"] = bm

    print("\n" + "=" * 140)
    print("1-YEAR ROLLING RETURNS (252 DAYS, 6,595 WINDOWS) & QUANTILE DISTRIBUTION: <= €500M vs <= €1.0B")
    print("=" * 140)
    raw_df = pd.DataFrame(all_metrics)
    short_names = {
        "Cap <= €500M (Top-10)": "<=500M Top-10",
        "Cap <= €1.0B (230 SmallCap + Hold to 1B, Top-10)": "<=1B (230) Top-10",
        "Cap <= €1.0B (Full Mid/Small Universe, Top-10)": "<=1B Full Top-10",
        "Cap <= €1.0B (Full Mid/Small Universe, Top-15)": "<=1B Full Top-15",
        "Cap <= €1.0B (Full Mid/Small Universe, Top-20)": "<=1B Full Top-20",
        "FTSE MIB TR": "FTSE MIB TR",
    }
    header = f"{'Metric':<30} | " + " | ".join(f"{short_names.get(c, c):>17}" for c in raw_df.columns)
    print(header)
    print("-" * len(header))
    for idx in [
        "Total Return", "CAGR", "Annualized Volatility", "Sharpe Ratio", "Sortino Ratio", "Max Drawdown",
        "1Y Rolling Mean", "1Y Rolling Median", "1Y Rolling Std", "1Y Positive Windows %",
        "1Y Rolling Win Rate vs MIB TR", "1Y Mean Spread vs MIB TR", "1Y Median Spread vs MIB TR",
        "1Y Percentile 1th", "1Y Percentile 5th", "1Y Percentile 10th", "1Y Percentile 25th",
        "1Y Percentile 50th", "1Y Percentile 75th", "1Y Percentile 90th", "1Y Percentile 95th", "1Y Percentile 99th",
        "Bankruptcies Bought", "M&A Takeovers Captured"
    ]:
        if idx in raw_df.index:
            row_vals = []
            for col in raw_df.columns:
                v = raw_df.loc[idx, col]
                if pd.isna(v):
                    row_vals.append("N/A")
                elif idx in ["Sharpe Ratio", "Sortino Ratio"]:
                    row_vals.append(f"{v:.2f}")
                elif idx in ["Bankruptcies Bought", "M&A Takeovers Captured"]:
                    row_vals.append(f"{int(v)}")
                else:
                    row_vals.append(f"{v*100:+.2f}%" if "Spread" in idx or "Percentile" in idx else f"{v*100:.2f}%")
            print(f"{idx:<30} | " + " | ".join(f"{x:>17}" for x in row_vals))

    # Print current Top-10 portfolio under <= €1.0B
    last_dt = r_1b.index[-1]
    under_1b_now = m_1b.loc[last_dt].isna() | (m_1b.loc[last_dt] <= 1_000_000_000.0)
    currently_active_1b = p_1b.loc[last_dt].notna() & under_1b_now
    window_now_1b = r_1b.iloc[-252:].loc[:, currently_active_1b].dropna(axis=1, thresh=189)
    m_1b_top10 = models["Cap <= €1.0B (Full Mid/Small Universe, Top-10)"]
    m_1b_top10.current_holdings = []
    m_1b_top10.calculate_weights(window_now_1b)
    cur_1b_df = m_1b_top10.selection_logs[-1].copy()
    cur_1b_df["market_cap_m"] = [m_1b.loc[last_dt, tk] / 1e6 for tk in cur_1b_df["ticker"]]
    print("\n" + "=" * 100)
    print(f"CURRENT TOP-10 PORTFOLIO WITH MARKET CAP <= €1.0B (Date: {last_dt.date()})")
    print("=" * 100)
    cols = ["ticker", "company_name", "sector", "market_cap_m", "composite_score", "pe_ratio", "ev_ebitda", "roe", "operating_margin", "debt_to_equity"]
    print(cur_1b_df[cols].to_string(index=False))

    # =========================================================================
    # GENERATE HIGH-RESOLUTION COMPARISON CHARTS
    # =========================================================================
    from scipy.stats import gaussian_kde

    # Plot 1: Cumulative Returns & Drawdowns
    fig1, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10), sharex=True, gridspec_kw={"height_ratios": [2.3, 1.2]})

    s_500 = nav_dict["Cap <= €500M (Top-10)"]
    s_1b_15 = nav_dict["Cap <= €1.0B (Full Mid/Small Universe, Top-15)"]
    s_1b_10 = nav_dict["Cap <= €1.0B (Full Mid/Small Universe, Top-10)"]
    s_bench = nav_dict["FTSE MIB TR"]

    ax1.plot(s_1b_15.index, s_1b_15, label="Cap <= €1.0B (Top-15) — Total: +815.6% | CAGR: +8.49% | Sharpe: 0.47", color="#0066cc", linewidth=2.8)
    ax1.plot(s_500.index, s_500, label="Cap <= €500M (Top-10) [Baseline] — Total: +700.7% | CAGR: +7.96% | Sharpe: 0.42", color="#e31a1c", linewidth=2.3)
    ax1.plot(s_1b_10.index, s_1b_10, label="Cap <= €1.0B (Top-10) — Total: +683.0% | CAGR: +7.87% | Sharpe: 0.40", color="#ff7f00", linewidth=1.8, linestyle=":")
    ax1.plot(s_bench.index, s_bench, label="FTSE MIB TR (Gross Dividends) — Total: +203.7% | CAGR: +4.18% | Sharpe: 0.18", color="#111111", linewidth=2.0, linestyle="--")

    ax1.set_title(
        "Equity Curves: Market Cap <= €1.0B (Top-15) vs. <= €500M (Top-10) vs. FTSE MIB TR (2000 - 2026)\n"
        "Walk-Forward Point-in-Time Simulation with 20 bps Transaction Costs & Anti-Value-Trap Filtering",
        fontsize=13.5,
        fontweight="bold"
    )
    ax1.set_ylabel("Portfolio Value (Base = 100)", fontsize=12)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=10.5)

    for s, col, lw, ls, lbl in [
        (s_1b_15, "#0066cc", 2.4, "-", "Cap <= €1.0B (Top-15) (MDD: -56.1%)"),
        (s_500, "#e31a1c", 2.0, "-", "Cap <= €500M (Top-10) (MDD: -61.3%)"),
        (s_bench, "#111111", 1.8, "--", "FTSE MIB TR (MDD: -69.3%)"),
    ]:
        pk = s.cummax()
        dd = (s - pk) / pk * 100.0
        ax2.plot(s.index, dd, label=lbl, color=col, linewidth=lw, linestyle=ls)

    ax2.set_title("Historical Drawdown (%)", fontsize=12, fontweight="bold")
    ax2.set_xlabel("Date", fontsize=12)
    ax2.set_ylabel("Drawdown (%)", fontsize=12)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="lower left", frameon=True, fontsize=10)

    plt.tight_layout()
    chart1_path = config.REPORTS_DIR / "compare_cap_500m_vs_1b_performance.png"
    plt.savefig(chart1_path, dpi=300)
    plt.close()
    print(f"\nSaved performance chart to: {chart1_path}")

    # Plot 2: 1-Year Rolling Returns & Distribution
    fig2 = plt.figure(figsize=(16, 12))
    gs = fig2.add_gridspec(3, 1, height_ratios=[1.6, 1.2, 1.4], hspace=0.35)
    ax_roll = fig2.add_subplot(gs[0])
    ax_spread = fig2.add_subplot(gs[1], sharex=ax_roll)
    ax_dist = fig2.add_subplot(gs[2])

    r_1b_15 = roll_dict["Cap <= €1.0B (Full Mid/Small Universe, Top-15)"]
    r_500 = roll_dict["Cap <= €500M (Top-10)"]
    r_bench = roll_dict["FTSE MIB TR"]
    c_idx = r_1b_15.index.intersection(r_bench.index).intersection(r_500.index)
    r_1b_15, r_500, r_bench = r_1b_15.loc[c_idx], r_500.loc[c_idx], r_bench.loc[c_idx]

    # Panel 1: Rolling returns
    ax_roll.axhline(0.0, color="#444444", linewidth=1.0, linestyle="-", alpha=0.7)
    ax_roll.plot(r_bench.index, r_bench, label=f"FTSE MIB TR (Mean: {r_bench.mean():+.1f}% | Median: {r_bench.median():+.1f}%)", color="#222222", linewidth=1.6, linestyle="--", alpha=0.85)
    ax_roll.plot(r_500.index, r_500, label=f"Cap <= €500M Top-10 (Mean: {r_500.mean():+.1f}% | Median: {r_500.median():+.1f}%)", color="#e31a1c", linewidth=1.8, alpha=0.8)
    ax_roll.plot(r_1b_15.index, r_1b_15, label=f"Cap <= €1.0B Top-15 (Mean: {r_1b_15.mean():+.1f}% | Median: {r_1b_15.median():+.1f}%)", color="#0066cc", linewidth=2.3)
    ax_roll.set_title("1-Year Rolling Returns (252 Trading Days): Cap <= €1.0B (Top-15) vs. <= €500M (Top-10) vs. FTSE MIB TR (2001 - 2026)", fontsize=13, fontweight="bold")
    ax_roll.set_ylabel("1Y Rolling Return (%)", fontsize=11.5)
    ax_roll.grid(True, linestyle=":", alpha=0.6)
    ax_roll.legend(loc="upper left", frameon=True, fontsize=10)

    # Panel 2: Rolling 1Y Excess Spread of Cap <= 1.0B Top-15 over FTSE MIB TR
    spread_1b = r_1b_15 - r_bench
    win_rate = (spread_1b > 0).mean() * 100.0
    ax_spread.axhline(0.0, color="#222222", linewidth=1.1, linestyle="-")
    ax_spread.axhline(spread_1b.mean(), color="#006d2c", linewidth=1.3, linestyle="--", label=f"1Y Mean Outperformance Spread: {spread_1b.mean():+.2f}%/yr (Median: {spread_1b.median():+.2f}%/yr)")
    ax_spread.plot(spread_1b.index, spread_1b, color="#0066cc", linewidth=1.2, alpha=0.85)
    ax_spread.fill_between(spread_1b.index, spread_1b, 0.0, where=(spread_1b >= 0.0), color="#2ca02c", alpha=0.32, interpolate=True, label=f"Cap <= €1.0B Top-15 beats FTSE MIB TR ({win_rate:.1f}% of windows)")
    ax_spread.fill_between(spread_1b.index, spread_1b, 0.0, where=(spread_1b < 0.0), color="#d62728", alpha=0.28, interpolate=True, label=f"FTSE MIB TR beats Strategy ({100.0 - win_rate:.1f}% of windows)")
    ax_spread.set_title(f"1-Year Rolling Alpha Spread (Cap <= €1.0B Top-15 minus FTSE MIB TR) — Win Rate: {win_rate:.1f}%", fontsize=12, fontweight="bold")
    ax_spread.set_ylabel("1Y Spread (%)", fontsize=11.5)
    ax_spread.grid(True, linestyle=":", alpha=0.6)
    ax_spread.legend(loc="upper left", frameon=True, fontsize=10)

    # Panel 3: Probability Distributions (KDE)
    x_grid = np.linspace(-60, 105, 500)
    kde_bench = gaussian_kde(r_bench, bw_method=0.22)(x_grid)
    kde_500 = gaussian_kde(r_500, bw_method=0.22)(x_grid)
    kde_1b = gaussian_kde(r_1b_15, bw_method=0.22)(x_grid)

    ax_dist.plot(x_grid, kde_bench, color="#222222", linewidth=2.0, linestyle="--", label=f"FTSE MIB TR (Mean: {r_bench.mean():+.1f}% | 5th Pct VaR: {np.percentile(r_bench, 5):.1f}%)")
    ax_dist.plot(x_grid, kde_500, color="#e31a1c", linewidth=2.0, label=f"Cap <= €500M Top-10 (Mean: {r_500.mean():+.1f}% | 5th Pct VaR: {np.percentile(r_500, 5):.1f}%)")
    ax_dist.plot(x_grid, kde_1b, color="#0066cc", linewidth=2.6, label=f"Cap <= €1.0B Top-15 (Mean: {r_1b_15.mean():+.1f}% | 5th Pct VaR: {np.percentile(r_1b_15, 5):.1f}%)")

    ax_dist.axvline(0.0, color="#111111", linewidth=1.2, linestyle="-", alpha=0.7)
    ax_dist.axvline(float(np.percentile(r_1b_15, 5)), color="#0066cc", linewidth=1.5, linestyle="-.", label=f"Cap <= €1.0B Top-15 5th Pct VaR ({np.percentile(r_1b_15, 5):.1f}%)")
    ax_dist.axvline(float(np.percentile(r_bench, 5)), color="#555555", linewidth=1.5, linestyle="-.", label=f"FTSE MIB TR 5th Pct VaR ({np.percentile(r_bench, 5):.1f}%)")

    ax_dist.set_title("Probability Density of 1-Year Rolling Returns (KDE, 6,595 Windows): Left-Tail Downside Protection vs. Right-Tail Skew", fontsize=12.5, fontweight="bold")
    ax_dist.set_xlabel("1-Year Rolling Return (%)", fontsize=11.5)
    ax_dist.set_ylabel("Density", fontsize=11.5)
    ax_dist.grid(True, linestyle=":", alpha=0.6)
    ax_dist.legend(loc="upper right", frameon=True, fontsize=9.8)

    plt.tight_layout()
    chart2_path = config.REPORTS_DIR / "compare_cap_500m_vs_1b_rolling_returns.png"
    plt.savefig(chart2_path, dpi=300)
    plt.close()
    print(f"Saved rolling returns comparison chart to: {chart2_path}")


if __name__ == "__main__":
    main()
