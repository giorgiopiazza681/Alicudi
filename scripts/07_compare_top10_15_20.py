"""Script 07: Sensitivity Analysis of Portfolio Concentration (Top-10 vs Top-15 vs Top-20).

Compares walk-forward Point-in-Time performance (2000 - 2026) when varying the number
of portfolio holdings N in {10, 15, 20} against FTSE MIB Total Return (Gross Dividends).
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
from src.fundamental_engine import FundamentalEngine, Top10QualityValueModel
from src.backtest_engine import BacktestEngine
from src.performance import compute_metrics, format_metrics_table


def main():
    proc_dir = config.PROCESSED_DIR
    pit_dir = proc_dir / "fundamentals_pit"
    prices_matrix = pd.read_parquet(proc_dir / "prices_matrix.parquet")
    returns_matrix = pd.read_parquet(proc_dir / "returns_matrix.parquet")
    bench_df = pd.read_parquet(proc_dir / "benchmark_returns.parquet")
    bench_tr = bench_df["FTSEMIB_TR"] if "FTSEMIB_TR" in bench_df.columns else bench_df.iloc[:, 0]
    mcap_path = proc_dir / "market_cap_matrix.parquet"
    mcap_matrix = pd.read_parquet(mcap_path) if mcap_path.exists() else None

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

    engine_q = BacktestEngine(
        rebalance_freq="Q",
        lookback_days=252,
        cost_bps=config.TRANSACTION_COST_BPS,
    )

    configs = [
        {"name": "Top-10 (10.0% each)", "top_n": 10, "buffer_rank": 15, "max_per_sector": 3},
        {"name": "Top-15 (6.67% each)", "top_n": 15, "buffer_rank": 22, "max_per_sector": 4},
        {"name": "Top-20 (5.00% each)", "top_n": 20, "buffer_rank": 30, "max_per_sector": 5},
    ]

    results = {}
    models = {}
    all_metrics = {}
    nav_dict = {}

    graduated_tks = (
        mcap_matrix.columns[mcap_matrix.iloc[-1] > config.MARKET_CAP_THRESHOLD_EUR]
        if mcap_matrix is not None else pd.Index([])
    )

    for cfg in configs:
        name = cfg["name"]
        model = Top10QualityValueModel(
            pit_data=pit_data,
            top_n=cfg["top_n"],
            buffer_rank=cfg["buffer_rank"],
            max_per_sector=cfg["max_per_sector"],
            use_safety_filter=True,
            use_debt_penalty=True,
        )
        res = engine_q.run(
            model=model,
            strategy_name=name,
            returns_matrix=returns_matrix,
            prices_matrix=prices_matrix,
            min_assets=10,
        )
        results[name] = res
        models[name] = model
        nav_dict[name] = res.nav_series

        m = compute_metrics(res.daily_returns, benchmark_returns=bench_tr)
        m["Avg Quarterly Turnover"] = float(res.turnover_history.mean())

        # Rolling 1Y stats
        eval_dates = res.nav_series.index
        b_sub = bench_tr.reindex(eval_dates).fillna(0.0)
        b_nav = (1.0 + b_sub).cumprod() * 100.0

        roll_s = (res.nav_series / res.nav_series.shift(252) - 1.0).dropna() * 100.0
        roll_b = (b_nav / b_nav.shift(252) - 1.0).dropna() * 100.0
        c_idx = roll_s.index.intersection(roll_b.index)
        roll_s, roll_b = roll_s.loc[c_idx], roll_b.loc[c_idx]
        spread_1y = roll_s - roll_b

        m["1Y Rolling Mean"] = float(roll_s.mean()) / 100.0
        m["1Y Rolling Median"] = float(roll_s.median()) / 100.0
        m["1Y Rolling Win Rate vs MIB TR"] = float((spread_1y > 0).mean())
        m["1Y VaR 95% (5th Pct)"] = float(np.percentile(roll_s, 5)) / 100.0
        m["1Y 95th Percentile"] = float(np.percentile(roll_s, 95)) / 100.0

        hist_df = pd.concat(model.selection_logs, ignore_index=True)
        opa_cnt = hist_df[hist_df["status"] == "DELISTED_OPA"]["company_name"].nunique()
        bankrupt_cnt = hist_df[hist_df["status"].isin(["DELISTED_BANKRUPTCY", "DELISTED_REVOKED"])]["company_name"].nunique()
        multi_cnt = hist_df[hist_df["ticker"].isin(graduated_tks)]["company_name"].nunique()

        m["Bankruptcies Bought"] = bankrupt_cnt
        m["M&A Takeovers (OPA) Captured"] = opa_cnt
        m["Graduated Multibaggers Captured"] = multi_cnt
        all_metrics[name] = m

    # Add FTSE MIB TR
    eval_dates = results["Top-10 (10.0% each)"].nav_series.index
    bench_sub = bench_tr.reindex(eval_dates).dropna()
    bench_nav = (1.0 + bench_sub).cumprod() * 100.0
    nav_dict["FTSE MIB TR (Gross Dividends)"] = bench_nav

    bm = compute_metrics(bench_sub, benchmark_returns=None)
    roll_b = (bench_nav / bench_nav.shift(252) - 1.0).dropna() * 100.0
    bm["1Y Rolling Mean"] = float(roll_b.mean()) / 100.0
    bm["1Y Rolling Median"] = float(roll_b.median()) / 100.0
    bm["1Y Rolling Win Rate vs MIB TR"] = 0.0
    bm["1Y VaR 95% (5th Pct)"] = float(np.percentile(roll_b, 5)) / 100.0
    bm["1Y 95th Percentile"] = float(np.percentile(roll_b, 95)) / 100.0
    all_metrics["FTSE MIB TR (Gross Dividends)"] = bm

    print("=" * 100)
    print("PORTFOLIO CONCENTRATION SENSITIVITY: TOP-10 vs TOP-15 vs TOP-20 (2000 - 2026)")
    print("=" * 100)
    raw_df = pd.DataFrame(all_metrics)
    for idx in [
        "Total Return", "CAGR", "Annualized Volatility", "Sharpe Ratio", "Sortino Ratio",
        "Max Drawdown", "Calmar Ratio", "Beta vs FTSE MIB", "Alpha vs FTSE MIB",
        "Tracking Error", "Information Ratio", "Avg Quarterly Turnover",
        "1Y Rolling Mean", "1Y Rolling Median", "1Y Rolling Win Rate vs MIB TR",
        "1Y VaR 95% (5th Pct)", "1Y 95th Percentile",
        "Bankruptcies Bought", "M&A Takeovers (OPA) Captured", "Graduated Multibaggers Captured"
    ]:
        if idx in raw_df.index:
            row_vals = []
            for col in raw_df.columns:
                v = raw_df.loc[idx, col]
                if pd.isna(v):
                    row_vals.append("N/A")
                elif idx in [
                    "Total Return", "CAGR", "Annualized Volatility", "Max Drawdown",
                    "Alpha vs FTSE MIB", "Tracking Error", "Avg Quarterly Turnover",
                    "1Y Rolling Mean", "1Y Rolling Median", "1Y Rolling Win Rate vs MIB TR",
                    "1Y VaR 95% (5th Pct)", "1Y 95th Percentile"
                ]:
                    row_vals.append(f"{v*100:.2f}%")
                elif idx in ["Bankruptcies Bought", "M&A Takeovers (OPA) Captured", "Graduated Multibaggers Captured"]:
                    row_vals.append(f"{int(v)}")
                else:
                    row_vals.append(f"{v:.2f}")
            print(f"{idx:<34} | " + " | ".join(f"{x:>20}" for x in row_vals))

    # Sub-period CAGR comparison
    print("\n" + "=" * 100)
    print("SUB-PERIOD CAGR & MAX DRAWDOWN ANALYSIS BY MARKET REGIME")
    print("=" * 100)
    regimes = [
        ("2000-2007 (Dot-Com & Value Cycle)", "2000-01-01", "2007-12-31"),
        ("2008-2012 (GFC & Euro Debt Crisis)", "2008-01-01", "2012-12-31"),
        ("2013-2019 (PIR & Mid/Small Boom)", "2013-01-01", "2019-12-31"),
        ("2020-2026 (COVID, Inflation & Rates)", "2020-01-01", "2026-10-07"),
    ]
    for r_label, s_dt, e_dt in regimes:
        line_cagr = []
        line_mdd = []
        for col, nav_s in nav_dict.items():
            sub_nav = nav_s.loc[s_dt:e_dt]
            if len(sub_nav) > 20:
                tot = sub_nav.iloc[-1] / sub_nav.iloc[0] - 1.0
                yrs = len(sub_nav) / 252.0
                cagr = (1.0 + tot) ** (1.0 / yrs) - 1.0
                pk = sub_nav.cummax()
                mdd = ((sub_nav - pk) / pk).min()
                line_cagr.append(f"{cagr*100:+6.2f}% (MDD {mdd*100:5.1f}%)")
            else:
                line_cagr.append("N/A")
        print(f"{r_label:<36} | " + " | ".join(f"{x:>20}" for x in line_cagr))

    # Save comparison chart
    nav_df = pd.DataFrame(nav_dict).dropna()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [2.3, 1.2]})
    colors = {
        "Top-10 (10.0% each)": "#e31a1c",
        "Top-15 (6.67% each)": "#1f78b4",
        "Top-20 (5.00% each)": "#33a02c",
        "FTSE MIB TR (Gross Dividends)": "#111111",
    }
    for col in nav_df.columns:
        ls = "--" if "FTSE MIB" in col else "-"
        lw = 2.6 if "Top-10" in col or "Top-15" in col else 2.1
        ax1.plot(nav_df.index, nav_df[col], label=col, color=colors[col], linewidth=lw, linestyle=ls)

    ax1.set_title(
        "Portfolio Concentration Sensitivity: Top-10 vs. Top-15 vs. Top-20 Holdings (2000 - 2026)\n"
        "Survivorship-Bias-Free Point-in-Time Italian Small & Mid Caps (< €500M)",
        fontsize=13,
        fontweight="bold",
    )
    ax1.set_ylabel("Portfolio Value (Base = 100)", fontsize=12)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.legend(loc="upper left", frameon=True, fontsize=11)

    for col in nav_df.columns:
        pk = nav_df[col].cummax()
        dd = (nav_df[col] - pk) / pk * 100.0
        ls = "--" if "FTSE MIB" in col else "-"
        ax2.plot(nav_df.index, dd, label=f"{col} (MDD: {dd.min():.1f}%)", color=colors[col], linewidth=1.8, linestyle=ls)

    ax2.set_title("Historical Drawdown (%)", fontsize=12, fontweight="bold")
    ax2.set_xlabel("Date", fontsize=12)
    ax2.set_ylabel("Drawdown (%)", fontsize=12)
    ax2.grid(True, linestyle=":", alpha=0.6)
    ax2.legend(loc="lower left", frameon=True, fontsize=10)

    plt.tight_layout()
    out_chart = config.REPORTS_DIR / "concentration_sensitivity_10_15_20.png"
    plt.savefig(out_chart, dpi=300)
    plt.close()
    print(f"\nSaved concentration comparison chart to: {out_chart}")


if __name__ == "__main__":
    main()
