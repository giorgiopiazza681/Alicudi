"""Script 06: Plot 1-Year Rolling Returns (252 trading days) for Top-10 P/E + Profit vs FTSE MIB TR.

Generates a two-panel high-resolution chart:
1. Rolling 1-Year Total Return (%) of Top-10 P/E + Profit (Protetta) vs FTSE MIB Total Return (with Dividends).
2. Rolling 1-Year Excess Return / Outperformance (%) = Top-10 (1Y) - FTSE MIB TR (1Y), with green/red shading
   and overall win-rate statistics across all 252-day rolling windows (2000 - 2026).

Usage:
    python scripts/06_plot_rolling_returns.py
"""

import shutil
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

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

    # Load cached PIT fundamental matrices if available and shape matches, otherwise build
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

    engine_q = BacktestEngine(rebalance_freq="Q", lookback_days=252, cost_bps=20.0)
    top10_model = Top10QualityValueModel(
        pit_data=pit_data,
        top_n=10,
        buffer_rank=15,
        max_per_sector=3,
        use_safety_filter=True,
        use_debt_penalty=True,
    )
    res_top10 = engine_q.run(
        model=top10_model,
        strategy_name="My Strategy",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
        min_assets=10,
    )

    eval_dates = res_top10.nav_series.index
    top10_nav = res_top10.nav_series
    bench_sub = bench_tr.reindex(eval_dates).fillna(0.0)
    bench_nav = (1.0 + bench_sub).cumprod() * 100.0

    # Compute 1-Year (252 trading days) Rolling Returns (%)
    window = 252
    roll_top10 = (top10_nav / top10_nav.shift(window) - 1.0).dropna() * 100.0
    roll_bench = (bench_nav / bench_nav.shift(window) - 1.0).dropna() * 100.0

    common_idx = roll_top10.index.intersection(roll_bench.index)
    roll_top10 = roll_top10.loc[common_idx]
    roll_bench = roll_bench.loc[common_idx]
    excess_1y = roll_top10 - roll_bench

    # Summary statistics
    win_rate_vs_bench = float((excess_1y > 0).mean() * 100.0)
    pos_rate_top10 = float((roll_top10 > 0).mean() * 100.0)
    pos_rate_bench = float((roll_bench > 0).mean() * 100.0)
    mean_top10 = float(roll_top10.mean())
    mean_bench = float(roll_bench.mean())
    mean_excess = float(excess_1y.mean())
    median_excess = float(excess_1y.median())

    print("=" * 84)
    print("STATISTICHE ROLLING RETURNS A 1 ANNO (252 GIORNI DI BORSA, 2001 - 2026)")
    print("=" * 84)
    print(f"Numero finestre rolling 1Y analizzate:        {len(common_idx):,}")
    print(f"Rendimento Medio 1Y - My Strategy:            {mean_top10:+.2f}% ( Finestre > 0%: {pos_rate_top10:.1f}% )")
    print(f"Rendimento Medio 1Y - FTSE MIB TR (con Div):  {mean_bench:+.2f}% ( Finestre > 0%: {pos_rate_bench:.1f}% )")
    print(f"Extra-Rendimento Medio 1Y (Spread):           {mean_excess:+.2f}% ( Mediana: {median_excess:+.2f}% )")
    print(f"Hit Rate (% Finestre 1Y in cui My Strategy batte FTSE MIB TR): {win_rate_vs_bench:.1f}%")

    # Save rolling returns CSV
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    roll_df = pd.DataFrame({
        "My_Strategy_1Y_Pct": roll_top10,
        "FTSEMIB_TR_1Y_Pct": roll_bench,
        "Excess_Return_1Y_Pct": excess_1y,
    })
    roll_df.to_csv(config.REPORTS_DIR / "rolling_returns_1y.csv")

    # Plot
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(15, 10), sharex=True, gridspec_kw={"height_ratios": [1.8, 1.2]}
    )

    # Panel 1: Rolling 1Y Returns comparison
    ax1.axhline(0.0, color="#444444", linewidth=1.0, linestyle="-", alpha=0.7)
    ax1.plot(
        roll_bench.index,
        roll_bench.values,
        label=f"FTSE MIB TR (Gross Dividends) (1Y Mean: {mean_bench:+.1f}% | Positive Windows: {pos_rate_bench:.1f}%)",
        color="#2b2b2b",
        linewidth=1.6,
        linestyle="--",
        alpha=0.85,
    )
    ax1.plot(
        roll_top10.index,
        roll_top10.values,
        label=f"My Strategy (1Y Mean: {mean_top10:+.1f}% | Positive Windows: {pos_rate_top10:.1f}%)",
        color="#e31a1c",
        linewidth=2.2,
    )

    ax1.set_title(
        "1-Year Rolling Returns (252 Trading Days): My Strategy vs. FTSE MIB Total Return (2001 - 2026)",
        fontsize=13.5,
        fontweight="bold",
        pad=10,
    )
    ax1.set_ylabel("1-Year Rolling Return (%)", fontsize=11.5)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=10.5)

    # Panel 2: Rolling 1Y Excess Return (Spread = My Strategy - FTSE MIB TR)
    ax2.axhline(0.0, color="#222222", linewidth=1.1, linestyle="-")
    ax2.axhline(mean_excess, color="#006d2c", linewidth=1.2, linestyle="--", label=f"1Y Mean Spread: {mean_excess:+.2f}%/yr")
    ax2.plot(excess_1y.index, excess_1y.values, color="#1f78b4", linewidth=1.3, alpha=0.9)
    ax2.fill_between(
        excess_1y.index,
        excess_1y.values,
        0.0,
        where=(excess_1y.values >= 0.0),
        color="#2ca02c",
        alpha=0.35,
        interpolate=True,
        label=f"My Strategy beats FTSE MIB TR ({win_rate_vs_bench:.1f}% of 1Y windows)",
    )
    ax2.fill_between(
        excess_1y.index,
        excess_1y.values,
        0.0,
        where=(excess_1y.values < 0.0),
        color="#d62728",
        alpha=0.30,
        interpolate=True,
        label=f"FTSE MIB TR beats My Strategy ({100.0 - win_rate_vs_bench:.1f}% of 1Y windows)",
    )

    ax2.set_title(
        f"1-Year Rolling Excess Return (My Strategy minus FTSE MIB TR) — Win Rate: {win_rate_vs_bench:.1f}%",
        fontsize=12.5,
        fontweight="bold",
    )
    ax2.set_xlabel("Date", fontsize=11.5)
    ax2.set_ylabel("1Y Rolling Spread (%)", fontsize=11.5)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left", frameon=True, fontsize=10)

    plt.tight_layout()
    out_path = config.REPORTS_DIR / "rolling_returns_1y_top10_vs_ftsemib_tr.png"
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"\nGrafico temporale salvato in: {out_path}")

    # ==========================================================================
    # PLOT 2: DISTRIBUTION OF 1-YEAR ROLLING RETURNS (HISTOGRAM + KDE + BOXPLOT)
    # ==========================================================================
    fig2, (ax_hist, ax_box) = plt.subplots(
        2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [2.2, 1.0]}
    )

    x_grid = np.linspace(
        min(roll_top10.min(), roll_bench.min()) - 8.0,
        max(roll_top10.max(), roll_bench.max()) + 8.0,
        600,
    )
    kde_top10 = gaussian_kde(roll_top10.values, bw_method=0.22)(x_grid)
    kde_bench = gaussian_kde(roll_bench.values, bw_method=0.22)(x_grid)

    bins = np.linspace(-65, 105, 55)
    ax_hist.hist(
        roll_bench.values,
        bins=bins,
        density=True,
        color="#4d4d4d",
        alpha=0.30,
        edgecolor="#2b2b2b",
        linewidth=0.5,
        label=f"FTSE MIB TR (Gross Dividends) (Mean: {mean_bench:+.2f}% | Median: {roll_bench.median():+.2f}% | Std: {roll_bench.std():.1f}%)",
    )
    ax_hist.hist(
        roll_top10.values,
        bins=bins,
        density=True,
        color="#e31a1c",
        alpha=0.38,
        edgecolor="#99000d",
        linewidth=0.5,
        label=f"My Strategy (Mean: {mean_top10:+.2f}% | Median: {roll_top10.median():+.2f}% | Std: {roll_top10.std():.1f}%)",
    )

    ax_hist.plot(x_grid, kde_bench, color="#1a1a1a", linewidth=2.2, linestyle="--")
    ax_hist.plot(x_grid, kde_top10, color="#cb181d", linewidth=2.6, linestyle="-")

    # Vertical reference lines: 0%, Means, and 5th Percentiles (1Y VaR 95%)
    p5_top10 = float(np.percentile(roll_top10.values, 5))
    p5_bench = float(np.percentile(roll_bench.values, 5))
    p95_top10 = float(np.percentile(roll_top10.values, 95))
    p95_bench = float(np.percentile(roll_bench.values, 95))

    ax_hist.axvline(0.0, color="#111111", linewidth=1.3, linestyle="-", alpha=0.8, label="0% Threshold (1-Year Breakeven)")
    ax_hist.axvline(mean_bench, color="#2b2b2b", linewidth=1.8, linestyle=":", label=f"Mean FTSE MIB TR ({mean_bench:+.2f}%)")
    ax_hist.axvline(mean_top10, color="#e31a1c", linewidth=2.0, linestyle=":", label=f"Mean My Strategy ({mean_top10:+.2f}%)")
    ax_hist.axvline(p5_bench, color="#636363", linewidth=1.4, linestyle="-.", label=f"5th Percentile (1Y 95% VaR) FTSE MIB TR ({p5_bench:+.1f}%)")
    ax_hist.axvline(p5_top10, color="#a50f15", linewidth=1.5, linestyle="-.", label=f"5th Percentile (1Y 95% VaR) My Strategy ({p5_top10:+.1f}%)")

    ax_hist.set_title(
        "Probability Distribution of 1-Year Rolling Returns (6,595 Windows, 2001 - 2026)\n"
        "My Strategy vs. FTSE MIB Total Return (Gross Dividends)",
        fontsize=13.5,
        fontweight="bold",
        pad=10,
    )
    ax_hist.set_ylabel("Frequency Density", fontsize=11.5)
    ax_hist.grid(True, linestyle=":", alpha=0.6)
    ax_hist.legend(loc="upper right", frameon=True, fontsize=9.8)

    # Bottom Panel: Horizontal Boxplot + Quantiles Comparison
    bp = ax_box.boxplot(
        [roll_bench.values, roll_top10.values],
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
    ax_box.set_yticklabels(["FTSE MIB TR\n(Gross Dividends)", "My Strategy"], fontsize=11, fontweight="bold")
    ax_box.set_title(
        "Boxplot & Quantile Comparison (Box = 25th–75th Percentile | Black Line = Median | Green Dashed = Mean)",
        fontsize=11.5,
        fontweight="bold",
    )
    ax_box.set_xlabel("1-Year Rolling Return (%)", fontsize=11.5)
    ax_box.grid(True, linestyle=":", alpha=0.6)

    # Print quantile table
    print("\n" + "=" * 84)
    print("DISTRIBUZIONE PER QUANTILI DEI ROLLING RETURNS A 1 ANNO (2001 - 2026)")
    print("=" * 84)
    q_levels = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    for q in q_levels:
        qt = float(np.percentile(roll_top10.values, q))
        qb = float(np.percentile(roll_bench.values, q))
        print(f"Percentile {q:2d}°:  Top-10 = {qt:+6.2f}%  |  FTSE MIB TR = {qb:+6.2f}%  |  Diff = {qt - qb:+6.2f}%")

    plt.tight_layout()
    dist_path = config.REPORTS_DIR / "rolling_returns_1y_distribution.png"
    plt.savefig(dist_path, dpi=300)
    plt.close()
    print(f"\nGrafico distribuzione salvato in: {dist_path}")


if __name__ == "__main__":
    main()
