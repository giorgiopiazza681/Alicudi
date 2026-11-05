"""Script 03: Execute Walk-Forward Backtest for My Strategy vs. FTSE MIB TR (2000 - 2026).

Strategy Specifications ("My Strategy"):
- Universe: Survivorship-bias-free Italian Small & Mid Caps (Point-in-Time Market Cap <= €1.0B)
- Composite Score: Valuation (45%: E/P + EBITDA/EV) + Profitability (40%: ROE + Operating Margin) + Solvency (15%: Low Debt/Equity)
- Anti-Value-Trap Filter: Excludes bottom 25% by Momentum, top 25% by Volatility, and requires positive margins/ROE
- Portfolio Construction: 15 equal-weighted stocks (6.67% each), max 4 per GICS sector, Top-22 hysteresis buffer
- Rebalancing: Quarterly ("Q") with 20 bps transaction cost

Outputs saved to `reports/`:
- `strategy_comparison.csv`
- `current_portfolio.csv`
- `historical_selections.csv`
- `strategy_performance.png`

Usage:
    python scripts/03_run_strategy.py
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config
from src.backtest_engine import BacktestEngine
from src.fundamental_engine import FundamentalEngine, QualityValueModel
from src.performance import compute_metrics, format_metrics_table


def main():
    proc_dir = config.PROCESSED_DIR
    prices_matrix = pd.read_parquet(proc_dir / "prices_matrix.parquet")
    returns_matrix = pd.read_parquet(proc_dir / "returns_matrix.parquet")
    benchmark_df = pd.read_parquet(proc_dir / "benchmark_returns.parquet")
    bench_tr = benchmark_df["FTSEMIB_TR"] if "FTSEMIB_TR" in benchmark_df.columns else benchmark_df.iloc[:, 0]
    bench_price = benchmark_df["FTSEMIB_PRICE"] if "FTSEMIB_PRICE" in benchmark_df.columns else None

    pit_data = FundamentalEngine().load_or_build_pit_matrices(prices_matrix, returns_matrix)

    print("=" * 88)
    print(f"RUNNING WALK-FORWARD BACKTEST: MY STRATEGY ({config.PORTFOLIO_TOP_N} STOCKS, <= €{config.MARKET_CAP_THRESHOLD_EUR/1e9:.1f}B CAP)")
    print("=" * 88)

    engine = BacktestEngine()
    model = QualityValueModel(pit_data=pit_data)
    res = engine.run(
        model=model,
        strategy_name="My Strategy",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
        min_assets=10,
    )

    eval_dates = res.nav_series.index
    bench_sub = bench_tr.reindex(eval_dates).dropna()
    bench_tr_nav = (1.0 + bench_sub).cumprod() * 100.0

    # Compute comparative metrics
    strat_metrics = compute_metrics(res.daily_returns, benchmark_returns=bench_tr)
    strat_metrics["Avg Quarterly Turnover"] = float(res.turnover_history.mean())
    all_metrics = {
        "My Strategy": strat_metrics,
        "FTSE MIB TR (Gross Dividends)": compute_metrics(bench_sub, benchmark_returns=None),
    }
    if bench_price is not None:
        bench_p_sub = bench_price.reindex(eval_dates).dropna()
        all_metrics["FTSE MIB Price (No Div)"] = compute_metrics(bench_p_sub, benchmark_returns=None)

    formatted_table = format_metrics_table(all_metrics)
    print(formatted_table.to_string())

    # Persist daily NAVs for fast downstream rolling return analysis
    nav_df = pd.DataFrame({
        "My Strategy": res.nav_series,
        "FTSE MIB TR (Gross Dividends)": bench_tr_nav,
    }).dropna()
    nav_df.to_parquet(proc_dir / "strategy_nav.parquet")

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    formatted_table.to_csv(config.REPORTS_DIR / "strategy_comparison.csv")

    # Save historical selections and live portfolio
    if model.selection_logs:
        hist_sel_df = pd.concat(model.selection_logs, ignore_index=True)
        hist_sel_df.to_csv(config.REPORTS_DIR / "historical_selections.csv", index=False)

        last_dt = returns_matrix.index[-1]
        mcap_path = proc_dir / "market_cap_matrix.parquet"
        mcap_matrix = pd.read_parquet(mcap_path) if mcap_path.exists() else None
        if mcap_matrix is not None and last_dt in mcap_matrix.index:
            under_cap_now = mcap_matrix.loc[last_dt].isna() | (mcap_matrix.loc[last_dt] <= config.MARKET_CAP_THRESHOLD_EUR)
        else:
            under_cap_now = pd.Series(True, index=prices_matrix.columns)

        currently_active = prices_matrix.loc[last_dt].notna() & under_cap_now
        window_now = returns_matrix.iloc[-252:].loc[:, currently_active].dropna(axis=1, thresh=189)
        model.current_holdings = []
        model.calculate_weights(window_now)
        current_df = model.selection_logs[-1].copy()
        current_df.to_csv(config.REPORTS_DIR / "current_portfolio.csv", index=False)

        print("\n" + "=" * 88)
        print(f"CURRENT PORTFOLIO ({config.PORTFOLIO_TOP_N} STOCKS, <= €{config.MARKET_CAP_THRESHOLD_EUR/1e9:.1f}B EUR, Date: {last_dt.date()})")
        print("=" * 88)
        display_cols = [
            "ticker", "company_name", "sector", "composite_score",
            "pe_ratio", "ev_ebitda", "roe", "operating_margin", "debt_to_equity", "weight"
        ]
        disp = current_df[display_cols].copy()
        disp["composite_score"] = disp["composite_score"].map(lambda x: f"{x:.1f}")
        disp["pe_ratio"] = disp["pe_ratio"].map(lambda x: f"{x:.1f}x")
        disp["ev_ebitda"] = disp["ev_ebitda"].map(lambda x: f"{x:.1f}x")
        disp["roe"] = disp["roe"].map(lambda x: f"{x*100:.1f}%")
        disp["operating_margin"] = disp["operating_margin"].map(lambda x: f"{x*100:.1f}%")
        disp["debt_to_equity"] = disp["debt_to_equity"].map(lambda x: f"{x:.0f}%")
        disp["weight"] = disp["weight"].map(lambda x: f"{x*100:.2f}%")
        print(disp.to_string(index=False))

    # Plot Cumulative Equity Curve & Drawdowns
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [2.4, 1.2]})
    colors = {"My Strategy": "#e31a1c", "FTSE MIB TR (Gross Dividends)": "#111111"}

    for col, lw, ls in [("My Strategy", 2.8, "-"), ("FTSE MIB TR (Gross Dividends)", 2.2, "--")]:
        s = nav_df[col]
        tot = (s.iloc[-1] / s.iloc[0] - 1.0) * 100.0
        cagr = ((1.0 + tot / 100.0) ** (252.0 / len(s)) - 1.0) * 100.0
        r = s.pct_change().dropna()
        sharpe = (r.mean() * 252.0 - config.RISK_FREE_RATE) / (r.std() * np.sqrt(252.0))
        ax1.plot(s.index, s, label=f"{col} (CAGR: +{cagr:.2f}% | Sharpe: {sharpe:.2f} | Total: +{tot:.1f}%)", color=colors[col], linewidth=lw, linestyle=ls)

        peak = s.cummax()
        dd = (s - peak) / peak * 100.0
        ax2.plot(dd.index, dd, label=f"{col} (MDD: {dd.min():.1f}%)", color=colors[col], linewidth=lw - 0.4, linestyle=ls)

    ax1.set_title(
        f"My Strategy ({config.PORTFOLIO_TOP_N} Stocks, Cap <= €{config.MARKET_CAP_THRESHOLD_EUR/1e9:.1f}B) vs. FTSE MIB Total Return (2000 - 2026)\n"
        f"Survivorship-Bias-Free Point-in-Time Universe — {prices_matrix.shape[1]} Italian Small & Mid Caps",
        fontsize=13.5,
        fontweight="bold",
    )
    ax1.set_ylabel("Portfolio Value (Base = 100)", fontsize=12)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=11)

    ax2.set_title("Historical Drawdown (%)", fontsize=12, fontweight="bold")
    ax2.set_xlabel("Date", fontsize=12)
    ax2.set_ylabel("Drawdown (%)", fontsize=12)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="lower left", frameon=True, fontsize=10.5)

    plt.tight_layout()
    out_chart = config.REPORTS_DIR / "strategy_performance.png"
    plt.savefig(out_chart, dpi=300)
    plt.close()
    print(f"\nPerformance chart saved to: {out_chart}")


if __name__ == "__main__":
    main()
