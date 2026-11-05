import pandas as pd
import numpy as np

# Load historical selections
df = pd.read_csv('reports/top10_historical_selections.csv')
prices = pd.read_parquet('data/processed/prices_matrix.parquet')
df['date'] = pd.to_datetime(df['date'])
recent_df = df[df['date'] >= '2022-01-01'].copy()

results = []
rebalance_dates = sorted(recent_df['date'].unique())

for i, dt in enumerate(rebalance_dates):
    next_dt = rebalance_dates[i+1] if i+1 < len(rebalance_dates) else prices.index[-1]
    batch = recent_df[recent_df['date'] == dt]
    for _, row in batch.iterrows():
        tk = row['ticker']
        if tk in prices.columns and dt in prices.index and next_dt in prices.index:
            p_start = prices.loc[dt, tk]
            p_end = prices.loc[next_dt, tk]
            if pd.notnull(p_start) and pd.notnull(p_end) and p_start > 0:
                ret = (p_end / p_start) - 1.0
                results.append({
                    'ticker': tk,
                    'company_name': row['company_name'],
                    'sector': row['sector'],
                    'entry_date': dt.strftime('%Y-%m-%d'),
                    'exit_date': next_dt.strftime('%Y-%m-%d'),
                    'period_return': ret,
                    'pe': row.get('pe_ratio', np.nan),
                    'roe': row.get('roe', np.nan),
                    'de': row.get('debt_to_equity', np.nan)
                })

res_df = pd.DataFrame(results)

print("=== WORST INDIVIDUAL HOLDING QUARTERS (2022 - 2026) ===")
worst_q = res_df.sort_values('period_return').head(12)
for _, r in worst_q.iterrows():
    print(f"{r['ticker']:<8} | {r['company_name']:<25} | {r['sector']:<22} | {r['entry_date']} -> {r['exit_date']} | Return: {r['period_return']*100:+6.2f}%")

print("\n=== WORST COMPOUNDED CUMULATIVE RETURNS WHILE IN PORTFOLIO (2022 - 2026) ===")
cum = res_df.groupby(['ticker', 'company_name', 'sector']).agg(
    quarters=('period_return', 'count'),
    cum_ret=('period_return', lambda x: (np.prod(1.0 + x) - 1.0) * 100.0),
    avg_q=('period_return', lambda x: np.mean(x) * 100.0)
).reset_index().sort_values('cum_ret')

for _, r in cum.head(15).iterrows():
    print(f"{r['ticker']:<8} | {r['company_name']:<25} | {r['sector']:<22} | Quarters: {r['quarters']:2d} | Cumulative: {r['cum_ret']:+6.2f}% | Avg Q: {r['avg_q']:+5.2f}%")
