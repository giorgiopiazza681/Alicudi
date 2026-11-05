"""Configuration module for the Alicudi Quantitative Portfolio Strategy.
"""

from pathlib import Path

# Directory Paths
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
MARKET_CAP_THRESHOLD_EUR = 1_000_000_000  # €1.0 Billion Point-in-Time Market Cap limit
MIN_TRADING_DAYS = 252                    # Minimum 1 year of trading history
MIN_DAILY_TURNOVER_EUR = 20_000           # Minimum average daily traded value (ADTV) in EUR
MAX_ZERO_VOLUME_PCT = 0.25                # Exclude stocks with >25% zero-volume trading days

# Strategy & Portfolio Construction Parameters ("My Strategy")
PORTFOLIO_TOP_N = 15                      # Number of equal-weighted holdings (6.67% each)
PORTFOLIO_BUFFER_RANK = 22                # Hysteresis buffer rank to reduce quarterly turnover
MAX_STOCKS_PER_SECTOR = 4                 # Maximum holdings per GICS sector
MAX_STOCK_WEIGHT = 1.0 / PORTFOLIO_TOP_N

# Walk-Forward Backtest Defaults
DEFAULT_REBALANCE_FREQ = "Q"              # Quarterly rebalancing
DEFAULT_LOOKBACK_DAYS = 252               # 1-Year lookback window (252 trading days)
TRANSACTION_COST_BPS = 20                 # 20 bps (0.20%) per one-way trade
RISK_FREE_RATE = 0.025                    # 2.5% annualized risk-free rate
