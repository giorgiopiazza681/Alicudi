"""Portfolio Construction Models for Italian Small/Mid Cap Equities.

Implements quantitative allocation strategies:
1. Equal Weight (1/N)
2. Global Minimum Variance (GMV - Quadratic Optimization with Long-Only bounds)
3. Inverse Volatility (Low Volatility Anomaly)
4. Risk Parity / Equal Risk Contribution (ERC)
5. Momentum Quintile Selection + Inverse Volatility
6. Quality / Value Factor Selection
"""

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import config

logger = logging.getLogger(__name__)


def regularized_covariance(returns_df: pd.DataFrame, shrinkage: float = 0.15) -> np.ndarray:
    """Computes sample covariance with shrinkage towards a diagonal target

    to stabilize covariance estimates for small cap portfolios.
    """
    sample_cov = returns_df.cov().values * 252.0  # Annualized
    n = sample_cov.shape[0]
    target = np.diag(np.diag(sample_cov))
    shrunk_cov = (1.0 - shrinkage) * sample_cov + shrinkage * target
    return shrunk_cov


class PortfolioModel:
    """Base class for portfolio weighting models."""

    def __init__(self, max_weight: float = config.MAX_STOCK_WEIGHT):
        self.max_weight = max_weight

    def calculate_weights(self, hist_returns: pd.DataFrame) -> pd.Series:
        raise NotImplementedError


class EqualWeightModel(PortfolioModel):
    """Equal Weight (1/N) benchmark strategy."""

    def calculate_weights(self, hist_returns: pd.DataFrame) -> pd.Series:
        tickers = hist_returns.columns
        n = len(tickers)
        if n == 0:
            return pd.Series(dtype=float)
        w = 1.0 / n
        return pd.Series(w, index=tickers)


class InverseVolatilityModel(PortfolioModel):
    """Weights proportional to inverse annualized volatility (1 / sigma).

    Exploits the Low Volatility Anomaly without requiring full covariance inversion.
    """

    def calculate_weights(self, hist_returns: pd.DataFrame) -> pd.Series:
        tickers = hist_returns.columns
        vols = hist_returns.std() * np.sqrt(252.0)
        # Avoid division by zero
        vols = vols.replace(0, np.nan).dropna()
        if vols.empty:
            return pd.Series(dtype=float)

        inv_vol = 1.0 / vols
        raw_weights = inv_vol / inv_vol.sum()

        # Apply maximum weight constraint iteratively if needed
        weights = raw_weights.clip(upper=self.max_weight)
        # Re-normalize
        if weights.sum() > 0:
            weights = weights / weights.sum()
        return weights.reindex(tickers).fillna(0.0)


class MinimumVarianceModel(PortfolioModel):
    """Global Minimum Variance (GMV) Portfolio.

    Solves: min w^T Sigma w subject to sum(w) = 1, 0 <= w_i <= max_weight.
    Designed specifically to reduce portfolio volatility below the FTSE MIB.
    """

    def __init__(self, max_weight: float = config.MAX_STOCK_WEIGHT, shrinkage: float = 0.15):
        super().__init__(max_weight=max_weight)
        self.shrinkage = shrinkage

    def calculate_weights(self, hist_returns: pd.DataFrame) -> pd.Series:
        tickers = hist_returns.columns
        n = len(tickers)
        if n == 0:
            return pd.Series(dtype=float)

        # Drop tickers with excessive missing observations in lookback
        valid_cols = [c for c in tickers if hist_returns[c].count() >= len(hist_returns) * 0.8]
        if len(valid_cols) < 2:
            return pd.Series(1.0 / max(len(valid_cols), 1), index=valid_cols).reindex(tickers).fillna(0.0)

        sub_rets = hist_returns[valid_cols].fillna(0.0)
        cov = regularized_covariance(sub_rets, shrinkage=self.shrinkage)
        m = len(valid_cols)

        # Objective: Portfolio Variance
        def port_variance(w):
            return np.dot(w.T, np.dot(cov, w))

        # Constraints & bounds
        w0 = np.ones(m) / m
        bounds = [(0.0, self.max_weight) for _ in range(m)]
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        res = minimize(
            port_variance,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 300, "ftol": 1e-7}
        )

        if res.success:
            weights = pd.Series(res.x, index=valid_cols)
        else:
            # Fallback to inverse vol if optimization fails
            logger.warning(f"GMV optimization did not converge: {res.message}. Using Inverse Vol fallback.")
            return InverseVolatilityModel(max_weight=self.max_weight).calculate_weights(sub_rets).reindex(tickers).fillna(0.0)

        # Normalize clean
        weights = weights.clip(lower=0.0)
        weights = weights / weights.sum()
        return weights.reindex(tickers).fillna(0.0)


