"""Script 09: Plot 5-Year Rolling Returns (1,260 trading days) for My Strategy vs FTSE MIB TR.

Generates two high-resolution English charts:
1. 5-Year Rolling Total Return (%) and Excess Return Spread (%) over time (2005 - 2026).
2. Empirical Probability Distribution (Histogram + KDE + Boxplots with Quantiles).
"""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

import config
from src.backtest_engine import BacktestEngine
from src.fundamental_engine import FundamentalEngine, Top10QualityValueModel


def main():
    proc_dir = config.PROCESSED_DIR
    pit_dir = proc_dir / "fundamentals_pit"

    prices_matrix = pd.read_parquet(proc_dir / "prices_matrix.parquet")
    returns_matrix = pd.read_parquet(proc_dir / "returns_matrix.parquet")
    benchmark_df = pd.read_parquet(proc_dir / "benchmark_returns.parquet")
    bench_tr = benchmark_df["FTSEMIB_TR"] if "FTSEMIB_TR" in benchmark_df.columns else benchmark_df.iloc[:, 0]

    # Load cached PIT fundamental matrices
    if (
        (pit_dir / "pe_matrix.parquet").exists()
        and (pit_dir / "fundamental_metadata.parquet").exists()
        and pd.read_parquet(pit_dir / "pe_matrix.parquet").shape[1] == prices_matrix.shape[1]
    ):
        pit_data = {
            "pe": pd.read_parquet(pit_dir / "pe_matrix.parquet"),
            "ev_ebitda": pd.read_parquet(pit_dir / "ev_ebitda_matrix.parquet"),
            "roe": pd.read_parquet(pit_dir / "roe_matrix.parquet"),
            "op_margin": pd.read_parquet(pit_dir / "op_margin_matrix.parquet"),
            "debt_equity": pd.read_parquet(pit_dir / "debt_equity_matrix.parquet"),
            "metadata": pd.read_parquet(pit_dir / "fundamental_metadata.parquet").set_index("ticker"),
        }
    else:
        pit_data = FundamentalEngine().build_pit_fundamental_matrices(prices_matrix, returns_matrix)

    # Official My Strategy: 15 stocks, Cap <= 1.0B, buffer 22, max 4 per sector
    engine_q = BacktestEngine(rebalance_freq="Q", lookback_days=252, cost_bps=20.0)
    strategy_model = Top10QualityValueModel(
        pit_data=pit_data,
        top_n=15,
        buffer_rank=22,
        max_per_sector=4,
        use_safety_filter=True,
        use_debt_penalty=True,
    )
    res_strat = engine_q.run(
        model=strategy_model,
        strategy_name="My Strategy",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
        min_assets=10,
    )

    eval_dates = res_strat.nav_series.index
    strat_nav = res_strat.nav_series
    bench_sub = bench_tr.reindex(eval_dates).fillna(0.0)
    bench_nav = (1.0 + bench_sub).cumprod() * 100.0

    # Compute 5-Year (1,260 trading days) Rolling Returns (%)
    window_5y = 1260  # 5 years * 252 trading days
    roll_strat_tot = (strat_nav / strat_nav.shift(window_5y) - 1.0).dropna() * 100.0
    roll_bench_tot = (bench_nav / bench_nav.shift(window_5y) - 1.0).dropna() * 100.0

    # Annualized 5-Year Rolling Returns (CAGR % per year)
    roll_strat_cagr = (((1.0 + roll_strat_tot / 100.0) ** (1.0 / 5.0)) - 1.0) * 100.0
    roll_bench_cagr = (((1.0 + roll_bench_tot / 100.0) ** (1.0 / 5.0)) - 1.0) * 100.0

    common_idx = roll_strat_tot.index.intersection(roll_bench_tot.index)
    roll_strat_tot = roll_strat_tot.loc[common_idx]
    roll_bench_tot = roll_bench_tot.loc[common_idx]
    roll_strat_cagr = roll_strat_cagr.loc[common_idx]
    roll_bench_cagr = roll_bench_cagr.loc[common_idx]

    excess_5y_tot = roll_strat_tot - roll_bench_tot
    excess_5y_cagr = roll_strat_cagr - roll_bench_cagr

    # Summary statistics
    win_rate_5y = float((excess_5y_tot > 0).mean() * 100.0)
    pos_rate_strat = float((roll_strat_tot > 0).mean() * 100.0)
    pos_rate_bench = float((roll_bench_tot > 0).mean() * 100.0)

    mean_strat_tot = float(roll_strat_tot.mean())
    mean_bench_tot = float(roll_bench_tot.mean())
    mean_strat_cagr = float(roll_strat_cagr.mean())
    mean_bench_cagr = float(roll_bench_cagr.mean())

    mean_excess_cagr = float(excess_5y_cagr.mean())
    median_excess_cagr = float(excess_5y_cagr.median())

    print("=" * 88)
    print("5-YEAR ROLLING RETURNS STATISTICS (1,260 TRADING DAYS, 2005 - 2026)")
    print("=" * 88)
    print(f"Number of 5Y rolling windows analyzed:      {len(common_idx):,}")
    print(f"Mean 5Y Total Return - My Strategy:         {mean_strat_tot:+.2f}% (Annualized: {mean_strat_cagr:+.2f}%/yr)")
    print(f"Mean 5Y Total Return - FTSE MIB TR:         {mean_bench_tot:+.2f}% (Annualized: {mean_bench_cagr:+.2f}%/yr)")
    print(f"Positive 5-Year Windows - My Strategy:      {pos_rate_strat:.1f}%")
    print(f"Positive 5-Year Windows - FTSE MIB TR:      {pos_rate_bench:.1f}%")
    print(f"Win Rate (% of 5Y windows My Strategy beats FTSE MIB TR): {win_rate_5y:.1f}%")
    print(f"Mean 5Y Annualized Alpha Spread:            {mean_excess_cagr:+.2f}%/yr (Median: {median_excess_cagr:+.2f}%/yr)")

    # Save rolling 5Y CSV
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    roll_5y_df = pd.DataFrame({
        "My_Strategy_5Y_Total_Pct": roll_strat_tot,
        "My_Strategy_5Y_Annualized_CAGR_Pct": roll_strat_cagr,
        "FTSEMIB_TR_5Y_Total_Pct": roll_bench_tot,
        "FTSEMIB_TR_5Y_Annualized_CAGR_Pct": roll_bench_cagr,
        "Excess_Return_5Y_Total_Pct": excess_5y_tot,
        "Excess_Return_5Y_Annualized_Pct": excess_5y_cagr,
    })
    roll_5y_csv = config.REPORTS_DIR / "rolling_returns_5y.csv"
    roll_5y_df.to_csv(roll_5y_csv)
    print(f"Saved 5Y rolling returns data to: {roll_5y_csv}")

    # =========================================================================
    # PLOT 1: TIME SERIES OF 5-YEAR ROLLING RETURNS & ALPHA SPREAD
    # =========================================================================
    fig1, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(15, 10), sharex=True, gridspec_kw={"height_ratios": [1.8, 1.2]}
    )

    # Panel 1: 5-Year Annualized CAGR (%) over time
    ax1.axhline(0.0, color="#444444", linewidth=1.0, linestyle="-", alpha=0.7)
    ax1.plot(
        roll_bench_cagr.index,
        roll_bench_cagr.values,
        label=f"FTSE MIB TR (Gross Dividends) (Mean CAGR: {mean_bench_cagr:+.1f}%/yr | Positive Windows: {pos_rate_bench:.1f}%)",
        color="#2b2b2b",
        linewidth=1.7,
        linestyle="--",
        alpha=0.85,
    )
    ax1.plot(
        roll_strat_cagr.index,
        roll_strat_cagr.values,
        label=f"My Strategy (Cap <= €1.0B, Top-15) (Mean CAGR: {mean_strat_cagr:+.1f}%/yr | Positive Windows: {pos_rate_strat:.1f}%)",
        color="#e31a1c",
        linewidth=2.4,
    )

    ax1.set_title(
        "5-Year Rolling Annualized Returns (1,260 Trading Days): My Strategy vs. FTSE MIB Total Return (2005 - 2026)",
        fontsize=13.5,
        fontweight="bold",
        pad=10,
    )
    ax1.set_ylabel("5-Year Annualized Return (CAGR %)", fontsize=11.5)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=10.5)

    # Panel 2: Rolling 5Y Annualized Excess Return Spread (My Strategy - FTSE MIB TR)
    ax2.axhline(0.0, color="#222222", linewidth=1.1, linestyle="-")
    ax2.axhline(
        mean_excess_cagr,
        color="#006d2c",
        linewidth=1.3,
        linestyle="--",
        label=f"Mean 5Y Annualized Spread: {mean_excess_cagr:+.2f}%/yr (Median: {median_excess_cagr:+.2f}%/yr)",
    )
    ax2.plot(excess_5y_cagr.index, excess_5y_cagr.values, color="#1f78b4", linewidth=1.3, alpha=0.9)
    ax2.fill_between(
        excess_5y_cagr.index,
        excess_5y_cagr.values,
        0.0,
        where=(excess_5y_cagr.values >= 0.0),
        color="#2ca02c",
        alpha=0.35,
        interpolate=True,
        label=f"My Strategy beats FTSE MIB TR ({win_rate_5y:.1f}% of 5Y windows)",
    )
    ax2.fill_between(
        excess_5y_cagr.index,
        excess_5y_cagr.values,
        0.0,
        where=(excess_5y_cagr.values < 0.0),
        color="#d62728",
        alpha=0.30,
        interpolate=True,
        label=f"FTSE MIB TR beats My Strategy ({100.0 - win_rate_5y:.1f}% of 5Y windows)",
    )

    ax2.set_title(
        f"5-Year Rolling Annualized Excess Return (My Strategy minus FTSE MIB TR) — Win Rate: {win_rate_5y:.1f}%",
        fontsize=12.5,
        fontweight="bold",
    )
    ax2.set_xlabel("Date", fontsize=11.5)
    ax2.set_ylabel("5Y Annualized Spread (%)", fontsize=11.5)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left", frameon=True, fontsize=10)

    plt.tight_layout()
    chart1_path = config.REPORTS_DIR / "rolling_returns_5y_top10_vs_ftsemib_tr.png"
    plt.savefig(chart1_path, dpi=300)
    plt.close()
    print(f"Saved 5Y rolling returns time-series chart to: {chart1_path}")

    # =========================================================================
    # PLOT 2: DISTRIBUTION OF 5-YEAR ROLLING RETURNS (HISTOGRAM + KDE + BOXPLOT)
    # =========================================================================
    fig2, (ax_hist, ax_box) = plt.subplots(
        2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [2.2, 1.0]}
    )

    x_grid = np.linspace(
        min(roll_strat_cagr.min(), roll_bench_cagr.min()) - 4.0,
        max(roll_strat_cagr.max(), roll_bench_cagr.max()) + 4.0,
        600,
    )
    kde_strat = gaussian_kde(roll_strat_cagr.values, bw_method=0.22)(x_grid)
    kde_bench = gaussian_kde(roll_bench_cagr.values, bw_method=0.22)(x_grid)

    bins = np.linspace(-15, 30, 45)
    ax_hist.hist(
        roll_bench_cagr.values,
        bins=bins,
        density=True,
        color="#4d4d4d",
        alpha=0.30,
        edgecolor="#2b2b2b",
        linewidth=0.5,
        label=f"FTSE MIB TR (Gross Dividends) (Mean: {mean_bench_cagr:+.2f}%/yr | Median: {roll_bench_cagr.median():+.2f}%/yr | Std: {roll_bench_cagr.std():.1f}%)",
    )
    ax_hist.hist(
        roll_strat_cagr.values,
        bins=bins,
        density=True,
        color="#e31a1c",
        alpha=0.38,
        edgecolor="#99000d",
        linewidth=0.5,
        label=f"My Strategy (Cap <= €1.0B, Top-15) (Mean: {mean_strat_cagr:+.2f}%/yr | Median: {roll_strat_cagr.median():+.2f}%/yr | Std: {roll_strat_cagr.std():.1f}%)",
    )

    ax_hist.plot(x_grid, kde_bench, color="#1a1a1a", linewidth=2.2, linestyle="--")
    ax_hist.plot(x_grid, kde_strat, color="#cb181d", linewidth=2.6, linestyle="-")

    p5_strat = float(np.percentile(roll_strat_cagr.values, 5))
    p5_bench = float(np.percentile(roll_bench_cagr.values, 5))
    p95_strat = float(np.percentile(roll_strat_cagr.values, 95))
    p95_bench = float(np.percentile(roll_bench_cagr.values, 95))

    ax_hist.axvline(0.0, color="#111111", linewidth=1.3, linestyle="-", alpha=0.8, label="0% Threshold (5-Year Breakeven)")
    ax_hist.axvline(mean_bench_cagr, color="#2b2b2b", linewidth=1.8, linestyle=":", label=f"Mean FTSE MIB TR ({mean_bench_cagr:+.2f}%/yr)")
    ax_hist.axvline(mean_strat_cagr, color="#e31a1c", linewidth=2.0, linestyle=":", label=f"Mean My Strategy ({mean_strat_cagr:+.2f}%/yr)")
    ax_hist.axvline(p5_bench, color="#636363", linewidth=1.4, linestyle="-.", label=f"5th Percentile (5Y VaR 95%) FTSE MIB TR ({p5_bench:+.1f}%/yr)")
    ax_hist.axvline(p5_strat, color="#a50f15", linewidth=1.5, linestyle="-.", label=f"5th Percentile (5Y VaR 95%) My Strategy ({p5_strat:+.1f}%/yr)")

    ax_hist.set_title(
        f"Probability Distribution of 5-Year Rolling Annualized Returns (5,588 Windows, 2005 - 2026)\n"
        "My Strategy (Cap <= €1.0B, Top-15) vs. FTSE MIB Total Return (Gross Dividends)",
        fontsize=13.5,
        fontweight="bold",
        pad=10,
    )
    ax_hist.set_ylabel("Frequency Density", fontsize=11.5)
    ax_hist.grid(True, linestyle=":", alpha=0.6)
    ax_hist.legend(loc="upper right", frameon=True, fontsize=9.8)

    # Bottom Panel: Horizontal Boxplot
    bp = ax_box.boxplot(
        [roll_bench_cagr.values, roll_strat_cagr.values],
        vert=False,
        widths=0.48,
        patch_artist=True,
        showmeans=True,
        meanline=True,
        flierprops={"marker": ".", "markersize": 2.5, "alpha": 0.25},
        medianprops={"color": "#111111", "linewidth": 2.2},
        meanprops={"color": "#00441b", "linewidth": 2.0, "linestyle": "--"},
    )
    box_colors = ["#878787", "#fb6a4a"]
    for patch, c in zip(bp["boxes"], box_colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.65)

    ax_box.axvline(0.0, color="#111111", linewidth=1.2, linestyle="-", alpha=0.8)
    ax_box.set_yticks([1, 2])
    ax_box.set_yticklabels(["FTSE MIB TR\n(Gross Dividends)", "My Strategy\n(Cap <= €1.0B, Top-15)"], fontsize=11, fontweight="bold")
    ax_box.set_title(
        "Boxplot & Quantile Comparison (Box = 25th–75th Percentile | Black Line = Median | Green Dashed = Mean)",
        fontsize=11.5,
        fontweight="bold",
    )
    ax_box.set_xlabel("5-Year Annualized Rolling Return (CAGR %)", fontsize=11.5)
    ax_box.grid(True, linestyle=":", alpha=0.6)

    # Print quantile table
    print("\n" + "=" * 88)
    print("5-YEAR ROLLING ANNUALIZED RETURN QUANTILE BREAKDOWN (2005 - 2026)")
    print("=" * 88)
    q_levels = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    for q in q_levels:
        qs = float(np.percentile(roll_strat_cagr.values, q))
        qb = float(np.percentile(roll_bench_cagr.values, q))
        print(f"Percentile {q:2d}th:  My Strategy = {qs:+6.2f}%/yr  |  FTSE MIB TR = {qb:+6.2f}%/yr  |  Diff = {qs - qb:+6.2f}%/yr")

    plt.tight_layout()
    chart2_path = config.REPORTS_DIR / "rolling_returns_5y_distribution.png"
    plt.savefig(chart2_path, dpi=300)
    plt.close()
    print(f"Saved 5Y distribution chart to: {chart2_path}")


if __name__ == "__main__":
    main()
