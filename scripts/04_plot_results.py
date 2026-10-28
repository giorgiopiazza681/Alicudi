"""Script 04: Generate visual plots of portfolio equity curves, drawdowns, and risk-return comparison.

Usage:
    python scripts/04_plot_results.py
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
from src.portfolio_models import (
    EqualWeightModel,
    InverseVolatilityModel,
    MinimumVarianceModel,
    MomentumLowVolModel,
    RiskParityModel,
)


def main():
    proc_dir = config.PROCESSED_DIR
    prices_path = proc_dir / "prices_matrix.parquet"
    returns_path = proc_dir / "returns_matrix.parquet"
    bench_path = proc_dir / "benchmark_returns.parquet"

    prices_matrix = pd.read_parquet(prices_path)
    returns_matrix = pd.read_parquet(returns_path)
    benchmark_df = pd.read_parquet(bench_path)
    benchmark_ret = benchmark_df.iloc[:, 0]

    engine = BacktestEngine(rebalance_freq="M", lookback_days=252, cost_bps=20)

    models = [
        ("Min Variance (GMV)", MinimumVarianceModel(max_weight=0.10), "#2ca02c"),
        ("Momentum + Low Vol", MomentumLowVolModel(max_weight=0.10), "#1f77b4"),
        ("Inverse Volatility", InverseVolatilityModel(max_weight=0.10), "#ff7f0e"),
        ("Equal Weight (1/N)", EqualWeightModel(max_weight=0.10), "#9467bd"),
        ("Risk Parity (ERC)", RiskParityModel(max_weight=0.10), "#8c564b"),
    ]

    nav_dfs = {}
    for name, model, color in models:
        res = engine.run(model=model, strategy_name=name, returns_matrix=returns_matrix, prices_matrix=prices_matrix)
        nav_dfs[name] = res.nav_series

    # Benchmark NAV
    eval_dates = next(iter(nav_dfs.values())).index
    bench_sub = benchmark_ret.reindex(eval_dates).dropna()
    bench_nav = (1.0 + bench_sub).cumprod() * 100.0
    nav_dfs["FTSE MIB (Benchmark)"] = bench_nav

    all_nav = pd.DataFrame(nav_dfs).dropna()

    # Set up plots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [2.5, 1.2]})

    # Palette
    colors = {
        "Min Variance (GMV)": "#2ca02c",
        "Momentum + Low Vol": "#1f77b4",
        "Inverse Volatility": "#ff7f0e",
        "Equal Weight (1/N)": "#9467bd",
        "Risk Parity (ERC)": "#8c564b",
        "FTSE MIB (Benchmark)": "#d62728"
    }

    # Plot 1: Cumulative Performance (NAV)
    for col in all_nav.columns:
        lw = 2.5 if "Momentum" in col or "Min Variance" in col or "FTSE MIB" in col else 1.5
        ls = "--" if "FTSE MIB" in col else "-"
        ax1.plot(all_nav.index, all_nav[col], label=col, color=colors.get(col, "gray"), linewidth=lw, linestyle=ls)

    ax1.set_title("Italian Small/Mid Caps (<500M €) Quantitative Strategies vs FTSE MIB (2016 - 2026)", fontsize=14, fontweight="bold")
    ax1.set_ylabel("Portfolio NAV (Base = 100)", fontsize=12)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=10)

    # Plot 2: Drawdowns
    for col in all_nav.columns:
        peak = all_nav[col].cummax()
        dd = (all_nav[col] - peak) / peak * 100.0
        lw = 2.0 if "Momentum" in col or "Min Variance" in col or "FTSE MIB" in col else 1.2
        ls = "--" if "FTSE MIB" in col else "-"
        ax2.plot(all_nav.index, dd, label=col, color=colors.get(col, "gray"), linewidth=lw, linestyle=ls)

    ax2.set_title("Underwater Chart (Drawdown %)", fontsize=12, fontweight="bold")
    ax2.set_xlabel("Date", fontsize=12)
    ax2.set_ylabel("Drawdown %", fontsize=12)
    ax2.grid(True, linestyle=":", alpha=0.6)

    plt.tight_layout()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.REPORTS_DIR / "strategies_vs_ftsemib.png"
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"Chart saved successfully to: {out_path}")


if __name__ == "__main__":
    main()
