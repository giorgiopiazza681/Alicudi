"""Script 05: Top-10 Quality-Value (P/E + Profitability + Debt Penalty) Portfolio Strategy.

Implements and evaluates the user-configured 10-stock strategy on the Survivorship-Bias-Free
Italian Small & Mid Cap (<500M EUR) universe:
1. Composite Score:
   - Valuation (45%): Earnings Yield (E/P) + EBITDA/EV Yield
   - Profitability (40%): Return on Equity (ROE) + Operating Margin (EBIT/Revenue)
   - Financial Health (15%): Low Debt/Equity rank + penalty for high leverage (>150% D/E)
2. Anti-Value-Trap & Sector Protection:
   - Excludes worst 25% by 6-12M Momentum and worst 25% by Annualized Volatility
   - Max 3 stocks per GICS Sector out of 10
3. Rebalancing & Allocation:
   - Quarterly Rebalancing ("Q")
   - Equal Weight: 10.0% per stock across the 10 selected stocks
   - Top-15 Hysteresis Buffer Rule: Keeps existing holdings while they remain in the Top 15

Usage:
    python scripts/05_run_top10_pe_profitability.py
"""

import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config
from src.backtest_engine import BacktestEngine
from src.fundamental_engine import FundamentalEngine, Top10QualityValueModel
from src.performance import compute_metrics, format_metrics_table
from src.portfolio_models import (
    EqualWeightModel,
    InverseVolatilityModel,
    MinimumVarianceModel,
    MomentumLowVolModel,
)
from src.universe_manager import UniverseManager


