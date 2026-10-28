"""Backtesting Engine with realistic rebalancing, turnover tracking, and transaction costs.
"""

import logging
from typing import Dict, List, Optional, Tuple, Type

import numpy as np
import pandas as pd

import config
from src.portfolio_models import PortfolioModel

logger = logging.getLogger(__name__)


class BacktestResult:
    """Encapsulates backtest output, returns series, weights, and turnover metrics."""

    def __init__(
        self,
        strategy_name: str,
        nav_series: pd.Series,
        daily_returns: pd.Series,
        weights_history: pd.DataFrame,
        turnover_history: pd.Series,
        rebalance_dates: List[pd.Timestamp],
        transaction_costs: pd.Series
    ):
        self.strategy_name = strategy_name
        self.nav_series = nav_series
        self.daily_returns = daily_returns
        self.weights_history = weights_history
        self.turnover_history = turnover_history
        self.rebalance_dates = rebalance_dates
        self.transaction_costs = transaction_costs


class BacktestEngine:
    """Executes walk-forward portfolio simulations."""

    def __init__(
        self,
        rebalance_freq: str = config.DEFAULT_REBALANCE_FREQ,  # "M" (Monthly), "Q" (Quarterly)
        lookback_days: int = config.DEFAULT_LOOKBACK_DAYS,    # 252 days
        cost_bps: float = config.TRANSACTION_COST_BPS,        # 20 bps = 0.20%
        cap_threshold_eur: float = config.MARKET_CAP_THRESHOLD_EUR,
    ):
        self.rebalance_freq = rebalance_freq
        self.lookback_days = lookback_days
        self.cost_rate = cost_bps / 10_000.0
        self.cap_threshold_eur = cap_threshold_eur

    def get_rebalance_dates(self, dates: pd.DatetimeIndex) -> List[pd.Timestamp]:
        """Finds periodic rebalancing points matching the frequency schedule."""
        df_dates = pd.DataFrame({"date": dates}, index=dates)
        # Handle pandas 2.2+ and 3.0 frequency naming changes
        alias_map = {"M": "ME", "Q": "QE", "Y": "YE", "A": "YE"}
        freq = alias_map.get(self.rebalance_freq, self.rebalance_freq)
        grouped = df_dates.resample(freq).first().dropna()
        reb_dates = [d for d in grouped["date"] if d in dates]
        return reb_dates

    def run(
        self,
        model: PortfolioModel,
        strategy_name: str,
        returns_matrix: pd.DataFrame,
        prices_matrix: pd.DataFrame,
        min_assets: int = 5,
        market_cap_matrix: Optional[pd.DataFrame] = None,
    ) -> BacktestResult:
        """Executes walk-forward backtest.

        Args:
            model: Instance of PortfolioModel.
            strategy_name: Label for reports.
            returns_matrix: Synchronized matrix of daily returns.
            prices_matrix: Synchronized matrix of adjusted prices.
            min_assets: Minimum active assets required to form portfolio.
        """
        all_dates = returns_matrix.index
        if len(all_dates) <= self.lookback_days:
            raise ValueError(
                f"Insufficient dates ({len(all_dates)}) for lookback ({self.lookback_days})."
            )

        # Slice after initial lookback period
        eval_dates = all_dates[self.lookback_days:]
        all_reb_dates = self.get_rebalance_dates(eval_dates)

        if not all_reb_dates:
            raise ValueError("No rebalance dates found within evaluation period.")

        logger.info(
            f"Running {strategy_name}: {len(eval_dates)} days, "
            f"{len(all_reb_dates)} rebalances ({self.rebalance_freq} frequency)."
        )

        n_days = len(eval_dates)
        tickers = returns_matrix.columns
        weights_hist = {}
        turnover_hist = pd.Series(index=all_reb_dates, dtype=float)
        costs_hist = pd.Series(0.0, index=eval_dates)

        # Portfolio NAV and daily return tracking
        nav = pd.Series(index=eval_dates, dtype=float)
        port_daily_ret = pd.Series(0.0, index=eval_dates)

        # Load Point-in-Time Market Cap matrix if not passed explicitly
        if market_cap_matrix is None:
            mcap_path = config.PROCESSED_DIR / "market_cap_matrix.parquet"
            if mcap_path.exists():
                try:
                    market_cap_matrix = pd.read_parquet(mcap_path)
                except Exception:
                    market_cap_matrix = None

        current_weights = pd.Series(0.0, index=tickers)
        reb_idx = 0
        current_nav = 100.0  # Normalized base

        for i, dt in enumerate(eval_dates):
            # Check if today is a rebalance day
            if reb_idx < len(all_reb_dates) and dt == all_reb_dates[reb_idx]:
                # Locate lookback window
                loc_idx = all_dates.get_loc(dt)
                window_rets = returns_matrix.iloc[loc_idx - self.lookback_days : loc_idx]

                # Identify Point-in-Time active assets at rebalance date dt:
                # 1. Must be actively listed/quoted on date dt (not already delisted)
                # 2. Must have Point-in-Time Market Cap <= cap_threshold_eur (500M EUR) on date dt
                # 3. Must have at least 75% valid daily return observations in the lookback window
                currently_listed = prices_matrix.loc[dt].notna()
                if market_cap_matrix is not None and dt in market_cap_matrix.index:
                    mcap_dt = market_cap_matrix.loc[dt].reindex(tickers)
                    # New entries must be <= 500M EUR; existing holdings can stay up to 650M EUR graduation buffer
                    is_held = current_weights > 0.0
                    cap_limit = pd.Series(self.cap_threshold_eur, index=tickers)
                    cap_limit.loc[is_held] = self.cap_threshold_eur * 1.30
                    under_cap_pit = mcap_dt.isna() | (mcap_dt <= cap_limit)
                else:
                    under_cap_pit = pd.Series(True, index=tickers)

                valid_mask = (window_rets.count() >= (self.lookback_days * 0.75)) & currently_listed & under_cap_pit
                active_rets = window_rets.loc[:, valid_mask].dropna(axis=1, thresh=int(self.lookback_days * 0.75))

                if active_rets.shape[1] >= min_assets:
                    new_weights = model.calculate_weights(active_rets).reindex(tickers).fillna(0.0)
                    # Normalize
                    if new_weights.sum() > 0:
                        new_weights = new_weights / new_weights.sum()
                else:
                    new_weights = current_weights.copy()

                # Calculate turnover and transaction cost
                turnover = np.sum(np.abs(new_weights - current_weights))
                cost = turnover * self.cost_rate
                costs_hist.loc[dt] = cost
                turnover_hist.loc[dt] = turnover

                current_weights = new_weights
                weights_hist[dt] = current_weights.copy()
                reb_idx += 1

            # Daily asset returns on date dt
            day_rets = returns_matrix.loc[dt].fillna(0.0)

            # Portfolio gross return
            gross_return = np.dot(current_weights, day_rets)

            # Deduct transaction cost if rebalance occurred today
            net_return = gross_return - costs_hist.loc[dt]
            port_daily_ret.loc[dt] = net_return

            # Update NAV
            current_nav *= (1.0 + net_return)
            nav.loc[dt] = current_nav

            # Drift weights based on asset price moves during the holding period
            asset_growths = current_weights * (1.0 + day_rets)
            total_growth = asset_growths.sum()
            if total_growth > 0:
                current_weights = asset_growths / total_growth

        weights_df = pd.DataFrame(weights_hist).T

        return BacktestResult(
            strategy_name=strategy_name,
            nav_series=nav,
            daily_returns=port_daily_ret,
            weights_history=weights_df,
            turnover_history=turnover_hist,
            rebalance_dates=all_reb_dates,
            transaction_costs=costs_hist
        )
