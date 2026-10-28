"""Configuration module for Italian Small/Mid Cap Quantitative Portfolio Project.
"""

from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PRICES_DIR = RAW_DIR / "prices"
FINANCIALS_DIR = RAW_DIR / "financials"
INFO_DIR = RAW_DIR / "info"
BENCHMARK_DIR = RAW_DIR / "benchmark"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = BASE_DIR / "reports"

# Universe & Filtering Parameters
BENCHMARK_TICKER = "FTSEMIB.MI"
MARKET_CAP_THRESHOLD_EUR = 500_000_000  # 500 Million EUR
MIN_TRADING_DAYS = 252                 # At least 1 year of trading history
MIN_DAILY_TURNOVER_EUR = 20_000        # Minimum average daily traded value (ADTV) to avoid illiquidity traps
MAX_ZERO_VOLUME_PCT = 0.25             # Exclude stocks that don't trade on >25% of trading days

# Backtest Defaults
DEFAULT_REBALANCE_FREQ = "M"           # "M" (Monthly), "Q" (Quarterly), "Y" (Yearly)
DEFAULT_LOOKBACK_DAYS = 252            # 1 Year covariance & estimation window
TRANSACTION_COST_BPS = 20              # 20 basis points (0.20%) per one-way trade (spread + fees)
MAX_STOCK_WEIGHT = 0.10                # Maximum 10% weight per individual stock (concentration risk control)
RISK_FREE_RATE = 0.025                 # 2.5% annualized risk-free rate for Sharpe calculation
