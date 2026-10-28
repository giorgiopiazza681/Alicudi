"""Script 03: Execute Quantitative Portfolio Strategies and compare vs FTSE MIB.

Evaluates:
1. Equal Weight (1/N)
2. Inverse Volatility (Low Volatility Anomaly)
3. Global Minimum Variance (GMV)
4. Risk Parity (Equal Risk Contribution)
5. Momentum Quintile + Low Volatility
6. Benchmark: FTSE MIB

Usage:
    python scripts/03_run_strategies.py [--rebalance M] [--cost-bps 20] [--lookback 252]
"""

import argparse
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from src.backtest_engine import BacktestEngine
from src.performance import compute_metrics, format_metrics_table
from src.portfolio_models import (
    EqualWeightModel,
    InverseVolatilityModel,
    MinimumVarianceModel,
    MomentumLowVolModel,
    RiskParityModel,
)


def main():
    parser = argparse.ArgumentParser(description="Run portfolio construction strategies on Italian Small/Mid Caps.")
    parser.add_argument("--rebalance", type=str, default="M", choices=["M", "Q", "Y"], help="Rebalance frequency (M/Q/Y).")
    parser.add_argument("--cost-bps", type=float, default=20.0, help="Transaction cost in basis points (default: 20 bps = 0.20%).")
    parser.add_argument("--lookback", type=int, default=252, help="Covariance/momentum lookback days (default: 252).")
    parser.add_argument("--max-weight", type=float, default=0.10, help="Max weight per stock (default: 0.10 = 10%).")
    args = parser.parse_args()

    # Load matrices
    proc_dir = config.PROCESSED_DIR
    prices_path = proc_dir / "prices_matrix.parquet"
    returns_path = proc_dir / "returns_matrix.parquet"
    bench_path = proc_dir / "benchmark_returns.parquet"

    if not prices_path.exists() or not returns_path.exists():
        print("Processed matrices not found. Please run scripts/02_prepare_dataset.py first.")
        sys.exit(1)

    prices_matrix = pd.read_parquet(prices_path)
    returns_matrix = pd.read_parquet(returns_path)

    benchmark_ret = None
    if bench_path.exists():
        benchmark_df = pd.read_parquet(bench_path)
        benchmark_ret = benchmark_df.iloc[:, 0]

    print("=" * 80)
    print("RUNNING QUANTITATIVE PORTFOLIO STRATEGIES ON ITALIAN SMALL/MID CAPS")
    print(f"Universe: {returns_matrix.shape[1]} stocks | Period: {returns_matrix.index[0].date()} to {returns_matrix.index[-1].date()}")
    print(f"Rebalance: {args.rebalance} | Lookback: {args.lookback} days | Costs: {args.cost_bps} bps | Max Weight: {args.max_weight:.0%}")
    print("=" * 80)

    engine = BacktestEngine(
        rebalance_freq=args.rebalance,
        lookback_days=args.lookback,
        cost_bps=args.cost_bps
    )

    models = [
        ("Equal Weight (1/N)", EqualWeightModel(max_weight=args.max_weight)),
        ("Inverse Volatility", InverseVolatilityModel(max_weight=args.max_weight)),
        ("Min Variance (GMV)", MinimumVarianceModel(max_weight=args.max_weight)),
        ("Risk Parity (ERC)", RiskParityModel(max_weight=args.max_weight)),
        ("Momentum + Low Vol", MomentumLowVolModel(max_weight=args.max_weight))
    ]

    all_metrics = {}
    nav_series_dict = {}

    for name, model in models:
        print(f"Simulating: {name}...")
        res = engine.run(
            model=model,
            strategy_name=name,
            returns_matrix=returns_matrix,
            prices_matrix=prices_matrix
        )
        nav_series_dict[name] = res.nav_series
        metrics = compute_metrics(res.daily_returns, benchmark_returns=benchmark_ret)
        all_metrics[name] = metrics

    # Also compute FTSE MIB benchmark metrics over the exact same evaluation period
    if benchmark_ret is not None and nav_series_dict:
        sample_nav = next(iter(nav_series_dict.values()))
        eval_dates = sample_nav.index
        bench_sub = benchmark_ret.reindex(eval_dates).dropna()
        bench_metrics = compute_metrics(bench_sub, benchmark_returns=None)
        all_metrics["FTSE MIB (Benchmark)"] = bench_metrics

    # Format and present summary table
    formatted_table = format_metrics_table(all_metrics)

    print("\n" + "=" * 80)
    print("PERFORMANCE & RISK COMPARISON vs FTSE MIB")
    print("=" * 80)
    print(formatted_table.to_string())

    # Save reports
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = config.REPORTS_DIR / "strategy_comparison.csv"
    formatted_table.to_csv(report_file)
    print(f"\nReport saved to: {report_file}")


if __name__ == "__main__":
    main()
