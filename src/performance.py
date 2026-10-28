"""Performance and Risk Analytics for Small/Mid Cap Strategies vs FTSE MIB Benchmark.
"""

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import config


def compute_drawdown_series(nav_series: pd.Series) -> Tuple[pd.Series, float, int]:
    """Computes drawdown time series, maximum drawdown (MDD), and max drawdown duration in days."""
    peak = nav_series.cummax()
    dd = (nav_series - peak) / peak
    mdd = float(dd.min())

    # Max duration in days
    is_zero = (dd == 0)
    streak = 0
    max_streak = 0
    for z in is_zero:
        if not z:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0

    return dd, mdd, max_streak


def compute_metrics(
    daily_returns: pd.Series,
    benchmark_returns: Optional[pd.Series] = None,
    risk_free_rate: float = config.RISK_FREE_RATE
) -> Dict[str, float]:
    """Computes full quantitative performance and risk metrics."""
    clean_rets = daily_returns.dropna()
    n_days = len(clean_rets)
    if n_days < 20:
        return {}

    # NAV
    nav = (1.0 + clean_rets).cumprod() * 100.0
    total_ret = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    years = n_days / 252.0
    cagr = float((1.0 + total_ret) ** (1.0 / max(years, 0.01)) - 1.0) if total_ret > -1.0 else -1.0

    # Volatility
    daily_vol = clean_rets.std()
    ann_vol = float(daily_vol * np.sqrt(252.0))

    # Sharpe Ratio
    rf_daily = (1.0 + risk_free_rate) ** (1.0 / 252.0) - 1.0
    excess_rets = clean_rets - rf_daily
    sharpe = float(np.sqrt(252.0) * excess_rets.mean() / daily_vol) if daily_vol > 0 else 0.0

    # Sortino Ratio
    downside_rets = clean_rets[clean_rets < rf_daily] - rf_daily
    downside_vol = float(np.sqrt((downside_rets ** 2).mean() * 252.0)) if len(downside_rets) > 0 else 0.0
    sortino = float((cagr - risk_free_rate) / downside_vol) if downside_vol > 0 else 0.0

    # Drawdown
    dd_series, mdd, max_dd_days = compute_drawdown_series(nav)
    calmar = float(cagr / abs(mdd)) if abs(mdd) > 0 else 0.0

    # Win rate
    win_rate = float((clean_rets > 0).mean())

    metrics = {
        "Total Return": total_ret,
        "CAGR": cagr,
        "Annualized Volatility": ann_vol,
        "Sharpe Ratio": sharpe,
        "Sortino Ratio": sortino,
        "Max Drawdown": mdd,
        "Calmar Ratio": calmar,
        "Daily Win Rate": win_rate,
        "Trading Days": n_days,
        "Years": years,
    }

    # Benchmark-relative metrics (FTSE MIB)
    if benchmark_returns is not None:
        aligned = pd.concat([clean_rets, benchmark_returns], axis=1, join="inner").dropna()
        if len(aligned) > 20:
            strat_r = aligned.iloc[:, 0]
            bench_r = aligned.iloc[:, 1]

            cov_matrix = np.cov(strat_r, bench_r)
            cov_sb = cov_matrix[0, 1]
            var_b = cov_matrix[1, 1]

            beta = float(cov_sb / var_b) if var_b > 0 else 1.0
            corr = float(np.corrcoef(strat_r, bench_r)[0, 1])

            # Jensen's Alpha (annualized)
            bench_cagr = float((1.0 + bench_r).prod() ** (252.0 / len(bench_r)) - 1.0)
            alpha = float((cagr - risk_free_rate) - beta * (bench_cagr - risk_free_rate))

            # Tracking error and Information ratio
            diff_r = strat_r - bench_r
            te = float(diff_r.std() * np.sqrt(252.0))
            ir = float((cagr - bench_cagr) / te) if te > 0 else 0.0

            metrics["Beta vs FTSE MIB"] = beta
            metrics["Alpha vs FTSE MIB"] = alpha
            metrics["Correlation with FTSE MIB"] = corr
            metrics["Tracking Error"] = te
            metrics["Information Ratio"] = ir
            metrics["FTSE MIB CAGR"] = bench_cagr

    return metrics


def format_metrics_table(metrics_dict: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    """Formats metrics dictionary into a clean comparison DataFrame with percent/decimal formatting."""
    df = pd.DataFrame(metrics_dict)
    formatted = pd.DataFrame(index=df.index, columns=df.columns, dtype=object)

    pct_rows = [
        "Total Return", "CAGR", "Annualized Volatility", "Max Drawdown",
        "Daily Win Rate", "Alpha vs FTSE MIB", "Tracking Error", "FTSE MIB CAGR"
    ]
    ratio_rows = [
        "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
        "Beta vs FTSE MIB", "Correlation with FTSE MIB", "Information Ratio"
    ]

    for col in df.columns:
        for idx in df.index:
            val = df.loc[idx, col]
            if pd.isnull(val):
                formatted.loc[idx, col] = "N/A"
            elif idx in pct_rows:
                formatted.loc[idx, col] = f"{val * 100:.2f}%"
            elif idx in ratio_rows:
                formatted.loc[idx, col] = f"{val:.2f}"
            elif idx == "Trading Days":
                formatted.loc[idx, col] = f"{int(val):,}"
            elif idx == "Years":
                formatted.loc[idx, col] = f"{val:.1f}"
            else:
                formatted.loc[idx, col] = str(val)

    return formatted
