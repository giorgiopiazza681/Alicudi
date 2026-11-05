"""Script 04: Compute and Plot Multi-Horizon Rolling Returns (1-Year and 5-Year) in English.

Evaluates My Strategy (15 Stocks, Cap <= €1.0B) vs. FTSE MIB TR (Gross Dividends) across:
- 1-Year Rolling Windows (252 trading days)
- 5-Year Rolling Windows (1,260 trading days, annualized CAGR)

Outputs saved to `reports/`:
- `rolling_returns_1y.csv`, `rolling_returns_1y_trajectory.png`, `rolling_returns_1y_distribution.png`
- `rolling_returns_5y.csv`, `rolling_returns_5y_trajectory.png`, `rolling_returns_5y_distribution.png`

Usage:
    python scripts/04_plot_rolling_returns.py
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

import config
from src.backtest_engine import BacktestEngine
from src.fundamental_engine import FundamentalEngine, QualityValueModel


def load_or_compute_nav() -> pd.DataFrame:
    """Loads cached daily NAV series from `strategy_nav.parquet`, or runs the backtest if missing."""
    proc_dir = config.PROCESSED_DIR
    nav_path = proc_dir / "strategy_nav.parquet"
    if nav_path.exists():
        return pd.read_parquet(nav_path)

    prices_matrix = pd.read_parquet(proc_dir / "prices_matrix.parquet")
    returns_matrix = pd.read_parquet(proc_dir / "returns_matrix.parquet")
    benchmark_df = pd.read_parquet(proc_dir / "benchmark_returns.parquet")
    bench_tr = benchmark_df["FTSEMIB_TR"] if "FTSEMIB_TR" in benchmark_df.columns else benchmark_df.iloc[:, 0]

    pit_data = FundamentalEngine().load_or_build_pit_matrices(prices_matrix, returns_matrix)
    res = BacktestEngine().run(
        model=QualityValueModel(pit_data=pit_data),
        strategy_name="My Strategy",
        returns_matrix=returns_matrix,
        prices_matrix=prices_matrix,
        min_assets=10,
    )
    bench_sub = bench_tr.reindex(res.nav_series.index).fillna(0.0)
    nav_df = pd.DataFrame({
        "My Strategy": res.nav_series,
        "FTSE MIB TR (Gross Dividends)": (1.0 + bench_sub).cumprod() * 100.0,
    }).dropna()
    nav_df.to_parquet(nav_path)
    return nav_df


def analyze_and_plot_rolling_horizon(strat_nav: pd.Series, bench_nav: pd.Series, years: int) -> None:
    """Computes rolling returns for `years` (252 * years trading days) and saves English charts + CSV."""
    window = years * 252
    suffix = "/yr" if years > 1 else ""
    metric_label = f"{years}-Year Rolling Annualized Return (% CAGR)" if years > 1 else "1-Year Rolling Return (%)"

    # Total and annualized rolling returns
    tot_s = (strat_nav / strat_nav.shift(window) - 1.0).dropna() * 100.0
    tot_b = (bench_nav / bench_nav.shift(window) - 1.0).dropna() * 100.0
    common_idx = tot_s.index.intersection(tot_b.index)
    tot_s, tot_b = tot_s.loc[common_idx], tot_b.loc[common_idx]

    if years > 1:
        roll_s = ((strat_nav / strat_nav.shift(window)).loc[common_idx] ** (1.0 / years) - 1.0) * 100.0
        roll_b = ((bench_nav / bench_nav.shift(window)).loc[common_idx] ** (1.0 / years) - 1.0) * 100.0
    else:
        roll_s, roll_b = tot_s, tot_b

    spread = roll_s - roll_b
    win_rate = float((spread > 0).mean() * 100.0)
    pos_s = float((roll_s > 0).mean() * 100.0)
    pos_b = float((roll_b > 0).mean() * 100.0)
    mean_s, mean_b, mean_sp = float(roll_s.mean()), float(roll_b.mean()), float(spread.mean())
    start_yr, end_yr = common_idx[0].year, common_idx[-1].year

    print("=" * 88)
    print(f"{years}-YEAR ROLLING RETURNS ({window:,} TRADING DAYS, {start_yr} - {end_yr})")
    print("=" * 88)
    print(f"Rolling windows analyzed: {len(common_idx):,} | Win Rate vs FTSE MIB TR: {win_rate:.1f}%")
    print(f"My Strategy Mean:         {mean_s:+.2f}%{suffix} (Median: {roll_s.median():+.2f}%{suffix} | Positive: {pos_s:.1f}%)")
    print(f"FTSE MIB TR Mean:         {mean_b:+.2f}%{suffix} (Median: {roll_b.median():+.2f}%{suffix} | Positive: {pos_b:.1f}%)")
    print(f"Mean Alpha Spread:        {mean_sp:+.2f}%{suffix} (Median: {spread.median():+.2f}%{suffix})")

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_df = pd.DataFrame({
        f"My_Strategy_{years}Y_Pct": roll_s,
        f"FTSEMIB_TR_{years}Y_Pct": roll_b,
        f"Excess_Return_{years}Y_Pct": spread,
    })
    if years > 1:
        out_df[f"My_Strategy_{years}Y_Total_Pct"] = tot_s
        out_df[f"FTSEMIB_TR_{years}Y_Total_Pct"] = tot_b
    out_df.to_csv(config.REPORTS_DIR / f"rolling_returns_{years}y.csv")

    # 1. Trajectory & Excess Spread Chart
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10), sharex=True, gridspec_kw={"height_ratios": [1.8, 1.2]})
    ax1.axhline(0.0, color="#444444", linewidth=1.0, alpha=0.7)
    ax1.plot(roll_b.index, roll_b.values, label=f"FTSE MIB TR (Gross Dividends) (Mean: {mean_b:+.2f}%{suffix} | Positive Windows: {pos_b:.1f}%)", color="#2b2b2b", linewidth=1.6, linestyle="--", alpha=0.85)
    ax1.plot(roll_s.index, roll_s.values, label=f"My Strategy (Mean: {mean_s:+.2f}%{suffix} | Positive Windows: {pos_s:.1f}%)", color="#e31a1c", linewidth=2.2)
    ax1.set_title(f"{years}-Year Rolling Returns ({window:,} Trading Days): My Strategy vs. FTSE MIB Total Return ({start_yr} - {end_yr})", fontsize=13.5, fontweight="bold", pad=10)
    ax1.set_ylabel(metric_label, fontsize=11.5)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=10.5)

    ax2.axhline(0.0, color="#222222", linewidth=1.1)
    ax2.axhline(mean_sp, color="#006d2c", linewidth=1.2, linestyle="--", label=f"{years}Y Mean Alpha Spread: {mean_sp:+.2f}%{suffix}")
    ax2.plot(spread.index, spread.values, color="#1f78b4", linewidth=1.3, alpha=0.9)
    ax2.fill_between(spread.index, spread.values, 0.0, where=(spread.values >= 0.0), color="#2ca02c", alpha=0.35, interpolate=True, label=f"My Strategy beats FTSE MIB TR ({win_rate:.1f}% of {years}Y windows)")
    ax2.fill_between(spread.index, spread.values, 0.0, where=(spread.values < 0.0), color="#d62728", alpha=0.30, interpolate=True, label=f"FTSE MIB TR beats My Strategy ({100.0 - win_rate:.1f}% of {years}Y windows)")
    ax2.set_title(f"{years}-Year Rolling Excess Return (My Strategy minus FTSE MIB TR) — Win Rate: {win_rate:.1f}%", fontsize=12.5, fontweight="bold")
    ax2.set_xlabel("Date", fontsize=11.5)
    ax2.set_ylabel(f"{years}Y Rolling Spread (%{suffix})", fontsize=11.5)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="upper left", frameon=True, fontsize=10)

    plt.tight_layout()
    plt.savefig(config.REPORTS_DIR / f"rolling_returns_{years}y_trajectory.png", dpi=300)
    plt.close()

    # 2. Probability Distribution (Histogram + KDE + Boxplot)
    fig2, (ax_hist, ax_box) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [2.2, 1.0]})
    pad = 8.0 if years == 1 else 4.0
    x_grid = np.linspace(min(roll_s.min(), roll_b.min()) - pad, max(roll_s.max(), roll_b.max()) + pad, 600)
    bins = np.linspace(min(roll_s.min(), roll_b.min()) - 2.0, max(roll_s.max(), roll_b.max()) + 2.0, 50)

    ax_hist.hist(roll_b.values, bins=bins, density=True, color="#4d4d4d", alpha=0.30, edgecolor="#2b2b2b", linewidth=0.5, label=f"FTSE MIB TR (Mean: {mean_b:+.2f}%{suffix} | Median: {roll_b.median():+.2f}%{suffix} | Std: {roll_b.std():.1f}%{suffix})")
    ax_hist.hist(roll_s.values, bins=bins, density=True, color="#e31a1c", alpha=0.38, edgecolor="#99000d", linewidth=0.5, label=f"My Strategy (Mean: {mean_s:+.2f}%{suffix} | Median: {roll_s.median():+.2f}%{suffix} | Std: {roll_s.std():.1f}%{suffix})")
    ax_hist.plot(x_grid, gaussian_kde(roll_b.values, bw_method=0.22)(x_grid), color="#1a1a1a", linewidth=2.2, linestyle="--")
    ax_hist.plot(x_grid, gaussian_kde(roll_s.values, bw_method=0.22)(x_grid), color="#cb181d", linewidth=2.6, linestyle="-")

    p5_s, p5_b = float(np.percentile(roll_s.values, 5)), float(np.percentile(roll_b.values, 5))
    ax_hist.axvline(0.0, color="#111111", linewidth=1.3, alpha=0.8, label=f"0%{suffix} Breakeven Threshold")
    ax_hist.axvline(mean_b, color="#2b2b2b", linewidth=1.8, linestyle=":", label=f"Mean FTSE MIB TR ({mean_b:+.2f}%{suffix})")
    ax_hist.axvline(mean_s, color="#e31a1c", linewidth=2.0, linestyle=":", label=f"Mean My Strategy ({mean_s:+.2f}%{suffix})")
    ax_hist.axvline(p5_b, color="#636363", linewidth=1.4, linestyle="-.", label=f"5th Percentile ({years}Y 95% VaR) FTSE MIB TR ({p5_b:+.1f}%{suffix})")
    ax_hist.axvline(p5_s, color="#a50f15", linewidth=1.5, linestyle="-.", label=f"5th Percentile ({years}Y 95% VaR) My Strategy ({p5_s:+.1f}%{suffix})")

    ax_hist.set_title(f"Probability Distribution of {years}-Year Rolling Returns ({len(common_idx):,} Windows, {start_yr} - {end_yr})\nMy Strategy vs. FTSE MIB Total Return (Gross Dividends)", fontsize=13.5, fontweight="bold", pad=10)
    ax_hist.set_ylabel("Probability Density", fontsize=11.5)
    ax_hist.grid(True, linestyle=":", alpha=0.6)
    ax_hist.legend(loc="upper right" if years == 1 else "upper left", frameon=True, fontsize=9.8)

    bp = ax_box.boxplot(
        [roll_b.values, roll_s.values],
        vert=False,
        widths=0.48,
        patch_artist=True,
        showmeans=True,
        meanline=True,
        flierprops={"marker": ".", "markersize": 2.5, "alpha": 0.25},
        medianprops={"color": "#111111", "linewidth": 2.2},
        meanprops={"color": "#00441b", "linewidth": 2.0, "linestyle": "--"},
    )
    for patch, c in zip(bp["boxes"], ["#878787", "#fb6a4a"]):
        patch.set_facecolor(c)
        patch.set_alpha(0.65)

    ax_box.axvline(0.0, color="#111111", linewidth=1.2, alpha=0.8)
    ax_box.set_yticks([1, 2])
    ax_box.set_yticklabels(["FTSE MIB TR\n(Gross Dividends)", "My Strategy"], fontsize=11, fontweight="bold")
    ax_box.set_title("Boxplot & Quantile Comparison (Box = 25th–75th Percentile | Black Line = Median | Green Dashed = Mean)", fontsize=11.5, fontweight="bold")
    ax_box.set_xlabel(metric_label, fontsize=11.5)
    ax_box.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    plt.savefig(config.REPORTS_DIR / f"rolling_returns_{years}y_distribution.png", dpi=300)
    plt.close()


def main():
    nav_df = load_or_compute_nav()
    strat_nav = nav_df["My Strategy"]
    bench_nav = nav_df["FTSE MIB TR (Gross Dividends)"]

    for horizon_years in (1, 5):
        analyze_and_plot_rolling_horizon(strat_nav, bench_nav, years=horizon_years)


if __name__ == "__main__":
    main()