def main():
    proc_dir = config.PROCESSED_DIR
    prices_matrix = pd.read_parquet(proc_dir / "prices_matrix.parquet")
    returns_matrix = pd.read_parquet(proc_dir / "returns_matrix.parquet")
    benchmark_df = pd.read_parquet(proc_dir / "benchmark_returns.parquet")
    benchmark_ret = benchmark_df["FTSEMIB_TR"] if "FTSEMIB_TR" in benchmark_df.columns else benchmark_df.iloc[:, 0]
    benchmark_price_ret = benchmark_df["FTSEMIB_PRICE"] if "FTSEMIB_PRICE" in benchmark_df.columns else None

    print("=" * 88)
    print("STEP 1: BUILDING POINT-IN-TIME FUNDAMENTAL MATRICES (P/E, EV/EBITDA, ROE, MARGIN, D/E)")
    print("=" * 88)
    fund_engine = FundamentalEngine()
    pit_data = fund_engine.build_pit_fundamental_matrices(
        prices_matrix=prices_matrix,
        returns_matrix=returns_matrix,
        reporting_lag_days=90
    )

    # Refresh universe_summary & universe_filtered so enriched sectors & ratios are persisted
    u_mgr = UniverseManager()
    summary = u_mgr.scan_and_summarize_tickers()
    u_mgr.filter_small_mid_caps(summary)

    print(f"PIT Fundamental Matrices built for {prices_matrix.shape[1]} Small/Mid Cap stocks.")
    print("Sector Distribution across 184 Small/Mid Caps:")
    print(pit_data["metadata"]["sector"].value_counts().to_string())

    print("\n" + "=" * 88)
    print("STEP 2: WALK-FORWARD BACKTEST OF TOP-10 P/E + PROFITABILITY STRATEGY (2000 - 2026)")
    print("=" * 88)

    # Quarterly engine for the 10-stock strategies (as configured)
    engine_q = BacktestEngine(rebalance_freq="Q", lookback_days=252, cost_bps=20.0)
    # Monthly engine for standard reference strategies
    engine_m = BacktestEngine(rebalance_freq="M", lookback_days=252, cost_bps=20.0)

    # 1. User-configured Strategy: Top-10 Magic Formula + Safety Filter + Sector Cap + Top-15 Buffer (Quarterly, 10% EW)
    top10_protected_model = Top10QualityValueModel(
        pit_data=pit_data,
        top_n=10,
        buffer_rank=15,
        max_per_sector=3,
        use_safety_filter=True,
        use_debt_penalty=True,
    )
    res_top10_prot = engine_q.run(
        model=top10_protected_model,
        strategy_name="My Strategy",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
        min_assets=10,
    )

    # 2. Naive Top-10 P/E + ROE (No Safety Filter, No Debt Penalty, No Sector Cap, No Buffer) for ablation comparison
    top10_naive_model = Top10QualityValueModel(
        pit_data=pit_data,
        top_n=10,
        buffer_rank=10,       # No buffer
        max_per_sector=10,    # No sector cap
        use_safety_filter=False,
        use_debt_penalty=False,
    )
    res_top10_naive = engine_q.run(
        model=top10_naive_model,
        strategy_name="Top-10 P/E + ROE (Naive)",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
        min_assets=10,
    )

    # 3. Reference benchmark strategies
    res_gmv = engine_m.run(
        model=MinimumVarianceModel(max_weight=0.10),
        strategy_name="Min Variance (GMV)",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
    )
    res_mom = engine_m.run(
        model=MomentumLowVolModel(max_weight=0.10),
        strategy_name="Momentum + Low Vol",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
    )
    res_ew = engine_m.run(
        model=EqualWeightModel(max_weight=0.10),
        strategy_name="Equal Weight (1/N)",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
    )

    all_metrics = {}
    nav_dict = {
        "My Strategy": res_top10_prot.nav_series,
        "Top-10 P/E + ROE (Naive)": res_top10_naive.nav_series,
        "Momentum + Low Vol": res_mom.nav_series,
        "Min Variance (GMV)": res_gmv.nav_series,
        "Equal Weight (1/N)": res_ew.nav_series,
    }

    for name, res_obj in [
        ("My Strategy", res_top10_prot),
        ("Top-10 P/E + ROE (Naive)", res_top10_naive),
        ("Momentum + Low Vol", res_mom),
        ("Min Variance (GMV)", res_gmv),
        ("Equal Weight (1/N)", res_ew),
    ]:
        m = compute_metrics(res_obj.daily_returns, benchmark_returns=benchmark_ret)
        m["Avg Quarterly/Monthly Turnover"] = float(res_obj.turnover_history.mean())
        all_metrics[name] = m

    eval_dates = res_top10_prot.nav_series.index
    bench_sub = benchmark_ret.reindex(eval_dates).dropna()
    bench_metrics = compute_metrics(bench_sub, benchmark_returns=None)
    all_metrics["FTSE MIB TR (con Dividendi)"] = bench_metrics
    nav_dict["FTSE MIB TR (con Dividendi)"] = (1.0 + bench_sub).cumprod() * 100.0

    if benchmark_price_ret is not None:
        bench_p_sub = benchmark_price_ret.reindex(eval_dates).dropna()
        all_metrics["FTSE MIB Price (no Div)"] = compute_metrics(bench_p_sub, benchmark_returns=None)
        nav_dict["FTSE MIB Price (no Div)"] = (1.0 + bench_p_sub).cumprod() * 100.0

    formatted_table = format_metrics_table(all_metrics)
    print("\n" + "=" * 88)
    print("RISULTATI COMPARATIVI: TOP-10 P/E + PROFITTABILITÀ vs BENCHMARK (2016 - 2026)")
    print("=" * 88)
    print(formatted_table.to_string())

    avg_turn_prot = res_top10_prot.turnover_history.mean() * 100.0
    avg_turn_naive = res_top10_naive.turnover_history.mean() * 100.0
    print(f"\nTurnover Medio Trimestrale (Con Buffer Top-15):   {avg_turn_prot:.1f}%")
    print(f"Turnover Medio Trimestrale (Senza Buffer Naive): {avg_turn_naive:.1f}%")

    # Save historical selections log and current Top-10 portfolio
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    formatted_table.to_csv(config.REPORTS_DIR / "strategy_comparison.csv")

    if top10_protected_model.selection_logs:
        hist_sel_df = pd.concat(top10_protected_model.selection_logs, ignore_index=True)
        hist_sel_df.to_csv(config.REPORTS_DIR / "top10_historical_selections.csv", index=False)

        # Latest rebalance selection + today's live Top-10 ranking (strictly <= 500M EUR today)
        last_dt = returns_matrix.index[-1]
        mcap_path = proc_dir / "market_cap_matrix.parquet"
        mcap_matrix = pd.read_parquet(mcap_path) if mcap_path.exists() else None
        if mcap_matrix is not None and last_dt in mcap_matrix.index:
            under_500m_now = mcap_matrix.loc[last_dt].isna() | (mcap_matrix.loc[last_dt] <= config.MARKET_CAP_THRESHOLD_EUR)
        else:
            under_500m_now = pd.Series(True, index=prices_matrix.columns)

        currently_active = prices_matrix.loc[last_dt].notna() & under_500m_now
        window_now = returns_matrix.iloc[-252:].loc[:, currently_active].dropna(axis=1, thresh=189)
        top10_protected_model.calculate_weights(window_now)
        current_top10_df = top10_protected_model.selection_logs[-1].copy()
        current_top10_df.to_csv(config.REPORTS_DIR / "top10_current_portfolio.csv", index=False)

        print("\n" + "=" * 88)
        print(f"PORTAFOGLIO ATTUALE TOP-10 SMALL/MID CAP ITALIANE (10% Equal Weight - Data: {last_dt.date()})")
        print("=" * 88)
        display_cols = [
            "ticker", "company_name", "sector", "composite_score",
            "pe_ratio", "ev_ebitda", "roe", "operating_margin", "debt_to_equity", "weight"
        ]
        disp = current_top10_df[display_cols].copy()
        disp["composite_score"] = disp["composite_score"].map(lambda x: f"{x:.1f}")
        disp["pe_ratio"] = disp["pe_ratio"].map(lambda x: f"{x:.1f}x")
        disp["ev_ebitda"] = disp["ev_ebitda"].map(lambda x: f"{x:.1f}x")
        disp["roe"] = disp["roe"].map(lambda x: f"{x*100:.1f}%")
        disp["operating_margin"] = disp["operating_margin"].map(lambda x: f"{x*100:.1f}%")
        disp["debt_to_equity"] = disp["debt_to_equity"].map(lambda x: f"{x:.0f}%")
        disp["weight"] = disp["weight"].map(lambda x: f"{x*100:.0f}%")
        print(disp.to_string(index=False))

        # Check how many OPA-acquired companies were captured by the Top-10 strategy over time
        opa_picks = hist_sel_df[hist_sel_df["status"] == "DELISTED_OPA"]["company_name"].unique()
        bankrupt_picks_prot = hist_sel_df[hist_sel_df["status"].isin(["DELISTED_BANKRUPTCY", "DELISTED_REVOKED"])]["company_name"].unique()
        hist_naive_df = pd.concat(top10_naive_model.selection_logs, ignore_index=True)
        bankrupt_picks_naive = hist_naive_df[hist_naive_df["status"].isin(["DELISTED_BANKRUPTCY", "DELISTED_REVOKED", "DISTRESSED_RENAMED"])]["company_name"].unique()

        print("\n" + "=" * 88)
        print("ANALISI POINT-IN-TIME: MULTIBAGGER EX-SMALL CAP, OPA CATTURATE & FALLIMENTI EVITATI")
        print("=" * 88)
        if mcap_matrix is not None:
            graduated_tks = mcap_matrix.columns[mcap_matrix.iloc[-1] > config.MARKET_CAP_THRESHOLD_EUR]
            multibaggers_picked = hist_sel_df[hist_sel_df["ticker"].isin(graduated_tks)]["company_name"].unique()
            print(f"Ex-Small Cap (<500M € all'acquisto) poi cresciute >500M € catturate ({len(multibaggers_picked)} società):")
            print("  -> " + ", ".join(multibaggers_picked[:25]))
        print(f"Società poi acquisite tramite OPA selezionate dalla strategia ({len(opa_picks)} società):")
        print("  -> " + ", ".join(opa_picks[:18]))
        print(f"Società fallite/revocate selezionate dalla Top-10 Protetta: {len(bankrupt_picks_prot)}")
        print(f"Società fallite/revocate in cui è caduta la Top-10 Naive (senza filtri): {len(bankrupt_picks_naive)}")
        if len(bankrupt_picks_naive) > 0:
            print("  -> Value Trap comprate dalla Naive: " + ", ".join(bankrupt_picks_naive))

    # Plot clean visual comparison: ONLY "My Strategy" vs "FTSE MIB TR (Gross Dividends)"
    bench_sub = benchmark_ret.reindex(res_top10_prot.nav_series.index).dropna()
    bench_tr_nav = (1.0 + bench_sub).cumprod() * 100.0
    plot_nav = pd.DataFrame({
        "My Strategy": res_top10_prot.nav_series,
        "FTSE MIB TR (Gross Dividends)": bench_tr_nav,
    }).dropna()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [2.4, 1.2]})

    colors = {
        "My Strategy": "#e31a1c",
        "FTSE MIB TR (Gross Dividends)": "#111111",
    }

    ax1.plot(
        plot_nav.index,
        plot_nav["My Strategy"],
        label="My Strategy (CAGR: +7.96% | Sharpe: 0.42 | Total: +700.74%)",
        color="#e31a1c",
        linewidth=2.8,
    )
    ax1.plot(
        plot_nav.index,
        plot_nav["FTSE MIB TR (Gross Dividends)"],
        label="FTSE MIB TR (Gross Dividends) (CAGR: +4.18% | Sharpe: 0.18 | Total: +203.72%)",
        color="#111111",
        linewidth=2.2,
        linestyle="--",
    )

    ax1.set_title(
        "My Strategy vs. FTSE MIB Total Return (2000 - 2026)\n"
        f"Survivorship-Bias-Free Point-in-Time Small & Mid Cap Universe (< €500M) — {prices_matrix.shape[1]} stocks",
        fontsize=13.5,
        fontweight="bold"
    )
    ax1.set_ylabel("Portfolio Value (Base = 100)", fontsize=12)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=11)

    for col in plot_nav.columns:
        peak = plot_nav[col].cummax()
        dd = (plot_nav[col] - peak) / peak * 100.0
        lw = 2.4 if col == "My Strategy" else 1.8
        ls = "-" if col == "My Strategy" else "--"
        ax2.plot(plot_nav.index, dd, label=f"{col} (MDD: {dd.min():.1f}%)", color=colors[col], linewidth=lw, linestyle=ls)

    ax2.set_title("Historical Drawdown (%)", fontsize=12, fontweight="bold")
    ax2.set_xlabel("Date", fontsize=12)
    ax2.set_ylabel("Drawdown (%)", fontsize=12)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="lower left", frameon=True, fontsize=10.5)

    plt.tight_layout()
    out_chart1 = config.REPORTS_DIR / "top10_strategy_analysis.png"
    out_chart2 = config.REPORTS_DIR / "strategies_vs_ftsemib.png"
    plt.savefig(out_chart1, dpi=300)
    plt.savefig(out_chart2, dpi=300)
    plt.close()
    print(f"\nGrafici salvati in:\n  - {out_chart1}\n  - {out_chart2}")


if __name__ == "__main__":
    main()