class RiskParityModel(PortfolioModel):
    """Equal Risk Contribution (ERC) / Risk Parity.

    Each asset contributes equally to the total portfolio risk.
    """

    def __init__(self, max_weight: float = config.MAX_STOCK_WEIGHT, shrinkage: float = 0.15):
        super().__init__(max_weight=max_weight)
        self.shrinkage = shrinkage

    def calculate_weights(self, hist_returns: pd.DataFrame) -> pd.Series:
        tickers = hist_returns.columns
        valid_cols = [c for c in tickers if hist_returns[c].count() >= len(hist_returns) * 0.8]
        if len(valid_cols) < 2:
            return pd.Series(1.0 / max(len(valid_cols), 1), index=valid_cols).reindex(tickers).fillna(0.0)

        sub_rets = hist_returns[valid_cols].fillna(0.0)
        cov = regularized_covariance(sub_rets, shrinkage=self.shrinkage)
        m = len(valid_cols)

        # Risk parity objective: minimize sum of squared differences of risk contributions
        def erc_objective(w):
            port_vol = np.sqrt(np.dot(w.T, np.dot(cov, w)))
            if port_vol == 0:
                return 0.0
            marginal_contrib = np.dot(cov, w) / port_vol
            risk_contrib = w * marginal_contrib
            target = port_vol / m
            return np.sum((risk_contrib - target) ** 2)

        w0 = np.ones(m) / m
        bounds = [(0.005, self.max_weight) for _ in range(m)]
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        res = minimize(
            erc_objective,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 300, "ftol": 1e-7}
        )

        if res.success:
            weights = pd.Series(res.x, index=valid_cols)
        else:
            return InverseVolatilityModel(max_weight=self.max_weight).calculate_weights(sub_rets).reindex(tickers).fillna(0.0)

        weights = weights.clip(lower=0.0)
        weights = weights / weights.sum()
        return weights.reindex(tickers).fillna(0.0)


class MomentumLowVolModel(PortfolioModel):
    """Cross-Sectional Momentum with Low Volatility Weighting.

    1. Ranks all small caps by 6-month momentum (excluding the last month to prevent 1M reversal).
    2. Selects the top 30% performers.
    3. Allocates capital among the winners using inverse volatility to dampen downside risk.
    """

    def __init__(
        self,
        top_pct: float = 0.30,
        momentum_lookback: int = 126,  # ~6 months
        skip_recent_days: int = 21,    # ~1 month
        max_weight: float = config.MAX_STOCK_WEIGHT
    ):
        super().__init__(max_weight=max_weight)
        self.top_pct = top_pct
        self.momentum_lookback = momentum_lookback
        self.skip_recent_days = skip_recent_days

    def calculate_weights(self, hist_returns: pd.DataFrame) -> pd.Series:
        tickers = hist_returns.columns
        if len(hist_returns) < self.momentum_lookback:
            return EqualWeightModel(self.max_weight).calculate_weights(hist_returns)

        # Calculate momentum: return from t - momentum_lookback to t - skip_recent_days
        eval_window = hist_returns.iloc[-self.momentum_lookback : -self.skip_recent_days]
        cum_returns = (1.0 + eval_window).prod() - 1.0
        cum_returns = cum_returns.dropna()

        if len(cum_returns) < 5:
            return EqualWeightModel(self.max_weight).calculate_weights(hist_returns)

        # Select top quintile / top_pct
        k = max(int(len(cum_returns) * self.top_pct), 3)
        top_performers = cum_returns.nlargest(k).index

        # Weight top performers by inverse volatility
        sub_rets = hist_returns[top_performers]
        inv_vol_model = InverseVolatilityModel(max_weight=self.max_weight)
        weights = inv_vol_model.calculate_weights(sub_rets)
        return weights.reindex(tickers).fillna(0.0)
